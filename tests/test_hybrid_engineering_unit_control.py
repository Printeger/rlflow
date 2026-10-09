"""Actual authenticated original engineering dispatch, write and STOP boundaries."""
import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_engineering_unit_control import EngineeringUnitControlService
from rlflow.hybrid_engineering_unit_stop import SECTION,EVENT
from rlflow.hybrid_candidate_output import SECTIONS
from rlflow.hybrid_engineering_patch import BEFORE,AFTER
from rlflow.hybrid_host_execution import HostExecutionService
from rlflow.store import Conflict
from rlflow.web_api import Project,create_app
from tests.test_hybrid_engineering_execution_unit import unit,candidate
from tests.test_hybrid_engineering_output import engineering_runtime
from tests.test_execution_adapter import setup as native_setup

ORIGIN='http://127.0.0.1:8765'
PHRASE='Working plan isolated synthetic fixture passphrase'

def setup(context,*,origin=ORIGIN):
    owner,lease,output,execution=unit(context)
    host=HostExecutionService(owner.pool);host.bind_unit(execution)
    auth=owner.store._hybrid_auth_owner;token,access=auth.login('fixture_human',PHRASE)
    service=EngineeringUnitControlService(host,lease,auth,origin=origin)
    project=service.project_id
    app=create_app([Project(project,str(owner.store.root),'fixture')],auth,origin=origin,
        engineering_unit_services={project:service})
    headers={'Origin':origin,'X-CSRF-Token':access.csrf,'Idempotency-Key':'run'}
    body={'action':'START_FIXED_ENGINEERING','task_id':service.task_id,'expected_state_version':owner.store.version()}
    return owner,execution,service,app,token,headers,f'/api/v1/projects/{project}/engineering-unit',body

def stop(body):return {'action':'CANCEL_FIXED_ENGINEERING','task_id':body['task_id']}

