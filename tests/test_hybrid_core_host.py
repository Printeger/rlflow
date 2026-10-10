"""Original existing Core hosting; durable suggestion/DRAFT across restart."""
from copy import deepcopy
from dataclasses import replace
from fastapi.testclient import TestClient
import pytest
from rlflow.hybrid_core_host import CoreRegistration,create_core_host
from rlflow.store import Store,Conflict
from rlflow.observation import enable
from rlflow.web_auth import AuthStore,Credential,Principal
from tests.test_hybrid_registry import bound
from tests.test_hybrid_control_api import ORIGIN,PHRASE


def prepared(tmp_path):
    root=tmp_path/'state';root.mkdir(mode=0o700)
    store=Store(root);epoch=enable(store,'project_fixture',data_mode='fixture')
    (root/'runtime').chmod(0o700)
    (root/'runtime/writer.lock').chmod(0o600)
    (root/'runtime/research.db').chmod(0o600)
    registry,proposal=bound()
    registration=CoreRegistration(root,'project_fixture','fixture',epoch,registry)
    credential=Credential.create(Principal('operator','human',{'operator'},{'project_fixture'}),PHRASE)
    return store,registration,credential,proposal


def test_existing_Core_restart_does_not_migrate_or_reexecute(tmp_path,monkeypatch):
    old,registration,credential,proposal=prepared(tmp_path)
    def forbidden(*a,**kw):pytest.fail('hosting invoked initialization/migration/recovery')
    monkeypatch.setattr(Store,'__init__',forbidden)
    monkeypatch.setattr(Store,'recover',forbidden)
    auth=AuthStore([credential]);app=create_core_host([registration],auth,origin=ORIGIN)
    token,_=auth.issue_request_token(Principal('client_agent','agent',{'viewer'},{'project_fixture'}))
    base='/api/v1/projects/project_fixture/agent-requests'
    with TestClient(app,base_url=ORIGIN) as client:
        discovery=client.get('/api/v1/projects/project_fixture/proposal-contract',headers={'Authorization':'Bearer '+token})
        assert discovery.status_code==200 and discovery.json()['execution_enabled'] is False
        response=client.post(base,headers={'Authorization':'Bearer '+token,'Origin':ORIGIN,'Idempotency-Key':'restart_original'},
            json={'action':'submit_goal','proposal':proposal,'expected_revision':0})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['status']=='AWAITING_HUMAN' and old.version()==0
        login=client.post('/api/v1/login',headers={'Origin':ORIGIN},json={'principal_id':'operator','passphrase':PHRASE})
        assert login.status_code==200
        accepted=client.post(base+'/'+saved['request_id']+'/forward',headers={'Origin':ORIGIN,
            'X-CSRF-Token':login.json()['csrf_token']},json={'request_hash':saved['request_hash'],'expected_version':0})
        assert accepted.status_code==200,accepted.text
        assert accepted.json()['status']=='ADOPTED' and old.version()==1
        with pytest.raises(BlockingIOError):create_core_host([registration],auth,origin=ORIGIN)
    renewed=AuthStore([credential]);replacement=create_core_host([registration],renewed,origin=ORIGIN)
    new_token,_=renewed.issue_request_token(Principal('client_agent','agent',{'viewer'},{'project_fixture'}))
    with TestClient(replacement,base_url=ORIGIN) as client:
        assert client.get(base+'/'+saved['request_id'],headers={'Authorization':'Bearer '+token}).status_code==401
        result=client.get(base+'/'+saved['request_id'],headers={'Authorization':'Bearer '+new_token})
        assert result.status_code==200 and result.json()['status']=='ADOPTED' and old.version()==1
        assert not any(old.objects(s) for s in ('tasks','sessions','jobs','approvals'))


