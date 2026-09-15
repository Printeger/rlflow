import json,os,signal,subprocess,sys,time
from pathlib import Path
import pytest
from rlflow import engine,experiments,packages
from rlflow.jobs import identity,owns
from rlflow.store import Store,atomic,canonical
from test_engine import harness,result_for
from test_packages import approved,specification
from test_experiments_v2 import spec,approve

DRIVER=Path(__file__).with_name('recovery_driver.py')


def until(predicate,seconds=15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.03)
    pytest.fail('bounded process condition not reached')


def real_workers(h,monkeypatch):
    # Replace the actual business CLI only; worker, lifeguard and held wrapper are real processes.
    saved=subprocess.Popen
    # harness wrapped Popen; restore the original implementation underneath its closure.
    original=next(c.cell_contents for c in saved.__closure__ if c.cell_contents is not None and isinstance(c.cell_contents,type)) if saved.__closure__ else saved
    children=[]
    def popen(argv,*args,**kw):
        if 'rlflow.worker' in argv:
            argv=[sys.executable,str(DRIVER),'worker',argv[-1]]
        p=original(argv,*args,**kw);children.append(p);return p
    monkeypatch.setattr(engine.subprocess,'Popen',popen)
    return children


def wait_role(h,sid):
    se=h.store.replay()['sessions'][sid];d=Path(se['directory'])
    until(lambda:(d/'fixture-cli-ready').exists())
    return se,d


def finish_role(h,sid):
    s=h.store.replay();se=s['sessions'][sid];h.task_id=se['task_id'];r=result_for(h,sid)
    if se['role']=='PI':r['payload']['task_interpretation'].update(stage_id='PKG',budget=s['stages']['PKG']['budget'],acceptance_criteria=[c['id'] for c in s['tasks'][h.task_id]['criteria']])
    if se['role']=='Engineer':
        from rlflow.policy import candidate
        baseline=s['tasks'][h.task_id]['baseline']['files'];current=candidate(h.repo)['files']
        r['payload']['changes']=[{'path':p,'description':'preserved partial repair','suggested_category':'ENGINEERING_FIX'} for p in sorted(set(baseline)|set(current)) if baseline.get(p)!=current.get(p)]
    if se['role']=='Evaluator':r['payload']['evidence_coverage']=[c['id'] for c in s['tasks'][h.task_id]['criteria']]
    atomic(Path(se['directory'])/'fixture-result.json',canonical(r))
    until(lambda:(Path(se['directory'])/'receipt.json').exists())
    return engine.reconcile(h.store)


@pytest.mark.parametrize('used',[True,False])
def test_sigkill_worker_reclaims_descendants_and_settles_without_blind_retry(harness,monkeypatch,used):
    h=harness;p=specification(h);p['tasks']=p['tasks'][:1];p['per_call_seconds']=20;approved(h,p);children=real_workers(h,monkeypatch)
    if not used:(h.store.root/'fixture-no-usage').write_text('unknown usage')
    sid=engine.dispatch_one(h.store);se,d=wait_role(h,sid)
    child=identity(json.loads((d/'fixture-descendant.json').read_text())['pid']);cli=json.loads((d/'codex-identity.json').read_text())
    os.kill(se['identity']['pid'],signal.SIGKILL)
    until(lambda:(d/'receipt.json').exists());until(lambda:not owns(child) and not owns(cli))
    h.store=Store(h.store.root);s=engine.reconcile(h.store);stage=s['stages']['PKG']
    assert len((h.store.root/'cli-starts.log').read_text().splitlines())==1
    if used:
        assert stage['used_calls']==1 and stage['reserved_calls']==0
        packages.pause(h.store,'PKG',True);assert engine.dispatch_one(h.store) is None
        packages.pause(h.store,'PKG',False)
        for _ in range(3):
            next_sid=engine.dispatch_one(h.store);assert next_sid is not None and next_sid!=sid
            wait_role(h,next_sid);s=finish_role(h,next_sid)
        assert s['goals']['PKG']['status']=='DONE' and s['stages']['PKG']['used_calls']==4
        assert engine.dispatch_one(h.store) is None
    else:
        assert stage['reserved_calls']==1 and stage['used_calls']==0
        assert engine.dispatch_one(h.store) is None
    for p in children:
        if p.poll() is None:p.wait(timeout=5)