def test_actual_HTTP_single_write_AST21_receipt_retry_STOP_and_recovery(engineering_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(engineering_runtime)
    spawn=subprocess.Popen;pwrite=os.pwrite;launches=[];writes=[]
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(launches.append(a[0]),spawn(*a,**k))[1])
    monkeypatch.setattr(os,'pwrite',lambda fd,data,offset:(writes.append((data,offset)),pwrite(fd,data,offset))[1])
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        assert client.get(path).json()['task']['kind']=='LOCAL_CPU_PATCH_PROPOSAL'
        wrong={**body,'action':'START_FIXED_CPU'}
        assert client.post(path+'/commands',headers=headers,json=wrong).status_code==400
        assert not execution._cancelled.is_set() and not launches
        response=client.post(path+'/commands',headers=headers,json=body)
        assert response.status_code==202,response.text
        receipt=response.json();assert receipt['action']=='START_FIXED_ENGINEERING'
        assert execution._last['status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
        assert execution._last['fact']['machine_verification']['derived']['passed_cases']==21
        assert candidate(owner,execution.lease).read_bytes()==AFTER and writes==[(AFTER,0)] and len(launches)==1
        assert owner.pool.snapshot()['occupied']==0
        version=owner.store.version()
        assert client.post(path+'/commands',headers=headers,json=body).json()['duplicate']
        assert owner.store.version()==version and len(writes)==len(launches)==1
        assert client.post(path+'/commands',headers=headers,json=stop(body)).status_code==409
        assert not execution._cancelled.is_set()
        stopped=client.post(path+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(body))
        assert stopped.status_code==202,stopped.text
        assert stopped.json()['recorded_phase']=='STOP_INTENT_ACCEPTED'
        # No additional pwrite or machine fact; STOP only reconciles original plain output.
        before=owner.store.version()
        assert client.post(path+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(body)).json()['duplicate']
        assert owner.store.version()==before and len(writes)==len(launches)==1
        profile=client.get(path).json()
        assert profile['last_sdk_status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
        assert not profile['goal_completed'] and profile['independent_review_status']=='NOT_PERFORMED'
        for call in (lambda:owner.store.transact(EVENT,receipt['command_id'],lambda state:None),
            lambda:owner.store.transact_objects(EVENT,stopped.json()['command_id'],[],lambda state:None)):
            with pytest.raises(PermissionError):call()
        owner.shutdown()
        assert client.get(path).json()['original_owner_available'] is False
        assert client.get(path+'/commands/'+receipt['command_id']).status_code==200
    state=owner.store.audit()
    from rlflow.snapshot_maintenance import maintain
    with owner.store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=?',(owner.store.version(),));db.commit()
    assert maintain(owner.store,seconds=20), 'engineering STOP proof must survive original same-RO maintenance'
    owner.store.snapshot();assert owner.store.recover()==state
    print('actual_engineering_HTTP',dict(single_pwrite=len(writes),launches=len(launches),AST_cases=21,Goal=False,Review='NOT_PERFORMED'))

@pytest.mark.parametrize('boundary',['G','PWRITE','MACHINE_COMMIT'])
def test_actual_last_human_auth_denies_new_effect_not_original_cleanup(engineering_runtime,monkeypatch,boundary):
    owner,execution,service,app,token,headers,path,body=setup(engineering_runtime)
    clock=[service.auth.clock()];monkeypatch.setattr(service.auth,'clock',lambda:clock[0]);seen=[]
    if boundary=='G':
        gate=owner._check_release_gate
        def expired(attempt):clock[0]+=1000;seen.append(True);return gate(attempt)
        monkeypatch.setattr(owner,'_check_release_gate',expired)
    elif boundary=='PWRITE':
        gate=execution.output._last_effect
        def expired(guard):
            if guard.row['material'].fd is not None and not guard.row['material'].write_entered:
                clock[0]+=1000;seen.append(True)
            return gate(guard)
        monkeypatch.setattr(execution.output,'_last_effect',expired)
    else:
        commit=owner.store._commit
        def expired(db,event,key,payload,*args,**kwargs):
            if any(s in SECTIONS and k and 'machine_verification' in v for s,k,v in payload['put']):
                clock[0]+=1000;seen.append(True)
            return commit(db,event,key,payload,*args,**kwargs)
        monkeypatch.setattr(owner.store,'_commit',expired)
    result=service.execute(body,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='run')
    assert result['recorded_phase']=='HANDOFF_UNKNOWN' and seen
    assert execution._last is None and owner.pool.snapshot()['occupied']==0
    assert candidate(owner,execution.lease).read_bytes()==(AFTER if boundary=='MACHINE_COMMIT' else BEFORE)
    assert all('machine_verification' not in value for _,value in owner.store.objects(SECTIONS[1]))
    source=owner.sources._issued(owner._issued(execution.lease)['source'])
    assert source['producer'].returncode is not None and all(fd is None for fd in source['fds'].values())
    if boundary=='G':assert not owner._issued(execution.lease)['release_entered']

def test_cancel_during_final_auth_identity_fence_cannot_enter_pwrite(engineering_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(engineering_runtime)
    authority=service._check_final_authority;seen=[]
    def cancelled_during_auth(*,cleanup,attempt=None):
        value=authority(cleanup=cleanup,attempt=attempt)
        row=execution.output._rows.get(id(execution.lease))
        if not cleanup and row is not None and row['material'].fd is not None and not row['material'].write_entered:
            execution._cancelled.set();seen.append(True)
        return value
    monkeypatch.setattr(service,'_check_final_authority',cancelled_during_auth)
    monkeypatch.setattr(os,'pwrite',lambda *a:pytest.fail('cancel latched during Auth must be rechecked before pwrite'))
    result=service.execute(body,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='run')
    assert result['recorded_phase']=='HANDOFF_UNKNOWN' and seen
    assert candidate(owner,execution.lease).read_bytes()==BEFORE and owner.pool.snapshot()['occupied']==0

def test_entered_write_lost_return_STOP_after_expiry_captures_without_rewrite_or_machine_accept(engineering_runtime,monkeypatch):
    owner,execution,service,app,token,headers,path,body=setup(engineering_runtime)
    writes=[];pwrite=os.pwrite
    def lost(fd,data,offset):writes.append(True);pwrite(fd,data,offset);raise OSError('entered write lost return')
    monkeypatch.setattr(os,'pwrite',lost)
    result=service.execute(body,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='run')
    assert result['recorded_phase']=='HANDOFF_UNKNOWN' and writes==[True]
    assert execution.output._rows[id(execution.lease)]['material'].fd is None
    assert owner.store.objects(SECTIONS[1])==[] and candidate(owner,execution.lease).read_bytes()==AFTER
    clock=[service.auth.clock()];monkeypatch.setattr(service.auth,'clock',lambda:clock[0])
    accept=service._accept_stop
    def expired_after_accept(*a):
        value=accept(*a);clock[0]+=1000;return value
    monkeypatch.setattr(service,'_accept_stop',expired_after_accept)
    accepted=service.execute(stop(body),token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,idempotency_key='stop')
    assert accepted['status']=='ACCEPTED' and execution._cancelled.is_set()
    outputs=owner.store.objects(SECTIONS[1]);assert len(outputs)==1
    assert outputs[0][1]['state']=='OUTPUT_CAPTURED_AUDIT_ONLY' and 'machine_verification' not in outputs[0][1]
    assert writes==[True] and owner.pool.snapshot()['occupied']==0
    state=owner.store.audit();owner.store.snapshot();assert owner.store.recover()==state
