"""Actual source corruption and late revocation; independent original STOP."""
import asyncio
import json
import threading
from fastapi.testclient import TestClient
from starlette.requests import Request
from rlflow.hybrid_client_execution_report import ExecutionReport
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.hybrid_delivery_evidence import DeliveryEvidenceReader
from rlflow.hybrid_cpu_assessment import SECTION
from rlflow.web_auth import Principal
from tests.test_hybrid_agent_stop_requests import requested_application
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start
from tests.test_execution_adapter import setup as native_setup


def test_actual_source_damage_late_revocation_and_report_pool_STOP(requested_application,monkeypatch):
    host,units,services,observers,app,human,headers=requested_application
    s=services[0];auth=s.auth
    agent,_=auth.issue_request_token(Principal('guard_report_agent','agent',{'viewer'},{s.project_id}),ttl=120)
    late,_=auth.issue_request_token(Principal('late_report_agent','agent',{'viewer'},{s.project_id}),ttl=120)
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',human)
        assert client.post(path(s)+'/commands',headers=headers,json=start(s)).status_code==202
        reader=CpuAssessmentReader(s.store,s.runtime.plans.registry,project_id=s.project_id,store_epoch=s.store_epoch)
        key=reader.assessments()['items'][0]['id']
        base=f'/api/v1/projects/{s.project_id}/execution-report/CPU_TRIAL/'
        reqheaders={'Authorization':'Bearer '+agent}
        assert client.get(base+'cpu_assessment_absent',headers=reqheaders).status_code==404
        original=DeliveryEvidenceReader.inspect
        def revoked(self,key):
            value=original(self,key);auth.revoke(late);return value
        with monkeypatch.context() as patch:
            patch.setattr(DeliveryEvidenceReader,'inspect',revoked)
            response=client.get(base+key,headers={'Authorization':'Bearer '+late})
            assert response.status_code==403 and 'machine_status' not in response.text
        # Actual accepted projection changed without its original event proof.
        with s.store.connect() as db:
            raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(SECTION,key)).fetchone()[0]
            changed=json.loads(raw);changed['result_hash']='sha256:'+'f'*64
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(json.dumps(changed),SECTION,key));db.commit()
        try:
            response=client.get(base+key,headers=reqheaders)
            assert response.status_code==503 and 'machine_status' not in response.text
        finally:
            with s.store.connect() as db:
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,SECTION,key));db.commit()
        assert client.get(base+key,headers=reqheaders).status_code==200
        entered=threading.Event();release=threading.Event();lock=threading.Lock();calls=[]
        original_read=ExecutionReport.read
        def held(self,key,**kw):
            with lock:
                calls.append(True)
                if len(calls)==2:entered.set()
            assert release.wait(8)
            return original_read(self,key,**kw)
        route=next(r.endpoint for r in app.routes if getattr(r,'path',None)==
            '/api/v1/projects/{project_id}/execution-report/{kind}/{source_id}')
        req=Request({'type':'http','method':'GET','path':base+key,'query_string':b'',
            'headers':[(b'authorization',('Bearer '+agent).encode())],'app':app})
        async def exercise():
            jobs=[asyncio.create_task(route(req,s.project_id,'CPU_TRIAL',key)) for _ in range(2)]
            try:
                async with asyncio.timeout(3):
                    while not entered.is_set():await asyncio.sleep(.01)
                for job in jobs:job.cancel()
                await asyncio.gather(*jobs,return_exceptions=True)
                assert (await route(req,s.project_id,'CPU_TRIAL',key)).status_code==429
                response=client.post('/api/v1/finite-host/commands',headers={**headers,'Idempotency-Key':'held_report_stop'},
                    json={'action':'CANCEL_ORIGINAL_FINITE_UNITS'})
                assert response.status_code==202 and response.json()['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
                assert host.pool.snapshot()['occupied']==0 and all(u._cancelled.is_set() for u in units)
            finally:
                release.set()
                async with asyncio.timeout(5):
                    while True:
                        ready=await route(req,s.project_id,'CPU_TRIAL',key)
                        if type(ready) is dict:break
                        assert ready.status_code==429
                        await asyncio.sleep(.01)
        with monkeypatch.context() as patch:
            patch.setattr(ExecutionReport,'read',held);asyncio.run(exercise())
    print('actual_report_guards',{'source_damage':503,'late_revoke':403,'missing':404,
        'cancelled_capacity_retained':True,'original_STOP':True,'pool_occupied':0},flush=True)
