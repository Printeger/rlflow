"""One preprovisioned Auth, two independently approved projects, actual shared pool."""
import copy
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import threading

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_cpu_unit_control import CpuUnitControlService
from rlflow.hybrid_engineering_unit_control import EngineeringUnitControlService
from rlflow.hybrid_finite_host_app import create_finite_host_app
from rlflow.hybrid_resource_telemetry import FixedUnitTelemetry
from rlflow.hybrid_engineering_patch import AFTER
from rlflow.web_auth import AuthStore, Credential, Principal
from tests.test_hybrid_host_execution import shared
from tests.test_execution_adapter import setup as native_setup

ORIGIN='http://127.0.0.1:8765'
PHRASE='Working plan isolated synthetic fixture passphrase'

@pytest.fixture
def application(tmp_path,native_setup,monkeypatch):
    # Trusted fixture setup BEFORE either independent approval. Never rebind
    # an existing Runtime/Store/Approval witness to a replacement Auth.
    auth=AuthStore([Credential.create(Principal('fixture_human','human',
        {'operator','approver'},{'shared_project_0','shared_project_1'}),PHRASE)],ttl=900)
    from tests import test_hybrid_working_plan_service as working
    monkeypatch.setattr(working,'AuthStore',lambda *args,**kwargs:auth)
    fixture=shared.__wrapped__(tmp_path,native_setup,monkeypatch)
    try:
        host,units=next(fixture)
        controls=(CpuUnitControlService(host,units[0].lease,auth,origin=ORIGIN),
            EngineeringUnitControlService(host,units[1].lease,auth,origin=ORIGIN))
        observers=tuple(FixedUnitTelemetry(host,u.lease) for u in units)
        for observer in observers:assert observer.sample()
        app=create_finite_host_app(host,controls,auth,origin=ORIGIN,observers=observers)
        token,access=auth.login('fixture_human',PHRASE)
        headers={'Origin':ORIGIN,'X-CSRF-Token':access.csrf,'Idempotency-Key':'run'}
        yield host,units,controls,observers,app,token,headers
    finally:fixture.close()

def path(service):
    kind='cpu-unit' if type(service) is CpuUnitControlService else 'engineering-unit'
    return f'/api/v1/projects/{service.project_id}/{kind}'

def start(service):
    return {'action':'START_FIXED_CPU' if type(service) is CpuUnitControlService else 'START_FIXED_ENGINEERING',
        'task_id':service.task_id,'expected_state_version':service.store.version()}

def stop(service):
    return {'action':'CANCEL_FIXED_CPU_TRIAL' if type(service) is CpuUnitControlService else 'CANCEL_FIXED_ENGINEERING',
        'task_id':service.task_id}

