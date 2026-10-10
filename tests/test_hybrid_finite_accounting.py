"""Original finite accounting source, no worker execution or settlement."""
import asyncio
import copy
from contextlib import contextmanager, closing
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.test_hybrid_finite_host_app import application, ORIGIN, path, stop
from tests.test_execution_adapter import setup as native_setup
from rlflow.hybrid_budget import account_key
from rlflow.hybrid_budget_ledger import SECTIONS
from rlflow.web_auth import Principal


def endpoint(service):
    return f'/api/v1/projects/{service.project_id}/finite-accounting'


@contextmanager
def damaged(store, section, key):
    with store.connect() as db:
        raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,key)).fetchone()[0]
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',('{}',section,key));db.commit()
    try: yield
    finally:
        with store.connect() as db:
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,section,key));db.commit()


def test_original_read_proofs_exact_balances_privacy_damage_and_rebinding(application,monkeypatch):
    host,units,services,_,app,token,headers=application
    source=app.state.finite_accounting_source
    audits=[s.store.audit() for s in services];pool_before=host.pool.snapshot()
    cs,es=services
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get(endpoint(cs)).status_code==401
        client.cookies.set('rlflow_session',token)
        assert client.get(endpoint(cs)+'?root=foreign').status_code==400
        for s in services:
            response=client.get(endpoint(s));assert response.status_code==200,response.text
            result=response.json();assert result['pool']['occupied']==2 and result['pool']['project_occupied']==1
            assert not result['cross_database_atomic'] and not result['goal_completed']
            original=s.store.objects(SECTIONS[1])[0][1]
            assert result['budget']['balances']=={n:{k:str(v) for k,v in r.items()} for n,r in original['balance'].items()}
            assert result['budget']['actual_cost_status']=='UNKNOWN'
            assert 'store_root' not in response.text and 'claim_key' not in response.text and 'member_id' not in response.text
        # A readonly token for one project sees no global activity, including
        # the other project's later FREE/historical membership.
        viewer,_=cs.auth.issue_bearer(Principal('only_cpu','agent',{'viewer'},{cs.project_id}))
        restricted={'Authorization':'Bearer '+viewer}
        value=client.get(endpoint(cs),headers=restricted).json()
        assert value['pool']['occupied'] is None and value['pool']['coverage']=='PROJECT_ONLY'
        assert client.get(endpoint(es),headers=restricted).status_code==404
        key=account_key(source._scopes[cs.project_id])
        for section,selector in ((SECTIONS[1],key),(SECTIONS[2],cs.reservation_id)):
            with damaged(cs.store,section,selector):
                assert client.get(endpoint(cs)).status_code==503
            assert client.get(endpoint(cs)).status_code==200
        # Detect mutable SAME Store/reader rebinding before any new DB access.
        with monkeypatch.context() as patch:
            patch.setattr(cs.store,'root',es.store.root)
            patch.setattr(cs.store,'db',es.store.db)
            patch.setattr(cs.store,'read_connection',lambda:pytest.fail('rebound source performed IO'))
            assert client.get(endpoint(cs)).status_code==403
        with monkeypatch.context() as patch:
            patch.setattr(cs,'_registration',copy.deepcopy(es._registration))
            assert client.get(endpoint(cs)).status_code==403
        # A malformed original Pool head is not a fabricated zero.
        with host.pool._transaction() as db:
            raw=db.execute('SELECT raw FROM heads WHERE slot=0').fetchone()[0]
        # Test-only corruption must not use protected transaction final proofs.
        import sqlite3
        with closing(sqlite3.connect(host.pool.root/'pool.db')) as db:
            db.execute("UPDATE heads SET raw='null' WHERE slot=0")
            db.commit()
        try: assert client.get(endpoint(cs)).status_code==503
        finally:
            with closing(sqlite3.connect(host.pool.root/'pool.db')) as db:
                db.execute('UPDATE heads SET raw=? WHERE slot=0',(raw,))
                db.commit()
        assert [s.store.audit() for s in services]==audits and host.pool.snapshot()==pool_before
        # No worker needed: original untouched engineering scope closes through
        # the original STOP API. A historical member still requires permission.
        stopped=client.post(path(es)+'/commands',headers={**headers,'Idempotency-Key':'accounting_stop'},json=stop(es))
        assert stopped.status_code==202,stopped.text
        result=client.get(endpoint(cs),headers=restricted).json()
        assert result['pool']['project_occupied']==1 and result['pool']['occupied'] is None
        assert client.get(endpoint(cs)).json()['pool']['occupied']==1


