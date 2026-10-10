"""A blocked metadata reader cannot consume original physical STOP slots."""
import asyncio
import threading
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from rlflow.hybrid_contract_discovery import ContractDiscovery
from tests.test_hybrid_agent_stop_requests import requested_application
from tests.test_hybrid_finite_host_app import application, ORIGIN
from tests.test_execution_adapter import setup as native_setup


def test_cancelled_discovery_waiters_keep_real_capacity_and_do_not_block_actual_STOP(requested_application,monkeypatch):
    host,units,services,observers,app,token,headers=requested_application
    entered=threading.Event();release=threading.Event();lock=threading.Lock();calls=[]
    original=ContractDiscovery.read
    def held(self,**kw):
        with lock:
            calls.append(True)
            if len(calls)==2:entered.set()
        assert release.wait(5)
        return original(self,**kw)
    monkeypatch.setattr(ContractDiscovery,'read',held)
    route=next(r.endpoint for r in app.routes if getattr(r,'path',None)==
        '/api/v1/projects/{project_id}/proposal-contract')
    req=Request({'type':'http','method':'GET','path':'/proposal-contract','query_string':b'',
        'headers':[(b'cookie',('rlflow_session='+token).encode())],'app':app})
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        async def exercise():
            jobs=[asyncio.create_task(route(req,services[0].project_id)) for _ in range(2)]
            try:
                async with asyncio.timeout(3):
                    while not entered.is_set():await asyncio.sleep(.01)
                for job in jobs:job.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
                refused=await route(req,services[0].project_id)
                assert refused.status_code==429  # Actual readers still running.
                # This is the original live HTTP STOP with actual leases,
                # not a mock cancellation callback or metadata boolean.
                reply=client.post('/api/v1/finite-host/commands',headers={**headers,
                    'Idempotency-Key':'during_discovery'},json={'action':'CANCEL_ORIGINAL_FINITE_UNITS'})
                assert reply.status_code==202,reply.text
                assert reply.json()['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
                assert all(u._cancelled.is_set() for u in units) and host.pool.snapshot()['occupied']==0
            finally:
                release.set()
                async with asyncio.timeout(3):
                    while True:
                        ready=await route(req,services[0].project_id)
                        if type(ready) is dict:
                            assert ready['authority']=='NOT_AUTHORITY'
                            break
                        assert ready.status_code==429
                        await asyncio.sleep(.01)
        asyncio.run(exercise())
        assert len(calls)>=3 and app.state.finite_host_stop_pool.pending==0
    print('actual_discovery_STOP_isolation',{'cancelled_waiter_capacity_retained':True,
        'original_STOP_scopes':2,'pool_occupied':0},flush=True)