def test_actual_shared_app_CPU_STOP_before_G_leaves_other_original_project_executable(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    cpu,engineering=units;cs,es=services
    assert cs.auth is es.auth is cpu.runtime.store._hybrid_auth_owner is engineering.runtime.store._hybrid_auth_owner
    entered=threading.Event();register=cpu.runtime._register_release
    def waiting(attempt):
        entered.set();assert cpu._cancelled.wait(2)
        return register(attempt)
    monkeypatch.setattr(cpu.runtime,'_register_release',waiting)
    engineering_version=es.store.version();engineering_attempt=engineering._actual()
    with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session',token)
        assert len(client.get('/api/v1/projects').json()['items'])==2
        bad=client.post(path(cs)+'/commands',headers=headers,json={**stop(cs),'task_id':es.task_id})
        assert bad.status_code==403 and not cpu._cancelled.is_set() and not engineering._cancelled.is_set()
        future=worker.submit(client.post,path(cs)+'/commands',headers=headers,json=start(cs))
        assert entered.wait(8)
        stopped=client.post(path(cs)+'/commands',headers={**headers,'Idempotency-Key':'stop'},json=stop(cs))
        assert stopped.status_code==202,stopped.text
        assert future.result(timeout=10).status_code==202
        assert not engineering._cancelled.is_set() and not engineering_attempt['spawn_entered']
        assert es.store.version()==engineering_version and host.pool.snapshot()['occupied']==1
        attempt=cpu.runtime._issued(cpu.lease);source=cpu.runtime.sources._issued(attempt['source'])
        assert not attempt['release_entered'] and source['producer'].poll() is not None
        assert all(fd is None for fd in source['fds'].values())
        run=client.post(path(es)+'/commands',headers=headers,json=start(es))
        assert run.status_code==202,run.text
        assert engineering._last['status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
        assert engineering._last['fact']['machine_verification']['derived']['passed_cases']==21
        assert host.pool.snapshot()['occupied']==0
    print('shared_auth_HTTP_STOP_isolation',dict(cpu_G=False,other_store_unchanged=True,other_AST_cases=21,occupied=0),flush=True)

def test_actual_shared_app_both_original_results_scoped_reads_and_preflight(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    import rlflow.hybrid_finite_host_app as composition
    with monkeypatch.context() as patch:
        patch.setattr(composition,'create_app',lambda *a,**k:pytest.fail('invalid finite capture must precede assembly'))
        for controls in ((services[0],services[0]),(copy.copy(services[0]),services[1])):
            with pytest.raises((ValueError,PermissionError)):create_finite_host_app(host,controls,services[0].auth,origin=ORIGIN)
        with pytest.raises(ValueError):create_finite_host_app(host,services,services[0].auth,origin=ORIGIN,max_control_jobs=True)
        with pytest.raises(ValueError):create_finite_host_app(host,[*services,*services],services[0].auth,origin=ORIGIN)
        with pytest.raises(ValueError):create_finite_host_app(host,services,services[0].auth,origin=ORIGIN,observers=[*observers,*observers])
        patch.setattr(services[1].reader,'store_epoch','foreign_epoch')
        with pytest.raises(ValueError):create_finite_host_app(host,services,services[0].auth,origin=ORIGIN)
    launches=[];writes=[];spawn=subprocess.Popen;pwrite=os.pwrite
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(launches.append(a[0]),spawn(*a,**k))[1])
    monkeypatch.setattr(os,'pwrite',lambda fd,data,offset:(writes.append((data,offset)),pwrite(fd,data,offset))[1])
    for u,observer in zip(units,observers):
        register=u.runtime._register_release
        def sampled(attempt,_register=register,_observer=observer):
            value=_register(attempt);assert _observer.sample();return value
        monkeypatch.setattr(u.runtime,'_register_release',sampled)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        for s in services:
            body=start(s);response=client.post(path(s)+'/commands',headers=headers,json=body)
            assert response.status_code==202,response.text
            version=s.store.version()
            assert client.post(path(s)+'/commands',headers=headers,json=body).json()['duplicate']
            assert s.store.version()==version
        assert units[0]._last['status']=='EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
        assert units[1]._last['status']=='MACHINE_ACCEPTED_PENDING_REVIEW'
        assert len(launches)==2 and writes==[(AFTER,0)] and host.pool.snapshot()['occupied']==0
        project=services[1].project_id;base=f'/api/v1/projects/{project}'
        page=client.get(base+'/candidate-outputs');assert page.status_code==200,page.text
        row=page.json()['items'][0]
        detail=client.get(base+'/candidate-outputs/'+row['id']);assert detail.status_code==200,detail.text
        evidence=detail.json()['candidate']['evidence']
        # Original kernel clock delta may legitimately be zero for this tiny
        # fixed function. Match the sealed protocol, never invent positive CPU.
        assert type(evidence['cpu_ns']) is int and 0<=evidence['cpu_ns']<=3_000_000_000
        assert type(evidence['worker_wall_ns']) is int and 0<=evidence['worker_wall_ns']<=3_000_000_000
        assert evidence['cpu_measurement_scope']=='ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT'
        assert detail.json()['candidate']['actual_cost_status']=='UNKNOWN'
        for s in services:
            telemetry=client.get(f'/api/v1/projects/{s.project_id}/telemetry')
            assert telemetry.status_code==200,telemetry.text
            assert telemetry.json()['project_id']==s.project_id
        bearer,_=services[0].auth.issue_bearer(Principal('scoped_reader','agent',{'viewer'},{services[0].project_id}))
        assert client.get(base+'/candidate-outputs',headers={'Authorization':'Bearer '+bearer}).status_code==404
        assert client.post(path(services[0])+'/commands',headers={**headers,'Authorization':'Bearer '+bearer},json=stop(services[0])).status_code==403
        assert not any(u._cancelled.is_set() for u in units)
    print('shared_auth_HTTP_actual_results',dict(launches=2,pwrites=1,cpu_status=units[0]._last['status'],engineering_AST=21,worker_cpu_ns=evidence['cpu_ns'],billing='UNKNOWN'),flush=True)
