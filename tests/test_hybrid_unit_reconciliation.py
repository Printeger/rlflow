"""Real retained unit phases reconciled through original human HTTP authority."""
import subprocess
import os
import asyncio
import threading
import pytest
from fastapi.testclient import TestClient
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start,stop
from tests.test_execution_adapter import setup as native_setup


@pytest.mark.parametrize('boundary',['late_auth','STOP'])
def test_missing_decision_final_original_guard_blocks_write(application,monkeypatch,boundary):
    host,units,services,_,app,token,headers=application
    unit=units[0];service=services[0];body=start(service)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        with monkeypatch.context() as patch:
            patch.setattr(unit.output,'decide',lambda *a,**kw:(_ for _ in ()).throw(OSError('before decision')))
            accepted=client.post(path(service)+'/commands',headers=headers,json=body)
        assert accepted.status_code==202 and unit._last is None
        before=service.store.version();other=services[1].store.audit();entered=[]
        occupied=host.pool.snapshot()['occupied'];assert occupied==1  # Untouched engineering claim.
        clock=[service.auth.clock()]
        monkeypatch.setattr(service.auth,'clock',lambda:clock[0])
        commit=service.store._commit
        from rlflow.hybrid_cpu_assessment import SECTION
        def fenced(db,event,key,payload,*a,**kw):
            if any(s==SECTION and 'machine_verification' in v for s,k,v in payload['put']):
                entered.append(True)
                if boundary=='STOP':unit._cancelled.set()  # Original irreversible memory STOP gate.
                else:clock[0]+=1000  # Guard checks expiry under its original held Auth lock.
            return commit(db,event,key,payload,*a,**kw)
        monkeypatch.setattr(service.store,'_commit',fenced)
        recovered=client.post(path(service)+'/commands/'+accepted.json()['command_id']+'/reconcile',headers=headers,json=body)
        assert entered and recovered.status_code in (403,503),recovered.text
        assert service.store.version()==before and len(service.store.objects(SECTION))==1
        assert services[1].store.audit()==other and host.pool.snapshot()['occupied']==occupied


def test_uncertain_real_spawn_reconcile_preserves_UNKNOWN_exposure(application,monkeypatch):
    host,units,services,_,app,token,headers=application
    unit=units[0];service=services[0];body=start(service);children=[];spawn=subprocess.Popen
    occupied=host.pool.snapshot()['occupied'];assert occupied==2
    def lost(*a,**kw):
        children.append(spawn(*a,**kw))
        raise OSError('real original child started, Popen return lost')
    try:
        with TestClient(app,base_url=ORIGIN) as client:
            client.cookies.set('rlflow_session',token)
            with monkeypatch.context() as patch:
                patch.setattr(subprocess,'Popen',lost)
                accepted=client.post(path(service)+'/commands',headers=headers,json=body)
            assert accepted.status_code==202 and len(children)==1
            before=service.store.version();other=services[1].store.audit()
            def forbidden(*a,**kw):pytest.fail('UNKNOWN original spawn must not be redispatched/adopted')
            with monkeypatch.context() as patch:
                for obj,name in ((host,'run'),(unit.runtime,'start'),(unit,'_collect'),(subprocess,'Popen'),(os,'pwrite')):
                    patch.setattr(obj,name,forbidden)
                reply=client.post(path(service)+'/commands/'+accepted.json()['command_id']+'/reconcile',headers=headers,json=body)
            assert reply.status_code==200,reply.text
            assert reply.json()['result']['status']=='UNKNOWN_RESULT_UNAVAILABLE' and reply.json()['result_fact'] is None
            assert service.store.version()==before and services[1].store.audit()==other
            assert host.pool.snapshot()['occupied']==occupied and len(children)==1
            attempt=unit.runtime._issued(unit.lease)
            assert not attempt['release_entered']
            assert unit.runtime.sources._issued(attempt['source'])['producer'] is None
            balance=service.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']
            assert balance['consumed']==0 and balance['unknown_exposure']==1
            cancelled=host.cancel_all()
            assert cancelled[0]['result']['status']=='UNKNOWN_CLEANUP_REQUIRED'
            assert cancelled[1]['result']['status']=='CANCELLED_SCOPE_STOPPED'
            assert host.pool.snapshot()['occupied']==1
    finally:
        # Laboratory-only reap of the actually started child; never install
        # this identity into the product or claim exposure FREE from its death.
        for child in children:
            child.wait(timeout=5)
            if child.stdin is not None:child.stdin.close()
        if unit.runtime._live:unit.runtime.shutdown_safety()  # Retire own FDs, not durable exposure.
    assert host.pool.snapshot()['occupied']==1


def test_held_reconcile_preparation_keeps_capacity_and_STOP_channel(application,monkeypatch):
    host,units,services,_,app,token,headers=application
    service=services[0];unit=units[0];body=start(service)
    entered=threading.Event();release=threading.Event();lock=threading.Lock();count=0
    original=service._reconcile_source
    def held(command):
        nonlocal count
        with lock:
            count+=1
            if count==2:entered.set()
        assert release.wait(8)
        return original(command)
    async def actual():
        import httpx
        context=app.router.lifespan_context(app);await context.__aenter__()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,
                    cookies={'rlflow_session':token}) as client:
                accepted=await client.post(path(service)+'/commands',headers=headers,json=body)
                assert accepted.status_code==202
                occupied=host.pool.snapshot()['occupied'];assert occupied==1
                other=services[1].store.audit()
                route=path(service)+'/commands/'+accepted.json()['command_id']+'/reconcile'
                monkeypatch.setattr(service,'_reconcile_source',held)
                tasks=[asyncio.create_task(client.post(route,headers=headers,json=body)) for _ in range(2)]
                try:
                    assert await asyncio.to_thread(entered.wait,3)
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
                    assert (await client.post(route,headers=headers,json=body)).status_code==429
                    stopped=await asyncio.wait_for(client.post(path(service)+'/commands',
                        headers={**headers,'Idempotency-Key':'held-stop'},json=stop(service)),2)
                    assert stopped.status_code==202 and unit._cancelled.is_set()
                    assert host.pool.snapshot()['occupied']==occupied and services[1].store.audit()==other
                    closing=asyncio.create_task(context.__aexit__(None,None,None));await asyncio.sleep(.02)
                    assert not closing.done() and app.state.cpu_unit_reconcile_pool.pending==2
                    release.set();await closing
                    assert app.state.cpu_unit_reconcile_pool.pending==0
                finally:
                    release.set();await asyncio.gather(*tasks,return_exceptions=True)
        finally:
            release.set()
            if not app.state.cpu_unit_reconcile_pool.closed:await context.__aexit__(None,None,None)
    asyncio.run(actual())


