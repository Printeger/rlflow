"""Cold host boundaries; installed real history is separately consumed without RUN."""
import asyncio
from dataclasses import replace
import threading
import pytest
from fastapi.testclient import TestClient
from rlflow.hybrid_cold_result_host import ColdResultRegistration,create_cold_result_host
from rlflow.web_auth import AuthStore,Principal
from rlflow.store import Store,Conflict
from tests.test_hybrid_core_host import prepared

ORIGIN='http://127.0.0.1:8765'


def setup(tmp_path):
    store,core,credential,proposal=prepared(tmp_path)
    registration=ColdResultRegistration(core.root,core.project_id,core.store_epoch,core.registry,'CPU_TRIAL')
    auth=AuthStore([credential])
    token,_=auth.issue_request_token(Principal('cold_agent','agent',{'viewer'},{core.project_id}))
    return store,registration,auth,token


def test_cold_no_writes_routes_or_migration(tmp_path,monkeypatch):
    store,registration,auth,token=setup(tmp_path);before=store.audit();original_connect=Store.connect
    def forbidden(*a,**kw):pytest.fail('cold reader attempted creation/recovery/write')
    monkeypatch.setattr(Store,'__init__',forbidden);monkeypatch.setattr(Store,'recover',forbidden)
    monkeypatch.setattr(Store,'connect',forbidden)
    app=create_cold_result_host([registration],auth,origin=ORIGIN)
    path='/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_absent'
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get(path).status_code==401
        headers={'Authorization':'Bearer '+token}
        assert client.get(path,headers=headers).status_code==404
        assert client.get(path+'?run=true',headers=headers).status_code==400
        assert client.get(path.replace('CPU_TRIAL','ENGINEERING'),headers=headers).status_code==404
        for endpoint in ('commands','cpu-unit/commands','engineering-unit/commands','agent-requests'):
            assert client.post('/api/v1/projects/project_fixture/'+endpoint,headers=headers,json={}).status_code==404
        assert client.post('/api/v1/finite-host/commands',headers=headers,json={}).status_code==404
        assert not list((registration.root/'runtime').glob('*host*.lock'))
        auth.revoke(token);assert client.get(path,headers=headers).status_code==401
    # Only the test's final audit needs its original writable connection method.
    # During every cold host startup/request/drain it remained forbidden.
    monkeypatch.setattr(Store,'connect',original_connect)
    assert store.audit()==before
    with pytest.raises(Conflict):
        with TestClient(app,base_url=ORIGIN):pass


@pytest.mark.parametrize('mutation',['epoch','duplicate','kind','public','link','origin'])
def test_invalid_registration_rejected(tmp_path,mutation):
    store,row,auth,token=setup(tmp_path);rows=[row];origin=ORIGIN
    if mutation=='epoch':rows=[replace(row,store_epoch='store_'+'f'*32)]
    if mutation=='duplicate':rows*=2
    if mutation=='kind':rows=[replace(row,kind='AUTO')]
    if mutation=='public':row.root.chmod(0o755)
    if mutation=='link':
        import os
        os.link(row.root/'runtime/research.db',tmp_path/'aliased.db')
    if mutation=='origin':origin='http://remote.invalid:8765'
    before=store.audit()
    with pytest.raises((ValueError,PermissionError,Conflict)):
        create_cold_result_host(rows,auth,origin=origin)
    assert store.audit()==before


def test_held_reads_keep_capacity_after_waiter_cancel_and_drain(tmp_path,monkeypatch):
    _,row,auth,token=setup(tmp_path)
    import rlflow.hybrid_cold_result_host as module
    entered=threading.Event();release=threading.Event();lock=threading.Lock();count=0
    def held(reader,key):
        nonlocal count
        with lock:
            count+=1
            if count==2:entered.set()
        assert release.wait(5)
        raise Conflict('injected unavailable original source')
    monkeypatch.setattr(module,'read_public',held)
    app=create_cold_result_host([row],auth,origin=ORIGIN)
    async def actual():
        import httpx
        context=app.router.lifespan_context(app);await context.__aenter__()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            path='/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_absent'
            headers={'Authorization':'Bearer '+token}
            tasks=[asyncio.create_task(client.get(path,headers=headers)) for _ in range(2)]
            try:
                assert await asyncio.to_thread(entered.wait,3)
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
                assert (await client.get(path,headers=headers)).status_code==429
                closing=asyncio.create_task(context.__aexit__(None,None,None));await asyncio.sleep(.02)
                assert not closing.done()
                assert (await client.get(path,headers=headers)).status_code==503
                release.set();await closing
                assert app.state.cold_result_drain.done()
            finally:release.set()
    asyncio.run(actual())


def test_real_malformed_source_and_registration_drift_fail_closed(tmp_path):
    store,row,auth,token=setup(tmp_path)
    app=create_cold_result_host([row],auth,origin=ORIGIN)
    from rlflow.hybrid_cpu_assessment import SECTION
    import sqlite3
    # Only this newly created test database, never retained checkpoint76 history.
    with sqlite3.connect(store.db) as db:
        db.execute('INSERT INTO projection VALUES(?,?,?,?,?)',(SECTION,'cpu_assessment_damaged','{}',0,None))
    path='/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_damaged'
    headers={'Authorization':'Bearer '+token}
    with TestClient(app,base_url=ORIGIN) as client:
        response=client.get(path,headers=headers)
        assert response.status_code==503 and response.json()['code']=='UNSUPPORTED_CAPABILITY'
        row.root.chmod(0o755)
        assert client.get(path,headers=headers).status_code==503


def test_late_revoke_is_checked_after_real_read_future(tmp_path,monkeypatch):
    _,row,auth,token=setup(tmp_path)
    import rlflow.hybrid_cold_result_host as module
    entered=threading.Event();release=threading.Event()
    def held(reader,key):
        entered.set();assert release.wait(5);return {'should_not_be_delivered':True}
    monkeypatch.setattr(module,'read_public',held)
    app=create_cold_result_host([row],auth,origin=ORIGIN)
    path='/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_absent'
    with TestClient(app,base_url=ORIGIN) as client:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(client.get,path,headers={'Authorization':'Bearer '+token})
            try:
                assert entered.wait(3);auth.revoke(token);release.set()
                assert future.result(timeout=3).status_code==401
            finally:release.set()


@pytest.mark.parametrize('mutation',['root','epoch','copy'])
def test_captured_Store_rebinding_rejected_before_auth(tmp_path,monkeypatch,mutation):
    _,row,auth,token=setup(tmp_path)
    import rlflow.hybrid_cold_result_host as module
    captured=[];original=module.DeliveryEvidenceReader
    def capture(source):
        reader=original(source);captured.append(reader);return reader
    monkeypatch.setattr(module,'DeliveryEvidenceReader',capture)
    app=create_cold_result_host([row],auth,origin=ORIGIN)
    with TestClient(app,base_url=ORIGIN) as client:
        store=captured[0].store
        if mutation=='root':store.root=tmp_path
        elif mutation=='epoch':store.store_epoch='store_'+'f'*32
        else:
            import sqlite3
            replacement=tmp_path/'copy.db'
            with store.read_connection() as source,sqlite3.connect(replacement) as destination:
                source.backup(destination)
            store.db=replacement
            info=replacement.stat();store._existing_identity=(info.st_dev,info.st_ino)
        def forbidden(*a,**kw):pytest.fail('rebound source reached Auth')
        monkeypatch.setattr(auth,'resolve',forbidden)
        path='/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_absent'
        assert client.get(path,headers={'Authorization':'Bearer '+token}).status_code==503