def test_sigkill_job_supervisor_reclaims_child_never_resubmits(harness):
    h=harness;v=spec(h);v['resources']['wall_seconds']=20
    script=h.repo/'probe.py';script.write_text('from pathlib import Path\nimport time\np=Path("starts.txt");p.write_text(str(int(p.read_text())+1) if p.exists() else "1")\ntime.sleep(60)\n')
    v['pins']['product']=v['pins']['workload']=v['pins']['runtime']=v['pins']['authorization']=experiments.file_pin(script)
    approve(h,v);j=experiments.submit(h.store,v);d=h.store.root/'jobs'/j['id']
    until(lambda:(h.repo/'starts.txt').exists());child=json.loads((d/'process-identity.json').read_text())
    nested=json.loads((d/'command-process/command-child-identity.json').read_text())
    os.kill(j['identity']['pid'],signal.SIGKILL)
    until(lambda:(d/'receipt.json').exists());until(lambda:not owns(child) and not owns(nested))
    h.store=Store(h.store.root);job=experiments.reconcile(h.store,j['id'])
    assert job['status']=='FAILED' and job['used_resources']['starts']==1
    assert experiments.submit(h.store,v)['id']==j['id'] and (h.repo/'starts.txt').read_text()=='1'


def test_actual_dispatcher_restart_preserves_running_worker_and_pause(harness,monkeypatch):
    h=harness;v=specification(h);v['tasks']=v['tasks'][:1];v['per_call_seconds']=20;approved(h,v);children=real_workers(h,monkeypatch)
    sid=engine.dispatch_one(h.store);se,d=wait_role(h,sid);packages.pause(h.store,'PKG',True)
    daemon=None
    try:
        engine.ensure_daemon(h.store)
        daemon=until(lambda:json.loads((h.store.root/'runtime/daemon.json').read_text()) if (h.store.root/'runtime/daemon.json').exists() else None)
        assert owns(daemon);os.kill(daemon['pid'],signal.SIGKILL);until(lambda:not owns(daemon))
        old=daemon
        daemon=engine.restart_daemon(h.store)
        until(lambda:owns(daemon) and json.loads((h.store.root/'runtime/daemon.json').read_text())['pid']==daemon['pid'])
        assert daemon['pid']!=old['pid'] and owns(se['identity'])
        s=finish_role(h,sid)
        assert s['packages']['PKG']['paused'] and s['stages']['PKG']['used_calls']==1
        time.sleep(.15);assert len((h.store.root/'cli-starts.log').read_text().splitlines())==1
    finally:
        if daemon and owns(daemon):os.kill(daemon['pid'],signal.SIGTERM);until(lambda:not owns(daemon))
    packages.pause(h.store,'PKG',False)
    for _ in range(2):
        next_sid=engine.dispatch_one(h.store);wait_role(h,next_sid);s=finish_role(h,next_sid)
    assert s['goals']['PKG']['status']=='DONE' and s['stages']['PKG']['used_calls']==3
    for p in children:
        if p.poll() is None:p.wait(timeout=5)


def test_stop_reclaims_running_worker_and_requires_clear_stop_before_continuation(harness,monkeypatch):
    h=harness;v=specification(h);v['tasks']=v['tasks'][:1];v['per_call_seconds']=20;approved(h,v);children=real_workers(h,monkeypatch)
    sid=engine.dispatch_one(h.store);se,d=wait_role(h,sid);cli=json.loads((d/'codex-identity.json').read_text())
    stop=h.store.root/'STOP';stop.write_text('operator STOP')
    until(lambda:(d/'receipt.json').exists());until(lambda:not owns(cli));s=engine.reconcile(h.store)
    assert s['stages']['PKG']['used_calls']==1 and engine.dispatch_one(h.store) is None
    packages.pause(h.store,'PKG',True);stop.unlink();assert engine.dispatch_one(h.store) is None
    packages.pause(h.store,'PKG',False)
    for _ in range(3):
        next_sid=engine.dispatch_one(h.store);wait_role(h,next_sid);s=finish_role(h,next_sid)
    assert s['goals']['PKG']['status']=='DONE' and s['stages']['PKG']['used_calls']==4
    for p in children:
        if p.poll() is None:p.wait(timeout=5)


