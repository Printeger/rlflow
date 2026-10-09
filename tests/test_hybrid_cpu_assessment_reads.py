"""Real raw result through opt-in viewer API and cold no-owner read storage."""
from datetime import timedelta
import json
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_cpu_assessment import SECTION,fact_key
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.store import Store,Conflict,canonical
from rlflow.web_api import Project,create_app
from rlflow.web_auth import AuthStore,Credential,Principal
from tests.test_hybrid_cpu_trial_runtime import trial_runtime,grant_and_lease
from tests.test_execution_adapter import setup as native_setup

ORIGIN='http://127.0.0.1:8765'
PHRASE='Isolated synthetic original CPU evidence viewer passphrase'


def setup(context,*,actual=False,origin=ORIGIN):
    owner,_,token,_,_,_,utc,_=context;_,lease=grant_and_lease(context)
    if actual:owner.run_cpu_trial(lease)
    else:owner.stop_to_terminal(lease)
    service=CpuAssessmentService(owner)
    accepted=service.assess(lease,token,idempotency_key='first',expected_state_version=owner.store.version())
    key=fact_key(accepted['fact']['request'])
    cold=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    reader=CpuAssessmentReader(cold,owner.plans.registry,project_id=owner.workspace.project_id,
        store_epoch=owner.workspace.store_epoch,clock=lambda:utc[0])
    viewer=Principal('viewer','human',{'viewer'},{reader.project_id})
    other=Principal('other','human',{'viewer'},{'another_project'})
    auth=AuthStore([Credential.create(p,PHRASE) for p in (viewer,other)])
    app=create_app([Project(reader.project_id,str(cold.root),'fixture')],auth,origin=origin,cpu_assessment_readers={reader.project_id:reader})
    bearer,_=auth.issue_bearer(viewer)
    return owner,lease,service,reader,app,auth,{'Authorization':'Bearer '+bearer},'/api/v1/projects/'+reader.project_id+'/cpu-trial-assessments',key


def test_actual_sealed_raw_evidence_cold_viewer_HTTP_and_no_runtime_side_effects(trial_runtime,monkeypatch):
    owner,lease,service,reader,app,auth,headers,base,key=setup(trial_runtime,actual=True)
    before=owner.store.version();original=owner._issued(lease)['origin']
    assert reader.store._hybrid_budget_service is None and reader.store._hybrid_cpu_assessment_service is None
    with monkeypatch.context() as patch:
        for obj,name in ((owner,'start'),(owner,'poll'),(owner,'collect_cpu_trial'),(owner.sources,'poll'),(owner.store,'_commit')):
            patch.setattr(obj,name,lambda *a,**k:pytest.fail('GET must not write, execute, collect or poll'))
        with TestClient(app,base_url=ORIGIN) as client:
            page=client.get(base,headers=headers);assert page.status_code==200 and len(page.json()['items'])==1
            response=client.get(base+'/'+key,headers=headers);assert response.status_code==200
            body=response.json();row=body['experiment']; evidence=row['evidence']
            assert row['assessment']['scientific_validity']=='VALID' and row['assessment']['next_action']=='REQUEST_INDEPENDENT_REVIEW'
            assert row['current_activation']=='EXPERIMENT_CURRENT_AS_OF' and not row['goal_completed']
            assert row['assessment']['condition_coverage']==[] and not row['controls_available']
            assert row['current_execution_status']=='UNKNOWN' and row['resource_release_status']=='NOT_OBSERVED'
            assert sum(len(r['points']) for r in evidence['raw_samples'])==384
            assert evidence['inside_counts']==[96,101,104] and evidence['mean_absolute_error']==0.08821911547006896
            assert evidence['resource_enforcement']=='partial'
            for secret in (str(owner.store.root),original['nonce'],'boot_id','producer','lease_id','registry_witness','pool_free'):
                assert secret not in response.text
            assert client.post(base+'/'+key,headers=headers,json={'action':'start'}).status_code==405
        assert owner.store.version()==before
    # The readonly cold reader remains useful after all original execution owners close.
    owner.shutdown();owner.pool.shutdown()
    assert reader.assessment(key)['experiment']['evidence']['inside_counts']==[96,101,104]
    assert owner.store.version()==before


