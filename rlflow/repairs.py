"""Bounded control-plane repair registration. Never grants policy or runtime writes."""
from .store import Conflict,sha

PROTECTED={'accounting.py','authorizations.py','policy.py','isolation.py','packages.py','contracts.py','store.py','releases.py'}


def register_in(state, session, failure):
    code=failure.get('code') or failure.get('kind','UNKNOWN')
    rid='R-'+sha({'stage':session['stage_id'],'cause':code})[:16]
    registry=state.setdefault('repairs',{})
    if rid not in registry:
        registry[rid]={'id':rid,'stage_id':session['stage_id'],'source_session':session['id'],
            'failure':failure,'status':'NEEDS_ISOLATED_CANDIDATE','budget_ref':session['stage_id'],
            'allowed_modules':['rlflow/worker.py','rlflow/failures.py'],
            'protected_modules':sorted(PROTECTED),'roles':['Engineer','Evaluator'],
            'resume_requires':['independent passing evaluation','new frozen control release','exact failure evidence']}
    return rid


def verify_repair(store,rid,engineer_session,evaluator_session):
    def change(s):
        repair=s['repairs'][rid]
        engineer=s['sessions'][engineer_session];evaluator=s['sessions'][evaluator_session]
        if engineer['role']!='Engineer' or evaluator['role']!='Evaluator' or any(x['status']!='ACCEPTED' for x in (engineer,evaluator)):
            raise Conflict('repair needs accepted Engineer and independent Evaluator')
        task=s['tasks'][evaluator['task_id']]
        if engineer['task_id']!=task['id'] or not task['completion']['cpu']:
            raise Conflict('repair roles must review the same passing candidate')
        if task.get('repair_id')!=rid:raise Conflict('evaluation does not bind this infrastructure repair')
        baseline=task['baseline']['files'];current=task['accepted_candidate']['files']
        changes={p for p in set(baseline)|set(current) if baseline.get(p)!=current.get(p)}
        if not changes or not changes<=set(repair['allowed_modules']):raise Conflict('repair changes protected authority or has no actual fix')
        repair.update(status='VERIFIED_AWAITING_RELEASE',engineer_session=engineer_session,evaluator_session=evaluator_session,candidate=task['accepted_candidate'])
    return store.transact('INFRA_REPAIR_VERIFIED','repair:'+rid+':'+evaluator_session,change,object_id=rid)


def resource_stage(state, sid):
    stage=state['stages'][sid]
    return state['stages'][stage['funding_stage_id']] if stage.get('funding_stage_id') else stage


def validate_stage(state,stage):
    from .policy import require_stage
    repair=state.get('repairs',{}).get(stage.get('repair_id'),{})
    parent=require_stage(state,stage['funding_stage_id'])
    if not parent.get('package_id') or repair.get('stage_id')!=parent['id'] or repair.get('repo')!=stage['repo']:
        raise Conflict('control repair is not bound to an approved package')
    if stage['module_roots']!=repair['allowed_modules'] or stage['authorization']!=parent['authorization'] or stage['categories']!=['ENGINEERING_FIX']:
        raise Conflict('repair scope/authority drift')