def test_dispatcher_recovers_after_both_worker_and_lifeguard_die(harness,monkeypatch):
    h=harness;v=specification(h);v['tasks']=v['tasks'][:1];v['per_call_seconds']=20;approved(h,v);children=real_workers(h,monkeypatch)
    sid=engine.dispatch_one(h.store);se,d=wait_role(h,sid)
    guard=json.loads((d/'lifeguard-ready.json').read_text())['identity'];cli=json.loads((d/'codex-identity.json').read_text())
    os.kill(guard['pid'],signal.SIGKILL);until(lambda:not owns(guard));os.kill(se['identity']['pid'],signal.SIGKILL);until(lambda:not owns(se['identity']))
    assert owns(cli)
    s=engine.reconcile(Store(h.store.root));until(lambda:not owns(cli))
    assert s['stages']['PKG']['used_calls']==1 and s['stages']['PKG']['reserved_calls']==0
    assert s['tasks'][se['task_id']]['status']=='QUEUED'
    for p in children:
        if p.poll() is None:p.wait(timeout=5)


def test_partial_engineer_change_and_completed_command_survive_worker_sigkill(harness,monkeypatch):
    from rlflow import isolation,evidence
    h=harness;v=specification(h);v['tasks']=v['tasks'][:1];v['per_call_seconds']=20;approved(h,v);children=real_workers(h,monkeypatch)
    sid=engine.dispatch_one(h.store);wait_role(h,sid);finish_role(h,sid)
    sid=engine.dispatch_one(h.store);se,d=wait_role(h,sid);assert se['role']=='Engineer'
    c={'candidate':str(h.repo),'scratch':str(d/'scratch'),'role':'Engineer','audit':str(d/'result.json.commands.jsonl'),'command_seconds':20}
    command="printf 'def parse(value):\\n    if type(value) is not int or value < 0: raise ValueError(\"invalid\")\\n    return value\\n' > "+str(h.repo/'parser.py')
    done=isolation.persistent_cpu_exec(c,{'command_id':'partial-fix','command':command,'timeout':5});assert done['exit_code']==0
    changed=(h.repo/'parser.py').read_bytes();os.kill(se['identity']['pid'],signal.SIGKILL)
    until(lambda:(d/'receipt.json').exists());s=engine.reconcile(Store(h.store.root))
    assert s['tasks'][se['task_id']]['status']=='QUEUED'
    recovered=engine.dispatch_one(h.store);assert recovered;next_se,next_dir=wait_role(h,recovered)
    material=evidence.recovery_material(h.store,h.store.replay(),h.store.replay()['tasks'][se['task_id']],next_dir)
    record=json.loads(Path(material['read_only_path']).read_text())
    assert record['commands'][0]['status']=='COMPLETED' and record['commands'][0]['result']==done
    assert (h.repo/'parser.py').read_bytes()==changed
    finish_role(h,recovered);sid=engine.dispatch_one(h.store);wait_role(h,sid);s=finish_role(h,sid)
    assert s['goals']['PKG']['status']=='DONE' and s['stages']['PKG']['used_calls']==4
    for p in children:
        if p.poll() is None:p.wait(timeout=5)


def test_pause_at_final_model_gate_releases_unused_reservation(harness,monkeypatch):
    h=harness;v=specification(h);v['tasks']=v['tasks'][:1];v['per_call_seconds']=20;approved(h,v);children=real_workers(h,monkeypatch)
    marker=h.store.root/'fixture-pause-before-model';marker.write_text('pause during CLI preparation')
    sid=engine.dispatch_one(h.store);se=h.store.replay()['sessions'][sid];d=Path(se['directory'])
    until(lambda:(d/'receipt.json').exists());s=engine.reconcile(h.store)
    assert (d/'model-intent.json').exists() and not (d/'model-release.json').exists()
    assert not (h.store.root/'cli-starts.log').exists()
    assert s['stages']['PKG']['used_calls']==s['stages']['PKG']['reserved_calls']==0
    assert s['sessions'][sid]['model_accounting']=='NOT_STARTED' and engine.dispatch_one(h.store) is None
    marker.unlink();packages.pause(h.store,'PKG',False)
    for _ in range(3):
        next_sid=engine.dispatch_one(h.store);assert next_sid;wait_role(h,next_sid);s=finish_role(h,next_sid)
    assert s['goals']['PKG']['status']=='DONE' and s['stages']['PKG']['used_calls']==3
    for p in children:
        if p.poll() is None:p.wait(timeout=5)