@pytest.mark.parametrize('mutation',['epoch','duplicate','private','unknown','origin','hidden','unknown_marker','catalog'])
def test_invalid_hosting_does_not_initialize_or_bind(tmp_path,monkeypatch,mutation):
    store,registration,credential,proposal=prepared(tmp_path)
    auth=AuthStore([credential]);registrations=[registration];origin=ORIGIN
    if mutation=='epoch':registrations=[replace(registration,store_epoch='store_'+'f'*32)]
    elif mutation=='duplicate':registrations*=2
    elif mutation=='private':registration.root.chmod(0o755)
    elif mutation=='origin':origin='http://remote.invalid:8765'
    elif mutation=='catalog':
        from rlflow.hybrid_registry import Registry
        import json
        catalog=json.loads(registration.registry._raw);catalog['project_id']='foreign_project'
        registrations=[replace(registration,registry=Registry(catalog))]
    elif mutation in ('hidden','unknown_marker'):
        with store.connect() as db:
            if mutation=='hidden':db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',('{"hidden_active":true}','tasks',''))
            else:db.execute('INSERT INTO projection VALUES(?,?,?,?,?)',('unknown_domain','','{}',0,None))
            db.commit()
    else:
        with store.connect() as db:
            db.execute('INSERT INTO projection VALUES(?,?,?,?,?)',('tasks','unknown_active','{}',0,None));db.commit()
    def forbidden(*a,**kw):pytest.fail('invalid hosting reached new Core binding')
    monkeypatch.setattr('rlflow.hybrid_core_host.DraftService',forbidden)
    with pytest.raises((ValueError,PermissionError,Conflict)):
        create_core_host(registrations,auth,origin=origin)
    assert not (registration.root/'agent-requests.sqlite3').exists()


def test_owner_process_gate_precedes_Auth(tmp_path,monkeypatch):
    import os
    store,registration,credential,proposal=prepared(tmp_path)
    auth=AuthStore([credential]);app=create_core_host([registration],auth,origin=ORIGIN)
    with TestClient(app,base_url=ORIGIN) as client:
        pid=os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr('rlflow.hybrid_core_host.os.getpid',lambda:pid+1)
            patch.setattr(auth,'resolve',lambda *a,**kw:pytest.fail('foreign process reached Auth'))
            assert client.get('/api/v1/projects').status_code==503


def test_all_project_preflight_precedes_first_inbox(tmp_path):
    from rlflow.hybrid_registry import Registry
    import json
    first=tmp_path/'first';first.mkdir()
    second=tmp_path/'second';second.mkdir()
    original,a,credential,proposal=prepared(first)
    old,b,unused,unused_proposal=prepared(second)
    catalog=json.loads(b.registry._raw);catalog['project_id']='second_project'
    b=replace(b,project_id='second_project',registry=Registry(catalog))
    # Original metadata still belongs to project_fixture, so second source
    # fails without changing that scope or partially hosting the first.
    with pytest.raises(Conflict):create_core_host([a,b],AuthStore([credential]),origin=ORIGIN)
    assert not (a.root/'agent-requests.sqlite3').exists()
    app=create_core_host([a],AuthStore([credential]),origin=ORIGIN)
    with TestClient(app,base_url=ORIGIN):pass


def test_real_fork_lifespan_does_not_unlock_parent_pin(tmp_path):
    import asyncio,os,select,signal
    store,registration,credential,proposal=prepared(tmp_path)
    auth=AuthStore([credential]);app=create_core_host([registration],auth,origin=ORIGIN)
    with TestClient(app,base_url=ORIGIN):
        read,write=os.pipe()
        with auth._lock:
            pid=os.fork()
            if pid==0:
                os.close(read)
                async def foreign():
                    try:
                        async with app.router.lifespan_context(app):pass
                    except PermissionError:return True
                    return False
                try:os.write(write,b'OK' if asyncio.run(foreign()) else b'BAD')
                finally:os._exit(0)
        os.close(write)
        if not select.select([read],[],[],3)[0]:
            os.kill(pid,signal.SIGKILL);os.waitpid(pid,0);os.close(read)
            pytest.fail('owned fork did not reject before inherited Auth lock')
        assert os.read(read,3)==b'OK';os.close(read)
        assert os.waitpid(pid,0)[1]==0
        with pytest.raises(BlockingIOError):create_core_host([registration],auth,origin=ORIGIN)


def test_DB_hardlink_alias_refused_before_owner_or_Store(tmp_path,monkeypatch):
    import os
    store,registration,credential,proposal=prepared(tmp_path)
    os.link(store.db,tmp_path/'alias.db')
    monkeypatch.setattr(Store,'attach_existing',lambda *a,**kw:pytest.fail('aliased DB attached'))
    with pytest.raises(PermissionError):create_core_host([registration],AuthStore([credential]),origin=ORIGIN)
    assert not (registration.root/'runtime/hybrid-core-host.lock').exists()