def prepare(store,rid):
    """Create a bounded Engineer/Evaluator task sharing its package's resource pool."""
    from pathlib import Path
    import subprocess
    from .policy import new_stage,available
    from .releases import files
    from .store import atomic
    s=store.replay();repair=s['repairs'][rid];parent=s['stages'][repair['stage_id']]
    if repair['status']!='NEEDS_ISOLATED_CANDIDATE' or not parent.get('package_id') or available(parent)['role_calls']<2:
        return False
    repo=store.root/'workspaces'/('control-repair-'+rid)
    if not repo.exists():
        repo.mkdir(parents=True)
        for name,path in files().items():atomic(repo/name,path.read_bytes())
        subprocess.run(['git','init','-q',str(repo)],check=True)
        subprocess.run(['git','-C',str(repo),'add','.'],check=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=rlflow','-c','user.email=rlflow@local','commit','-qm','frozen control repair baseline'],check=True)
    stage_id='repair-'+rid;task_id='T-'+sha({'repair':rid})[:16]
    limits={**parent['budget'],'wall_seconds':min(86400,parent['budget']['wall_seconds'])}
    protected=['.git']+[p for p in files() if p not in repair['allowed_modules']]
    stage=new_stage(stage_id,repo,'Repair only the recorded control infrastructure failure; preserve all authority and isolation rules',limits,parent['authorization'],module_roots=repair['allowed_modules'],protected_paths=protected)
    stage.update(repair_id=rid,funding_stage_id=parent['id'],per_call_seconds=parent['per_call_seconds'],command_seconds=parent.get('command_seconds',120))
    def create(state):
        r=state['repairs'][rid]
        if r['status']!='NEEDS_ISOLATED_CANDIDATE':raise Conflict('repair already prepared')
        r.update(repo=str(repo),status='IMPLEMENTING',task_id=task_id)
        state['stages'][stage_id]=stage
        state['tasks'][task_id]={'id':task_id,'version':1,'stage_id':stage_id,'cycle_id':task_id,
             'text':stage['scope']+'\nFailure evidence: '+str(r['failure']), 'repo':str(repo),'baseline':stage['baseline'],
             'status':'QUEUED','next_role':'Engineer','repair_rounds':0,'diagnostic_after_rounds':3,
             'results':[],'findings':[],'consulted':[],'repair_id':rid,
             'completion':dict.fromkeys(('implementation','cpu','real_run','behavior','formal'),False)}
        state.setdefault('autonomous_tasks',[]).append(task_id)
    store.transact('INFRA_REPAIR_PREPARED','repair:'+rid+':prepare',create,object_id=rid,expected=s['version'])
    return True


def promote(store,rid):
    """Verify the fixed regression suite, then publish only at an idle boundary."""
    from pathlib import Path
    import os,subprocess,sys,time
    from .releases import freeze,verify
    from .store import atomic,canonical
    state=store.replay();repair=state['repairs'][rid]
    if repair['status']!='VERIFIED_AWAITING_RELEASE':return False
    if any(x['status'] in {'START_INTENT','RUNNING','RECONCILE'} for x in state['sessions'].values()):return False
    if any(j['status'] in {'START_INTENT','RUNNING','RECONCILE'} for j in state['jobs'].values()):return False
    target=freeze(store.root/'releases',root=Path(repair['repo']));manifest=verify(target)
    out=store.root/'repair_validation'/rid;out.mkdir(parents=True,exist_ok=True)
    from .validation_job import poll
    argv=[sys.executable,'-m','pytest','-q','tests','--basetemp',str(out/'pytest')]
    validation=poll(out,argv,target,manifest['id'],store.root)
    if validation is None:return False
    if validation['exit_code']!=0:
        store.transact('INFRA_REPAIR_REGRESSION_FAILED','repair:'+rid+':regression-failed',lambda s:s['repairs'][rid].update(status='REGRESSION_FAILED',validation=validation),object_id=rid)
        return False
    verify(target)
    def publish(s):
        if any(x['status'] in {'START_INTENT','RUNNING','RECONCILE'} for x in s['sessions'].values()) or any(j['status'] in {'START_INTENT','RUNNING','RECONCILE'} for j in s['jobs'].values()):
            raise Conflict('repair release lost idle boundary')
        r=s['repairs'][rid]
        if r['status']!='VERIFIED_AWAITING_RELEASE':raise Conflict('repair state changed')
        r.update(status='RELEASED',validation=validation,release_id=manifest['id'])
        s.setdefault('releases',{})[manifest['id']]={'path':str(target),'validation':validation,'repair_id':rid,'published_sequence':s['version']+1,'unique_dispatcher':'rlflow.engine'}
        source=s['sessions'][r['source_session']];task=s['tasks'][source['task_id']]
        if task['status'] not in {'INFRASTRUCTURE_ERROR','ROLE_ERROR','QUEUED'} or task['version']!=source['task_version']+1:
            raise Conflict('business task changed after infrastructure failure')
        task.update(status='QUEUED',version=task['version']+1)
        task.pop('last_failure',None);task.pop('last_error',None)
        package=s['packages'][r['stage_id']]
        if not package['paused'] and package['status']=='ACTIVE' and task['id'] not in s.setdefault('autonomous_tasks',[]):
            s['autonomous_tasks'].append(task['id'])
    with store.lock('dispatch-release'):
        store.transact('INFRA_REPAIR_RELEASED','repair:'+rid+':release',publish,object_id=rid)
        atomic(store.root/'runtime/current-release.json',canonical({'id':manifest['id'],'path':str(target)}))
    return True