def test_query_auth_default_off_pagination_and_read_during_revocation(trial_runtime,monkeypatch):
    owner,lease,service,reader,app,auth,headers,base,key=setup(trial_runtime)
    before=owner.store.version()
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get(base).status_code==401
        other,_=auth.issue_bearer(Principal('outsider','human',{'viewer'},{'another_project'}))
        assert client.get(base,headers={'Authorization':'Bearer '+other}).status_code==404
        for query in ('?limit=0','?limit=6','?limit=01','?limit=1&limit=2','?after=../bad','?path=/tmp/private','?poll=1'):
            assert client.get(base+query,headers=headers).status_code==400
        assert client.get(base+'/missing',headers=headers).status_code==404
        assert client.get(base+'/'+key+'?raw=/tmp/private',headers=headers).status_code==400
        assert client.get(base,headers={**headers,'Origin':'https://other.invalid'}).status_code==403
        read=reader.assessment
        def revoke_after_read(*args):
            value=read(*args);auth.revoke(headers['Authorization'].split(' ',1)[1]);return value
        patch=monkeypatch.context()
        with patch as patcher:
            patcher.setattr(reader,'assessment',revoke_after_read)
            assert client.get(base+'/'+key,headers=headers).status_code==401
    assert owner.store.version()==before
    disabled=create_app([Project(reader.project_id,str(reader.store.root),'fixture')],auth,origin=ORIGIN)
    with TestClient(disabled,base_url=ORIGIN) as client:assert client.get(base).status_code==404
    second=service.assess(lease,trial_runtime[2],idempotency_key='second',expected_state_version=owner.store.version())
    first_page=reader.assessments(limit=1);assert len(first_page['items'])==1 and first_page['next_after']
    next_page=reader.assessments(after=first_page['next_after'],limit=1)
    assert len(next_page['items'])==1 and next_page['next_after'] is None
    assert {first_page['items'][0]['id'],next_page['items'][0]['id']}=={key,fact_key(second['fact']['request'])}


def test_source_corruption_and_final_after_IO_expiry_are_not_fake_empty_or_current(trial_runtime,monkeypatch):
    owner,lease,service,reader,app,auth,headers,base,key=setup(trial_runtime)
    activation=reader._activation
    def expires_after_proof(*args):
        result=activation(*args);trial_runtime[6][0]+=timedelta(seconds=120);trial_runtime[7][0]+=120*10**9;return result
    with monkeypatch.context() as patch:
        patch.setattr(reader,'_activation',expires_after_proof)
        assert reader.assessment(key)['experiment']['current_activation']=='HISTORICAL_ONLY'
    with owner.store.connect() as db:
        raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(SECTION,key)).fetchone()[0]
        value=json.loads(raw);value['assessment']['scientific_validity']='VALID'
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(value).decode(),SECTION,key))
    with TestClient(app,base_url=ORIGIN) as client:assert client.get(base+'/'+key,headers=headers).status_code==503
    with owner.store.connect() as db:
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,SECTION,key))
        db.execute('DELETE FROM projection WHERE section=? AND object_key=?',(SECTION,key))
    with pytest.raises(Conflict,match='missing original'):reader.assessments()
    with TestClient(app,base_url=ORIGIN) as client:assert client.get(base+'/'+key,headers=headers).status_code==503
    with owner.store.connect() as db:
        owner.store._replace_projection(db,owner.store.audit(db))
    assert reader.assessment(key)['experiment']['current_activation']=='HISTORICAL_ONLY'


def test_actual_loopback_socket_reads_original_appraisal_without_any_control(trial_runtime):
    import uvicorn
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    origin='http://127.0.0.1:'+str(port)
    owner,lease,service,reader,app,auth,headers,base,key=setup(trial_runtime,origin=origin)
    before=owner.store.version()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:pytest.fail('original loopback server did not start')
            time.sleep(.01)
        with httpx.Client(base_url=origin,headers=headers,timeout=5) as client:
            assert client.get(base).status_code==200
            result=client.get(base+'/'+key);assert result.status_code==200
            assert result.json()['experiment']['assessment']['execution_status']=='NOT_EXECUTED'
            assert result.json()['experiment']['evidence'] is None
            assert client.post(base+'/'+key,json={'action':'dispatch'}).status_code==405
        assert owner.store.version()==before and not owner._issued(lease)['spawn_entered']
    finally:
        server.should_exit=True;thread.join(5);sock.close()
        assert not thread.is_alive()


def test_corrupt_projection_version_and_startup_epoch_are_not_historical_success(trial_runtime):
    owner,lease,service,reader,app,auth,headers,base,key=setup(trial_runtime)
    before=owner.store.version()
    with owner.store.connect() as db:db.execute('UPDATE projection_meta SET version=?',(before+1,))
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get(base,headers=headers).status_code==503
        assert client.get(base+'/'+key,headers=headers).status_code==503
    with owner.store.connect() as db:db.execute('UPDATE projection_meta SET version=?',(before,))
    assert reader.assessment(key)['experiment']['current_activation']=='EXPERIMENT_CURRENT_AS_OF'
    wrong=CpuAssessmentReader(reader.store,reader.registry,project_id=reader.project_id,store_epoch='different_epoch',clock=reader.clock)
    with pytest.raises(Conflict):create_app([Project(reader.project_id,str(reader.store.root),'fixture')],auth,origin=ORIGIN,
        cpu_assessment_readers={reader.project_id:wrong})
    assert owner.store.version()==before