def test_real_read_futures_hold_capacity_cancel_waiters_and_STOP_independent(application,monkeypatch):
    _,units,services,_,app,token,headers=application
    source=app.state.finite_accounting_source;gate=threading.Event();entered=threading.Event();count=[0]
    original=source._budget
    def held(service):
        count[0]+=1
        if count[0]==2:entered.set()
        assert gate.wait(12)
        return original(service)
    monkeypatch.setattr(source,'_budget',held)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,cookies={'rlflow_session':token}) as client:
                tasks=[asyncio.create_task(client.get(endpoint(services[0]))) for _ in range(2)]
                try:
                    assert await asyncio.to_thread(entered.wait,4)
                    for t in tasks:t.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
                    assert app.state.finite_accounting_pool.pending==2
                    assert (await client.get(endpoint(services[0]))).status_code==429
                    stopped=await asyncio.wait_for(client.post(path(services[0])+'/commands',headers=headers,json=stop(services[0])),5)
                    assert stopped.status_code==202 and units[0]._cancelled.is_set()
                    services[0].auth.revoke(token)  # Read-after-auth fence will reject eventual responses.
                    gate.set()
                    for _ in range(200):
                        if app.state.finite_accounting_pool.pending==0:break
                        await asyncio.sleep(.01)
                    assert app.state.finite_accounting_pool.pending==0
                    assert (await client.get(endpoint(services[0]))).status_code==401
                    new_token,_=services[0].auth.login('fixture_human','Working plan isolated synthetic fixture passphrase')
                    client.cookies.set('rlflow_session',new_token)
                    gate.clear();entered.clear();count[0]=1
                    late=asyncio.create_task(client.get(endpoint(services[0])))
                    assert await asyncio.to_thread(entered.wait,4)
                    services[0].auth.revoke(new_token);gate.set()
                    assert (await late).status_code==401
                finally:
                    gate.set()
                    for t in tasks:t.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(scenario())
    assert app.state.finite_accounting_pool.closed


def test_project_only_hides_global_version_even_when_other_scope_frees(application):
    host,_,services,_,app,token,headers=application
    cs,es=services
    viewer,_=cs.auth.issue_bearer(Principal('only_cpu','agent',{'viewer'},{cs.project_id}))
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        restricted={'Authorization':'Bearer '+viewer}
        before=client.get(endpoint(cs),headers=restricted).json()
        global_before=client.get(endpoint(cs)).json()['pool']['as_of_pool_version']
        assert before['pool']['occupied'] is None and before['pool']['as_of_pool_version'] is None
        stopped=client.post(path(es)+'/commands',headers={**headers,'Idempotency-Key':'privacy_stop'},json=stop(es))
        assert stopped.status_code==202
        after=client.get(endpoint(cs),headers=restricted).json()
        global_after=client.get(endpoint(cs)).json()['pool']['as_of_pool_version']
        assert global_after>global_before and host.pool.snapshot()['occupied']==1
        assert after['pool']['occupied'] is None and after['pool']['as_of_pool_version'] is None
        assert after['pool']['project_occupied']==before['pool']['project_occupied']==1
        assert after['budget']['balances']==before['budget']['balances']
        assert after['as_of_state_version']==before['as_of_state_version']