def test_owner_pin_close_refuses_reused_FD_and_continues_other_pin(tmp_path):
    import os
    from rlflow.hybrid_core_host import _Pins
    for name in ('one','two'):(tmp_path/name/'runtime').mkdir(parents=True,mode=0o700)
    pins=_Pins();pins.acquire(tmp_path/'one');pins.acquire(tmp_path/'two')
    fd=pins.pins[0][0];os.close(fd)
    foreign=os.open(tmp_path/'foreign',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    if foreign!=fd:os.dup2(foreign,fd)
    try:
        with pytest.raises(Conflict):pins.close()
        assert os.fstat(fd).st_ino==(tmp_path/'foreign').stat().st_ino
        assert not pins.closed and pins.closing and len(pins.pins)==1
        other=_Pins();other.acquire(tmp_path/'two');other.close()
    finally:
        os.close(fd)
        if foreign!=fd:os.close(foreign)


def test_partial_pin_close_retains_exact_original_retry(tmp_path,monkeypatch):
    import os
    from rlflow.hybrid_core_host import _Pins
    for name in ('one','two'):(tmp_path/name/'runtime').mkdir(parents=True,mode=0o700)
    pins=_Pins();pins.acquire(tmp_path/'one');pins.acquire(tmp_path/'two')
    blocked=pins.pins[0][0];real=os.close
    with monkeypatch.context() as patch:
        def fail(fd):
            if fd==blocked:raise OSError('synthetic original close failure before actual close')
            real(fd)
        patch.setattr('rlflow.hybrid_core_host.os.close',fail)
        with pytest.raises(Conflict):pins.close()
        assert not pins.closed and len(pins.pins)==1
    pins.close();assert pins.closed


def test_cancelled_shutdown_waiter_keeps_pin_until_real_drain(tmp_path,monkeypatch):
    import asyncio,threading
    from starlette.requests import Request
    from rlflow.hybrid_contract_discovery import ContractDiscovery
    store,registration,credential,proposal=prepared(tmp_path)
    auth=AuthStore([credential]);app=create_core_host([registration],auth,origin=ORIGIN)
    token,_=auth.issue_request_token(Principal('client_agent','agent',{'viewer'},{'project_fixture'}))
    entered=threading.Event();release=threading.Event();real=ContractDiscovery.read
    def held(self,**kw):
        entered.set();assert release.wait(5)
        return real(self,**kw)
    monkeypatch.setattr(ContractDiscovery,'read',held)
    route=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/v1/projects/{project_id}/proposal-contract')
    guard=app.user_middleware[0].kwargs['dispatch']
    request=Request({'type':'http','method':'GET','path':'/api/v1/projects',
        'query_string':b'','headers':[(b'authorization',('Bearer '+token).encode())],'app':app})
    async def exercise():
        context=app.router.lifespan_context(app);await context.__aenter__()
        job=asyncio.create_task(route(request,'project_fixture'))
        try:
            async with asyncio.timeout(3):
                while not entered.is_set():await asyncio.sleep(.01)
            job.cancel();await asyncio.gather(job,return_exceptions=True)
            stopping=asyncio.create_task(context.__aexit__(None,None,None))
            async with asyncio.timeout(3):
                while not hasattr(app.state,'core_host_drain'):await asyncio.sleep(.01)
            stopping.cancel();await asyncio.gather(stopping,return_exceptions=True)
            async def forbidden(_):pytest.fail('closing owner permitted new HTTP')
            assert (await guard(request,forbidden)).status_code==503
            with pytest.raises(PermissionError):
                async with app.router.lifespan_context(app):pass
            with pytest.raises(BlockingIOError):create_core_host([registration],auth,origin=ORIGIN)
            assert not app.state.core_host_drain.done()
        finally:
            release.set()
            async with asyncio.timeout(3):await app.state.core_host_drain
    asyncio.run(exercise())
    next_app=create_core_host([registration],AuthStore([credential]),origin=ORIGIN)
    with TestClient(next_app,base_url=ORIGIN):pass
