"""Exact experiment approvals and a durable adapter to the reviewed H1 dispatcher.

runner_cpu uses the real held-child dispatcher with an isolated CPU workload.
real uses the same code but needs its own exact proposal; fake evidence never
confers real authorization. No default training allowance exists.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from .store import Conflict, canonical, atomic, sha, Store
from .policy import stopped, STOP_PATHS
from .jobs import identity, owns, _kill_owned

DISPATCHER = Path.home()/'.local/share/rlflow-standalone/adapters/unconfigured/local_dispatch.py'


def file_pin(path):
    p=Path(path).resolve(strict=True)
    if not p.is_file(): raise Conflict('input pin must be a file')
    return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def check_pins(spec):
    for name,pin in spec['pins'].items():
        if not isinstance(pin,dict) or set(pin)!={'path','sha256'} or file_pin(pin['path'])!=pin:
            raise Conflict('experiment input drift: '+name)
    dispatcher = DISPATCHER
    if spec.get('backend') == 'real':
        h1 = spec.get('h1')
        if not isinstance(h1, dict) or not isinstance(h1.get('workload_root'), str):
            raise Conflict('real experiment dispatcher requires an exact H1 workload root')
        dispatcher = Path(h1['workload_root']) / 'training_workloads/unified_h1/local_dispatch.py'
    if spec['pins']['dispatcher']!=file_pin(dispatcher):
        raise Conflict('experiment must use the reviewed H1 dispatcher')


def validate(spec, root):
    required={'id','stage_id','backend','argv','cwd','pins','method','evaluation','runtime','seed','resources','conditions','observations'}
    if not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'h1'}:raise Conflict('complete experiment specification required')
    if spec['backend'] not in {'runner_cpu','real'}:raise Conflict('unsupported experiment backend')
    for key in ('id','stage_id','method','evaluation','runtime'):
        if not isinstance(spec[key],str) or not spec[key].strip():raise Conflict('experiment identity missing: '+key)
    if type(spec['seed']) is not int:raise Conflict('fixed integer seed required')
    if not isinstance(spec['argv'],list) or not spec['argv'] or any(not isinstance(x,str) for x in spec['argv']):raise Conflict('invalid argv')
    if set(spec['pins'])!={'dispatcher','executable','product','workload','runtime','authorization'}:raise Conflict('all exact input pins required')
    check_pins(spec)
    if spec['argv'][0]!=spec['pins']['executable']['path']:raise Conflict('executable binding mismatch')
    resources=spec['resources']
    if not isinstance(resources,dict) or set(resources)!={'starts','wall_seconds','gpu_seconds','transitions'}:raise Conflict('explicit resource dimensions required')
    if resources['starts']!=1 or any(type(v) is not int or v<0 for v in resources.values()) or not 1<=resources['wall_seconds']<=86400:raise Conflict('invalid exact experiment resources')
    cwd=Path(spec['cwd']).resolve(strict=True)
    if not cwd.is_dir():raise Conflict('invalid working directory')
    if spec['backend']=='runner_cpu':
        if resources['gpu_seconds'] or resources['transitions'] or not cwd.is_relative_to(Path(root)/'workspaces'):
            raise Conflict('CPU adapter cannot access training resources')
    if not isinstance(spec['conditions'],list) or not spec['conditions']:raise Conflict('explicit structured conditions required')
    for c in spec['conditions']:
        if not isinstance(c,dict) or set(c)!={'evidence_id','sha256'}:raise Conflict('only accepted evidence hash predicates supported')
    if not isinstance(spec['observations'],list) or not spec['observations'] or any(not isinstance(x,str) or not x for x in spec['observations']):raise Conflict('required observations missing')
    if spec['backend']=='real':
        from .h1 import validate as validate_h1
        validate_h1(spec,root)
    elif 'h1' in spec:raise Conflict('CPU substitute cannot carry real H1 authority')
    return spec


def propose(store,spec):
    validate(spec,store.root)
    content={'scope':'EXPERIMENT','stage_id':spec['stage_id'],'spec':spec,
             'budget':{'role_calls':0,'wall_seconds':spec['resources']['wall_seconds'],'fake_starts':0},
             'preconditions':['exact pins','accepted condition hashes','STOP clear','single submission']}
    digest=sha(content);pid='P-'+digest[:16]
    def change(s):
        for old in s['proposals'].values():
            if old['content'].get('scope')=='EXPERIMENT' and old['content']['spec']['id']==spec['id'] and old['sha256']!=digest:
                raise Conflict('experiment ID already binds another immutable specification')
        s['proposals'][pid]={'id':pid,'version':1,'sha256':digest,'content':content,'shown':False}
    store.transact('PROPOSAL_CREATED','proposal:'+digest,change,object_id=pid)
    atomic(store.root/'proposals'/(pid+'.json'),canonical(content));return pid


def authorized(s,spec,root):
    package=s.get('packages',{}).get(spec['stage_id'])
    autonomous=package and package['status']=='ACTIVE' and not package['paused'] and any(t in s.get('autonomous_tasks',[]) for t in package['tasks'])
    if (s['paused'] and not autonomous) or stopped(root):raise Conflict('paused or STOP')
    if s.get('stages',{}).get(spec['stage_id'],{}).get('status')=='REVOKED':raise Conflict('underlying stage revoked')
    check_pins(spec)
    if spec['backend']=='real':
        from .h1 import validate as validate_h1
        validate_h1(spec,root)
    matches=[]
    for a in s['approvals'].values():
        p=s['proposals'][a['proposal_id']];c=p['content']
        if c.get('scope')=='EXPERIMENT' and c.get('spec')==spec:
            if (a['decision']=='APPROVED' and not a.get('revoked') and not p.get('revoked')
                    and sha(c)==a['proposal_sha256']==p['sha256'] and a['proposal_version']==p['version']):matches.append(a)
    if package and spec in package['spec'].get('experiments',[]):
        from .packages import require_package
        require_package(s,s['stages'][spec['stage_id']])
        matches.append({'approval_id':package['approval_id']+':experiment:'+sha(spec)})
    if len(matches)!=1:raise Conflict('no unique exact experiment approval')
    for c in spec['conditions']:
        e=s['evidence'].get(c['evidence_id'],{})
        if not e.get('accepted') or e.get('sha256')!=c['sha256']:raise Conflict('conditional authorization unmet or drifted')
    return matches[0]


def submit(store,spec):
    jid='J-'+sha({'id':spec['id'],'spec':spec})[:16]
    existing=store.view()['jobs'].get(jid)
    if existing:
        if existing['spec']!=spec:raise Conflict('experiment identity collision')
        return reconcile(store,jid)
    validate(spec,store.root)
    snapshot=store.view();authorized(snapshot,spec,store.root)
    from .resources import reserve_task
    resource_record,guarantees,_=reserve_task(store,snapshot.get('stages',{}).get(spec['stage_id'],{}),jid)
    launched=[]
    def reserve(s):
        approval=authorized(s,spec,store.root)
        if any(j.get('spec',{}).get('backend') in {'real','runner_cpu'} and j['status'] in {'START_INTENT','RUNNING','RECONCILE'} for j in s['jobs'].values()):
            raise Conflict('another runner job owns the execution slot')
        if any(j.get('approval_id')==approval['approval_id'] for j in s['jobs'].values()):raise Conflict('experiment approval already consumed')
        s['jobs'][jid]={'id':jid,'stage':spec['stage_id'],'spec':spec,'approval_id':approval['approval_id'],
                        'status':'START_INTENT','reserved_resources':spec['resources'],'used_resources':{},'identity':None,
                        'generation':uuid.uuid4().hex,'launch_phase':'PREPARING'}
        if resource_record:s['jobs'][jid]['task_resources']=resource_record
        if guarantees:s['jobs'][jid]['resource_guarantees']=guarantees
        launched.append(True)
    state=store.transact('EXPERIMENT_RESERVED',jid+':reserve',reserve,object_id=jid)
    if not launched:return reconcile(store,jid)
    d=store.root/'jobs'/jid;d.mkdir(parents=True,exist_ok=True)
    atomic(d/'request.json',canonical({'root':str(store.root),'job_id':jid,'spec':spec,'generation':state['jobs'][jid]['generation'],'task_resources':resource_record}))
    if spec['backend']=='real':
        from .h1 import validate as validate_h1
        atomic(d/'h1-authority.json',canonical(validate_h1(spec,store.root)))
    from .releases import freeze
    frozen=freeze(store.root/'session_releases')
    with (d/'supervisor.log').open('ab') as log:
        proc=subprocess.Popen([sys.executable,'-m','rlflow.experiments','_worker',str(d/'request.json')],cwd=frozen,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    ident=identity(proc.pid)
    store.transact('EXPERIMENT_IDENTITY',jid+':identity',lambda s:s['jobs'][jid].update(identity=ident,status='RUNNING'),object_id=jid)
    try:
        authorized(store.view(),spec,store.root)
        deadline=time.monotonic()+min(60,spec['resources']['wall_seconds'])
        while not (d/'launch-ready.json').exists():
            if proc.poll() is not None or time.monotonic()>deadline or stopped(store.root):
                raise Conflict('experiment readiness timed out; original launch retained for reconciliation')
            time.sleep(.02)
        ready=json.loads((d/'launch-ready.json').read_text())
        binding={'job_id':jid,'identity':ident,'control_release':frozen.name,'generation':state['jobs'][jid]['generation']}
        if ready['binding']!={'session':jid,'generation':binding['generation'],'identity':ident}:raise Conflict('job readiness mismatch')
        store.transact('EXPERIMENT_RELEASE_COMMITTED',jid+':supervisor-release',lambda s:s['jobs'][jid].update(launch_phase='RELEASE_COMMITTED',release_binding=binding),object_id=jid)
        from .startup import record
        record(d,'RELEASE_COMMITTED',binding)
        atomic(d/'supervisor-release.json',canonical(binding))
    except Conflict:
        atomic(d/'cancel',b'authorization changed before supervisor release')
    return store.view()['jobs'][jid]


def status(store,jid):return store.view()['jobs'][jid]


def reconcile(store,jid):
    state=store.view();job=state['jobs'][jid];d=store.root/'jobs'/jid
    if job['status'] in {'SUCCEEDED','FAILED','STOPPED'} and not (job['spec']['backend']=='real' and job.get('reserved_resources')):return job
    receipt=d/'receipt.json'
    if not receipt.exists() and not owns(job.get('identity')) and (d/'lifeguard-request.json').exists():
        from .lifeguard import reclaim
        ready=json.loads((d/'lifeguard-ready.json').read_text()) if (d/'lifeguard-ready.json').exists() else {}
        if not owns(ready.get('identity')):
            with store.lock('recover-'+jid):
                if not receipt.exists():reclaim(json.loads((d/'lifeguard-request.json').read_text()))
    if receipt.exists():
        result=json.loads(receipt.read_text())
        if result.get('job_id')!=jid or result.get('spec_sha256')!=sha(job['spec']):raise Conflict('runner receipt identity mismatch')
        h1_record=None
        if job['spec']['backend']=='real' and (result['released'] or not result.get('definitely_not_released')):
            from .h1 import collect as collect_h1
            h1_record=collect_h1(job['spec'],d,result)
        def finish(s):
            j=s['jobs'][jid];j.update(status=result['status'],receipt=result)
            if result['released']:
                j['used_resources']={'starts':1,'wall_seconds':result['elapsed_seconds'],
                                     'gpu_seconds':None if job['spec']['backend']=='real' else 0,'transitions':None if job['spec']['backend']=='real' else 0}
                # Unknown real resource dimensions remain reserved until raw runner evidence reconciles them.
                j['reserved_resources']={} if job['spec']['backend']=='runner_cpu' else {k:v for k,v in job['spec']['resources'].items() if k in {'gpu_seconds','transitions'}}
                if h1_record:
                    j['h1_evidence']=h1_record
                    j['used_resources']['gpu_seconds']=h1_record['allocation_gpu_seconds']
                    j['used_resources']['transitions']=h1_record['transitions']
                    j['reserved_resources']={k:v for k,v in j['reserved_resources'].items() if j['used_resources'].get(k) is None}
            elif result.get('definitely_not_released'):
                j['reserved_resources']={}
            else:j['status']='RECONCILE'
        store.transact('EXPERIMENT_FINISHED',jid+':finished:'+sha({'receipt':result,'h1':h1_record}),finish,object_id=jid)
    elif not owns(job.get('identity')):
        store.transact('EXPERIMENT_UNCERTAIN',jid+':uncertain',lambda s:s['jobs'][jid].update(status='RECONCILE'),object_id=jid)
    return status(store,jid)


def cancel(store,jid):
    d=store.root/'jobs'/jid;atomic(d/'cancel',b'cancel')
    # Cancellation goes to owned supervisor; its finally path and dispatcher reclaim the held child.
    job=status(store,jid)
    if owns(job.get('identity')):os.kill(job['identity']['pid'],15)
    return reconcile(store,jid)


def collect(store,jid):
    job=reconcile(store,jid);d=store.root/'jobs'/jid
    if job['status'] not in {'SUCCEEDED','FAILED','STOPPED'}:raise Conflict('runner not terminal')
    result={'id':'E-'+jid,'job_id':jid,'scope':job['spec']['backend'],'accepted':True,
            'sha256':sha(job['receipt']),'path':str(d),'exit_fact':job['status'],'scientific_validity':'UNASSESSED',
            'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.iterdir()) if p.is_file()}}
    store.transact('EXPERIMENT_EVIDENCE',jid+':collect',lambda s:s['evidence'].update({result['id']:result}),object_id=jid)
    return result


def worker(request):
    import signal
    r=json.loads(Path(request).read_text());store=Store(r['root']);spec=r['spec'];jid=r['job_id'];d=Path(request).parent
    start=time.monotonic();released=False;allocated_start=None;status_value='FAILED';error=None;code=None;confirmed_no_release=False
    def interrupted(*_):raise RuntimeError('runner cancelled')
    signal.signal(signal.SIGTERM,interrupted)
    guard=None
    task_resources=r.get('task_resources')
    try:
        from .startup import record
        binding={'session':jid,'generation':r.get('generation'),'identity':identity(os.getpid())}
        record(d,'PREPARING',binding)
        from .lifeguard import start as start_guard
        guard=start_guard(d,'experiment',identity(os.getpid()),store.root,spec['resources']['wall_seconds'],jid,spec,resources=task_resources)
        pin=spec['pins']['dispatcher']
        import types
        raw=Path(pin['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise Conflict('dispatcher drift before loading')
        module=types.ModuleType('reviewed_h1_dispatcher')
        exec(compile(raw,pin['path'],'exec'),module.__dict__)
        record(d,'READY',binding)
        release_started=time.monotonic()
        while not (d/'supervisor-release.json').exists():
            if time.monotonic()-release_started>=60 or time.monotonic()-start>=spec['resources']['wall_seconds'] or (d/'cancel').exists() or stopped(store.root):
                raise Conflict('supervisor release absent or cancelled')
            time.sleep(.02)
        release=json.loads((d/'supervisor-release.json').read_text())
        if release['job_id']!=jid or release['identity']!=identity(os.getpid()) or release.get('generation')!=r.get('generation'):raise Conflict('supervisor release identity mismatch')
        from .releases import verify
        if verify(Path(__file__).resolve().parents[1])['id']!=release['control_release']:raise Conflict('runner control release drift')
        authorized(store.view(),spec,store.root)
        if (d/'cancel').exists():raise Conflict('cancelled before launch')
        committed=store.get('jobs',jid)
        if committed.get('release_binding')!=release:raise Conflict('job release lacks committed authority')
        def gate():
            nonlocal released,allocated_start
            authorized(store.view(),spec,store.root)
            if (d/'cancel').exists():raise Conflict('cancelled before release')
            held=json.loads((d/'held-child.json').read_text())['held_child']['pid']
            atomic(d/'process-identity.json',canonical(identity(held)))
            if task_resources:
                from .resources import verify_group
                group=verify_group(task_resources);(group/'cgroup.procs').write_text(str(held))
                verify_group(task_resources,identity(held))
            allocated_start=time.monotonic()
            intent={'job_id':jid,'spec_sha256':sha(spec),'allocated_monotonic':allocated_start,'generation':r.get('generation'),'identity':identity(held),'authorization':sha(spec['pins']['authorization']),'resources':spec['resources'],'task_resources':task_resources}
            store.transact('EXPERIMENT_BUSINESS_RELEASE_COMMITTED',jid+':business-release',lambda s:s['jobs'][jid].update(business_release=intent),object_id=jid)
            atomic(d/'release-intent.json',canonical(intent))
            released=True
        # CPU substitute executes through the same reviewed dispatcher but its
        # command is itself constrained by the existing CPU sandbox.
        argv=spec['argv']
        if spec['backend']=='runner_cpu':
            import shlex
            from . import isolation
            cfg={'read':[spec['cwd'], spec['pins']['product']['path'], spec['pins']['workload']['path']],'write':[spec['cwd']],'execute':[],
                 'memory_bytes':2*1024**3,'command':shlex.join(argv),'timeout':spec['resources']['wall_seconds'],
                 'guard_directory':str(Path(task_resources['disk']['raw'])/'command-process') if task_resources and task_resources.get('disk') else str(d/'command-process'),'control_root':str(store.root)}
            argv=[sys.executable,'-I',str(Path(isolation.__file__).resolve()),'_supervised',json.dumps(cfg)]
        environment={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','CUDA_VISIBLE_DEVICES':''}
        if spec['backend']=='real':
            from .h1 import environment as h1_environment
            environment=h1_environment(spec)
        redirected=[]
        if task_resources:
            wrapper="import os,sys,json;sys.path.insert(0,sys.argv[1]);from rlflow.resources import verify_group,confine_writes;from rlflow.jobs import identity;r=json.loads(sys.argv[2]);verify_group(r,identity(os.getpid()));confine_writes(r['disk']['root']) if r.get('disk') else None;os.execv(sys.argv[3],sys.argv[3:])"
            argv=[sys.executable,'-I','-c',wrapper,str(Path(__file__).resolve().parents[1]),canonical(task_resources).decode(),*argv]
            if task_resources.get('disk'):
                raw=Path(task_resources['disk']['raw'])
                if spec['backend']=='runner_cpu':(d/'command-process').symlink_to(raw/'command-process')
                temporary=raw/'tmp';temporary.mkdir();environment['TMPDIR']=str(temporary)
                for number,name in ((1,'business-stdout.log'),(2,'business-stderr.log')):
                    saved=os.dup(number);output=os.open(raw/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    os.dup2(output,number);os.close(output);redirected.append((number,saved))
        try:
            code=module.dispatch_held(argv,cwd=Path(spec['cwd']),identity_path=d/'held-child.json',
                     coordination_root=store.root,completion_timeout_s=max(.01,spec['resources']['wall_seconds']-(time.monotonic()-start)),
                     environment=environment,before_release=gate)
        finally:
            for number,saved in redirected:os.dup2(saved,number);os.close(saved)

        status_value='SUCCEEDED' if code==0 else 'FAILED'
    except BaseException as exc:
        error=f'{type(exc).__name__}: {exc}'
        confirmed_no_release=not released
        status_value='STOPPED' if stopped(store.root) or (d/'cancel').exists() else 'FAILED'
    finally:
        if task_resources:
            from .resources import verify_group,stats
            group=verify_group(task_resources);(group/'cgroup.kill').write_text('1')
            atomic(d/'resource-usage.json',canonical(stats(group)))
        atomic(d/'receipt.json',canonical({'job_id':jid,'spec_sha256':sha(spec),'status':status_value,
              'exit_code':code,'error':error,'elapsed_seconds':time.monotonic()-start,'released':released,
              'allocated_seconds':time.monotonic()-allocated_start if allocated_start is not None else None,
              'definitely_not_released':confirmed_no_release}))
        atomic(d/'lifeguard-done',b'done')
        if guard is not None:guard.wait(timeout=3)


if __name__=='__main__':worker(sys.argv[2])