def test_missing_CPU_decision_written_once_and_corrupt_sources_503(application,monkeypatch):
    host,units,services,_,app,token,headers=application
    unit=units[0];service=services[0];body=start(service);decide=unit.output.decide
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        def missing(*a,**kw):raise OSError('injected failure BEFORE missing decision write')
        with monkeypatch.context() as patch:
            patch.setattr(unit.output,'decide',missing)
            reply=client.post(path(service)+'/commands',headers=headers,json=body)
        assert reply.status_code==202 and unit._last is None
        command=reply.json()['command_id'];route=path(service)+'/commands/'+command+'/reconcile'
        from rlflow.hybrid_cpu_assessment import SECTION
        assert len(service.store.objects(SECTION))==1
        before=service.store.version();other=services[1].store.audit()
        def forbidden(*a,**kw):pytest.fail('missing-stage reconcile repeated execution/effect')
        with monkeypatch.context() as patch:
            for obj,name in ((host,'run'),(unit.runtime,'start'),(unit.runtime.sources,'_runtime_release'),
                    (unit,'_collect'),(subprocess,'Popen'),(os,'pwrite')):patch.setattr(obj,name,forbidden)
            recovered=client.post(route,headers=headers,json=body)
        assert recovered.status_code==200,recovered.text
        assert service.store.version()==before+1 and len(service.store.objects(SECTION))==2
        assert recovered.json()['result']['status']=='EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
        assert services[1].store.audit()==other
        from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET
        for section,key in ((BUDGET[0],service._source_key(command)),(SECTION,recovered.json()['result_fact']['id'])):
            with service.store.connect() as db:
                original=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,key)).fetchone()[0]
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',('{}',section,key));db.commit()
            try:
                bad=client.post(route,headers=headers,json=body)
                assert bad.status_code==503,bad.text
            finally:
                with service.store.connect() as db:
                    db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(original,section,key));db.commit()
        assert service.store.version()==before+1


def test_actual_dual_lost_machine_return_reconcile_without_effect_retry(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    original_spawn=subprocess.Popen;launches=[]
    def counted(*a,**kw):launches.append(a[0]);return original_spawn(*a,**kw)
    monkeypatch.setattr(subprocess,'Popen',counted)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        for index,service in enumerate(services):
            unit=units[index];body=start(service);output=unit.output
            name='decide' if index==0 else 'accept_machine';original=getattr(output,name);lost=[]
            def uncertain(*a,**kw):
                value=original(*a,**kw);lost.append(value);raise OSError('injected lost original machine return AFTER commit')
            with monkeypatch.context() as patch:
                patch.setattr(output,name,uncertain)
                response=client.post(path(service)+'/commands',headers=headers,json=body)
            assert response.status_code==202 and lost and unit._last is None
            receipt=response.json();command=receipt['command_id'];version=service.store.version()
            other=services[1-index].store.audit()
            duplicate=client.post(path(service)+'/commands',headers=headers,json=body)
            assert duplicate.status_code==202 and duplicate.json()['duplicate'] and unit._last is None
            assert service.store.version()==version
            def forbidden(*a,**kw):pytest.fail('reconciliation attempted new execution/collection/write')
            with monkeypatch.context() as patch:
                for obj,name in ((host,'run'),(unit.runtime,'start'),(unit.runtime.sources,'_runtime_release'),
                        (unit,'_collect'),(subprocess,'Popen'),(os,'pwrite')):
                    patch.setattr(obj,name,forbidden)
                recovered=client.post(path(service)+'/commands/'+command+'/reconcile',headers=headers,json=body)
                assert recovered.status_code==200,recovered.text
                value=recovered.json()
                assert value['result']['status']==('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW' if index==0 else 'MACHINE_ACCEPTED_PENDING_REVIEW')
                assert value['result_fact']['sha256'] and value['result']['goal_completed'] is False
                assert not value['new_dispatch_enabled'] and not value['automatic_effect_retry_enabled']
                assert client.post(path(service)+'/commands/'+command+'/reconcile',headers=headers,json=body).json()==value
                assert client.post(path(service)+'/commands/'+command+'/reconcile',headers=headers,json=stop(service)).status_code==400
                assert not unit._cancelled.is_set()
                assert client.post(path(service)+'/commands/'+command+'/reconcile',headers={**headers,'Idempotency-Key':'different'},json=body).status_code==409
                assert client.post(path(service)+'/commands/'+command+'/reconcile',headers=headers,
                    json={**body,'expected_state_version':service.store.version()}).status_code==503
            assert service.store.version()==version and services[1-index].store.audit()==other
        assert len(launches)==2 and host.pool.snapshot()['occupied']==0
