"""Original finite execution -> request-only target client -> honest report."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import pytest
import uvicorn
from fastapi.testclient import TestClient
from rlflow.agent_client import AgentClient,ClientError
from rlflow.hybrid_client_execution_report import ExecutionReport,validate_public
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.web_auth import Principal
from tests.test_agent_client import config
from tests.test_contract_discovery import discovery_setup
from tests.test_hybrid_agent_stop_requests import requested_application
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start
from tests.test_execution_adapter import setup as native_setup

REAL_RUN=subprocess.run
REAL_POPEN=subprocess.Popen


def test_unsupported_report_does_not_invent_runtime(tmp_path):
    store,auth,pair,inbox,agent,app,mono=discovery_setup(tmp_path)
    before=store.audit()
    with TestClient(app,base_url=ORIGIN) as client:
        response=client.get('/api/v1/projects/project_fixture/execution-report/CPU_TRIAL/cpu_assessment_absent',
            headers={'Authorization':'Bearer '+agent})
        assert response.status_code==409 and response.json()['code']=='UNSUPPORTED_CAPABILITY'
        assert store.audit()==before


def test_actual_dual_execution_target_client_report_and_original_STOP(requested_application,tmp_path,monkeypatch):
    host,units,services,observers,app,human,headers=requested_application
    agent,_=services[0].auth.issue_request_token(Principal('report_agent','agent',{'viewer'},
        {s.project_id for s in services}),ttl=120)
    limited,_=services[0].auth.issue_request_token(Principal('limited_report','agent',{'viewer'},
        {services[0].project_id}),ttl=120)
    reports=[]
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',human)
        for s in services:
            reply=client.post(path(s)+'/commands',headers=headers,json=start(s))
            assert reply.status_code==202,reply.text
        assert host.pool.snapshot()['occupied']==0
        for i,s in enumerate(services):
            kind='CPU_TRIAL' if i==0 else 'ENGINEERING'
            reader=(CpuAssessmentReader if i==0 else CandidateOutputReader)(s.store,s.runtime.plans.registry,
                project_id=s.project_id,store_epoch=s.store_epoch)
            rows=(reader.assessments() if i==0 else reader.outputs())['items']
            source=rows[0]['id']
            url=f'/api/v1/projects/{s.project_id}/execution-report/{kind}/{source}'
            before=s.store.audit()
            response=client.get(url,headers={'Authorization':'Bearer '+agent})
            assert response.status_code==200,response.text
            value=response.json();validate_public(value,s.project_id,kind,source)
            assert value['source']['raw_item_count']==(384 if i==0 else 3)
            assert value['source']['machine_case_count']==(0 if i==0 else 21)
            assert not value['goal_completed'] and not value['dispatch_enabled']
            assert value['required_count']>0 and value['required_satisfied_count']==0
            assert 'MISSING_INDEPENDENT_REVIEW' in value['blockers']
            assert value['current_execution_status']=='UNKNOWN' and value['resource_release_status']=='NOT_OBSERVED'
            assert s.store.audit()==before
            reports.append((kind,source,value))
            if i==1:
                assert client.get(url,headers={'Authorization':'Bearer '+limited}).status_code==404
                assert client.get(url+'?run=true',headers={'Authorization':'Bearer '+agent}).status_code==400
        # SDK/CLI reads below use real loopback HTTP, not an opener stub.
        sock=socket.socket();sock.bind(('127.0.0.1',8765))
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,lifespan='off'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            deadline=time.monotonic()+5
            while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
            assert server.started
            for i,s in enumerate(services):
                parent=tmp_path/('client_'+str(i));parent.mkdir()
                target=config(parent,ORIGIN,project=s.project_id)
                env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(Path(__file__).resolve().parents[1]),
                    'RLFLOW_CONTROL_ORIGIN':ORIGIN,'RLFLOW_REQUEST_TOKEN':agent}
                kind,source,value=reports[i]
                actual=AgentClient(cwd=target,environ=env).execution_report(kind,source)
                assert actual['source']==value['source']
                with monkeypatch.context() as patch:
                    patch.setattr(subprocess,'Popen',REAL_POPEN);patch.setattr(subprocess,'run',REAL_RUN)
                    call=subprocess.run([sys.executable,'-m','rlflow.cli','client','execution-report','--kind',kind,
                        '--source',source],cwd=target,env=env,capture_output=True,text=True,timeout=10)
                assert call.returncode==0,call.stderr
                assert json.loads(call.stdout)['source']==value['source'] and agent not in call.stdout+call.stderr
        finally:
            server.should_exit=True;thread.join(5);sock.close();assert not thread.is_alive()
        # Original coordinator remains the sole physical cleanup owner.
        reply=client.post('/api/v1/finite-host/commands',headers={**headers,'Idempotency-Key':'after_reports'},
            json={'action':'CANCEL_ORIGINAL_FINITE_UNITS'})
        assert reply.status_code==202 and reply.json()['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
        assert host.pool.snapshot()['occupied']==0 and all(u._cancelled.is_set() for u in units)
    print('actual_client_execution_reports',{'CPU_raw':384,'engineering_cases':21,'reports':2,
        'report_Core_writes':0,'independent_review':'NOT_PERFORMED','Goal_completed':False,'original_STOP':True},flush=True)
