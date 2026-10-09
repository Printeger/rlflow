"""Actual approved CPU Unit through authenticated HTTP; no paid/native model."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import subprocess
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_cpu_unit_control import CpuUnitControlService
from rlflow.hybrid_cpu_unit_stop import SECTION, EVENT
from rlflow.hybrid_host_execution import HostExecutionService
from rlflow.store import Conflict
from rlflow.web_api import Project, create_app
from tests.test_hybrid_cpu_execution_unit import unit
from tests.test_hybrid_cpu_trial_runtime import trial_runtime
from tests.test_execution_adapter import setup as native_setup

ORIGIN='http://127.0.0.1:8765'
PHRASE='Working plan isolated synthetic fixture passphrase'

def setup(context,*,origin=ORIGIN):
    owner,lease,assessment,execution=unit(context)
    host=HostExecutionService(owner.pool);host.bind_unit(execution)
    auth=owner.store._hybrid_auth_owner
    token,access=auth.login('fixture_human',PHRASE)
    service=CpuUnitControlService(host,lease,auth,origin=origin)
    project=service.project_id
    app=create_app([Project(project,str(owner.store.root),'fixture')],auth,origin=origin,
                   cpu_unit_services={project:service})
    path=f'/api/v1/projects/{project}/cpu-unit'
    headers={'Origin':origin,'X-CSRF-Token':access.csrf,'Idempotency-Key':'run'}
    body={'action':'START_FIXED_CPU','task_id':service.task_id,'expected_state_version':owner.store.version()}
    return owner,execution,service,app,token,headers,path,body

def execute(service,body,token,headers,key='run'):
    return service.execute(body,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key=key)

def stop(body):return {'action':'CANCEL_FIXED_CPU_TRIAL','task_id':body['task_id']}

def test_actual_HTTP384_machine_PENDING_REVIEW_once_and_STOP_after_safe_cleanup(trial_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    spawn=subprocess.Popen;launches=[]
    def counted(*args,**kwargs):launches.append(args[0]);return spawn(*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',counted)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        assert client.get(path).json()['task']['kind']=='LOCAL_CPU_NUMERICAL_TRIAL'
        response=client.post(path+'/commands',headers=headers,json=body)
        assert response.status_code==202,response.text
        receipt=response.json();assert receipt['recorded_phase']=='HANDOFF_UNKNOWN'
        assert execution._last['status']=='EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
        assert execution._last['fact']['machine_verification']['derived']['inside_counts']==[96,101,104]
        assert owner.pool.snapshot()['occupied']==0 and len(launches)==1
        version=owner.store.version()
        duplicate=client.post(path+'/commands',headers=headers,json=body)
        assert duplicate.status_code==202 and duplicate.json()['duplicate']
        assert owner.store.version()==version and len(launches)==1
        assert client.post(path+'/commands',headers=headers,json=stop(body)).status_code==409
        assert not execution._cancelled.is_set()  # Conflicting key must not latch.
        stopped=client.post(path+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(body))
        assert stopped.status_code==202,stopped.text
        assert stopped.json()['recorded_phase']=='STOP_INTENT_ACCEPTED'
        assert owner.pool.snapshot()['occupied']==0 and owner.store.version()==version+1
        before=owner.store.version()
        assert client.post(path+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(body)).json()['duplicate']
        assert owner.store.version()==before and len(launches)==1
        assert client.get(path+'/commands/'+receipt['command_id']).status_code==200
        profile=client.get(path).json();assert not profile['goal_completed'] and profile['independent_review_status']=='NOT_PERFORMED'
        assert profile['task']['resource_release_status']=='NOT_OBSERVED'
        owner.shutdown()
        assert client.get(path).json()['original_owner_available'] is False
        assert client.get(path+'/commands/'+receipt['command_id']).status_code==200
    state=owner.store.audit();owner.store.snapshot();assert owner.store.recover()==state

def test_STOP_latch_precedes_actual_Pool_wait_and_accepted_cleanup_outlives_session(trial_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    accepted=threading.Event();accept=service._accept_stop
    clock=[service.auth.clock()];monkeypatch.setattr(service.auth,'clock',lambda:clock[0])
    def expired(*args):
        result=accept(*args);clock[0]+=1000;accepted.set();return result
    monkeypatch.setattr(service,'_accept_stop',expired)
    with ThreadPoolExecutor(max_workers=1) as workers:
        with owner.pool._lock:
            operation=service.prepare(stop(body),token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='stop')
            assert execution._cancelled.is_set()
            future=workers.submit(service.execute_prepared,operation)
            assert accepted.wait(5) and not future.done()
        receipt=future.result(timeout=10)
    assert receipt['status']=='ACCEPTED' and owner.pool.snapshot()['occupied']==0
    assert not owner._issued(execution.lease)['spawn_entered']
    assert service.receipt(receipt['command_id'])['accepted_state_version']==receipt['accepted_state_version']

@pytest.mark.parametrize('boundary',['G','DECISION'])
def test_actual_last_Human_auth_blocks_G_or_machine_COMMIT(trial_runtime,monkeypatch,boundary):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    clock=[service.auth.clock()];monkeypatch.setattr(service.auth,'clock',lambda:clock[0]);seen=[]
    if boundary=='G':
        gate=owner._check_release_gate
        def revoke(attempt):clock[0]+=1000;seen.append(True);return gate(attempt)
        monkeypatch.setattr(owner,'_check_release_gate',revoke)
    else:
        commit=owner.store._commit
        def revoke(db,event,key,payload,*args,**kwargs):
            if any(s=='hybrid_cpu_trial_assessments' and k and 'machine_verification' in v for s,k,v in payload['put']):
                clock[0]+=1000;seen.append(True)
            return commit(db,event,key,payload,*args,**kwargs)
        monkeypatch.setattr(owner.store,'_commit',revoke)
    receipt=execute(service,body,token,headers)
    assert seen and receipt['status']=='ACCEPTED'
    attempt=owner._issued(execution.lease)
    assert not any('machine_verification' in v for k,v in owner.store.objects('hybrid_cpu_trial_assessments') if k)
    if boundary=='G':assert not attempt['release_entered']
    assert owner.pool.snapshot()['occupied']==0

def test_protected_STOP_source_and_failed_accept_no202_retry_same_body(trial_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    commit=owner.store._commit
    with monkeypatch.context() as patch:
        def rollback(db,event,*args,**kwargs):
            result=commit(db,event,*args,**kwargs)
            if event==EVENT:raise OSError('confirmed before COMMIT')
            return result
        patch.setattr(owner.store,'_commit',rollback)
        with pytest.raises(OSError):execute(service,stop(body),token,headers,'stop')
    assert execution._cancelled.is_set() and not owner.store.objects(SECTION)
    receipt=execute(service,stop(body),token,headers,'stop')
    assert receipt['status']=='ACCEPTED'
    with pytest.raises(PermissionError):owner.store.transact(EVENT,receipt['command_id'],lambda state:None)
    with pytest.raises(PermissionError):owner.store.transact_objects(EVENT,receipt['command_id'],[],lambda state:None)
    with sqlite3.connect(owner.store.db) as db:
        original=db.execute('SELECT producer FROM events WHERE idempotency_key=?',(receipt['command_id'],)).fetchone()[0]
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET producer=? WHERE idempotency_key=?',('foreign',receipt['command_id']));db.commit()
        db.execute(trigger);db.commit()  # Isolated corruption fixture restores the actual append-only guard.
    try:
        with pytest.raises(Conflict):service.receipt(receipt['command_id'])
        with pytest.raises(Conflict):owner.store.audit()
        from rlflow.snapshot_maintenance import maintain
        with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(owner.store.version(),));db.commit()
        assert not maintain(owner.store,seconds=20)
    finally:
        with sqlite3.connect(owner.store.db) as db:
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET producer=? WHERE idempotency_key=?',(original,receipt['command_id']));db.commit()
            db.execute(trigger);db.commit()
    assert owner.store.audit()['version']==owner.store.version()
    assert maintain(owner.store,seconds=20)

def test_actual_HTTP_STOP_during_original_spawn_before_G_separate_channel(trial_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    entered=threading.Event();register=owner._register_release
    def wait_for_stop(attempt):
        entered.set();assert execution._cancelled.wait(2)
        return register(attempt)
    monkeypatch.setattr(owner,'_register_release',wait_for_stop)
    with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as workers:
        client.cookies.set('rlflow_session',token)
        future=workers.submit(client.post,path+'/commands',headers=headers,json=body)
        assert entered.wait(8)
        stopped=client.post(path+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(body))
        assert stopped.status_code==202,stopped.text
        assert future.result(timeout=10).status_code==202
    attempt=owner._issued(execution.lease);source=owner.sources._issued(attempt['source'])
    assert not attempt['release_entered'] and source['producer'].poll() is not None
    assert all(fd is None for fd in source['fds'].values()) and owner.pool.snapshot()['occupied']==0
    assert not owner.store.objects('hybrid_cpu_trial_assessments')

def test_STOP_full_intent_capacity_still_latches_after_auth_not_conflicting_key(trial_runtime):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    for i in range(32):
        operation=service.prepare(body,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key=f'run_{i}')
        service.discard_unsubmitted(operation)
    assert not execution._cancelled.is_set()
    with pytest.raises(Conflict,match='idempotency'):execute(service,stop(body),token,headers,'run_0')
    assert not execution._cancelled.is_set()
    with pytest.raises(Conflict,match='capacity'):execute(service,stop(body),token,headers,'new_stop')
    assert execution._cancelled.is_set()
    execution.cancel();assert owner.pool.snapshot()['occupied']==0

def test_fork_GET_and_POST_reject_before_inherited_Auth_and_executor_locks(trial_runtime):
    import asyncio
    from starlette.requests import Request
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    routes={r.path:r for r in app.routes if getattr(r,'path','').endswith(('/cpu-unit','/cpu-unit/commands'))}
    with service.auth._lock,app.state.cpu_unit_start_pool.lock:
        pid=os.fork()
        if pid==0:
            try:
                import signal
                signal.alarm(3)
                for suffix,method in [('', 'GET'),('/commands','POST')]:
                    request=Request({'type':'http','method':method,'path':path+suffix,'headers':[], 'query_string':b''})
                    route=routes['/api/v1/projects/{project_id}/cpu-unit'+suffix]
                    result=asyncio.run(route.endpoint(request,service.project_id))
                    assert result.status_code==403
                os._exit(0)
            except BaseException:os._exit(71)
        _,status=os.waitpid(pid,0)
    assert os.waitstatus_to_exitcode(status)==0
    assert not execution._cancelled.is_set() and not owner._issued(execution.lease)['spawn_entered']

def test_auth_scope_copy_and_direct_SDK_bypass_fail_before_dispatch(trial_runtime):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    with pytest.raises(PermissionError):execution.run(trial_runtime[2],idempotency_key='bypass',expected_state_version=owner.store.version())
    with pytest.raises(PermissionError):service.host.run(replace(execution.lease),trial_runtime[2],idempotency_key='copy',expected_state_version=owner.store.version())
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.post(path+'/commands',headers=headers,json=stop(body)).status_code==401
        client.cookies.set('rlflow_session',token)
        for h in ({**headers,'Origin':'https://foreign.invalid'},{**headers,'X-CSRF-Token':'wrong'}):
            assert client.post(path+'/commands',headers=h,json=stop(body)).status_code==403
        assert client.post(path+'/commands',headers=headers,json={**stop(body),'task_id':'foreign'}).status_code==403
        assert client.post(path+'/commands',headers=headers,json={**stop(body),'expected_state_version':0}).status_code==400
        for payload in (None,False,0,'bad',[]):
            response=client.post(path+'/commands',headers={**headers,'Content-Type':'application/json'},content=json.dumps(payload))
            assert response.status_code==400,response.text
    assert not execution._cancelled.is_set() and not owner._issued(execution.lease)['spawn_entered']

def test_source_schema_corruption_GET503_but_invalid_input400(trial_runtime):
    owner,execution,service,app,token,headers,path,body=setup(trial_runtime)
    receipt=execute(service,stop(body),token,headers,'stop')
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        assert client.get(path+'/commands/bad!').status_code==400
        with owner.store.connect() as db:
            raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(SECTION,receipt['command_id'])).fetchone()[0]
            value=json.loads(raw);value['request']['task_id']=False
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(json.dumps(value),SECTION,receipt['command_id']));db.commit()
        try:
            response=client.get(path+'/commands/'+receipt['command_id'])
            assert response.status_code==503 and response.json()['code']=='UNKNOWN_EXECUTION'
            assert 'task_id' not in response.text and str(owner.store.root) not in response.text
        finally:
            with owner.store.connect() as db:
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,SECTION,receipt['command_id']));db.commit()
        assert client.get(path+'/commands/'+receipt['command_id']).status_code==200
    from rlflow.contracts import validate_runtime_state
    from rlflow.hybrid_cpu_unit_stop import validate_complete
    state=owner.store.audit();state[SECTION]['']={}
    with pytest.raises(ValueError):validate_runtime_state(state)
    with pytest.raises(Conflict,match='coverage'):
        validate_complete(state,(service.project_id,'fixture'),lambda key:pytest.fail('reject extra member before source read'),1)
