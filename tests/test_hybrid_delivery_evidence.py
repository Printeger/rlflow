"""Actual original artifacts/conditions/gaps; no native model or GPU calls."""
from copy import deepcopy
import subprocess
import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_cpu_assessment import fact_key
from rlflow.hybrid_delivery_evidence import DeliveryEvidenceReader
from rlflow.hybrid_goals import SECTIONS as GOALS,digest
from rlflow.hybrid_protocol import validate
from rlflow.web_api import create_app,Project
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start
from tests.test_execution_adapter import setup as native_setup

def execute(client,services,units,headers):
    for service in services:
        response=client.post(path(service)+'/commands',headers=headers,json=start(service))
        assert response.status_code==202,response.text
    return [('CPU_TRIAL',fact_key(units[0]._last['fact']['request'])),
        ('ENGINEERING',units[1]._last['fact']['request']['prior_output_key'])]

def url(service,kind,key):return f'/api/v1/projects/{service.project_id}/delivery-evidence/{kind}/{key}'

def test_actual_both_results_real_condition_denominator_and_no_self_claimed_PASS(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        references=execute(client,services,units,headers)
        assert host.pool.snapshot()['occupied']==0
        versions=[s.store.version() for s in services]
        with monkeypatch.context() as patch:
            patch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('delivery read must not start any worker'))
            for unit,service in zip(units,services):
                for owner,name in ((unit.runtime,'start'),(unit.runtime,'poll'),(service.store,'_commit')):
                    patch.setattr(owner,name,lambda *a,**k:pytest.fail('delivery read must not execute/poll/write'))
            for index,(service,(kind,key)) in enumerate(zip(services,references)):
                response=client.get(url(service,kind,key));assert response.status_code==200,response.text
                body=response.json();context=body['machine_context']
                head=service.store.get(GOALS[1],body['goal_ref'])
                proposal=service.store.get(GOALS[0],head['contract_key'])['contract']['proposal']
                assert body['proposal_sha256']==digest(proposal)
                assert [c['verification'] for c in body['conditions']]==[c['verification'] for c in proposal['global_conditions']]
                assert body['required_count']==sum(c['required'] for c in proposal['global_conditions'])
                assert body['required_count']>0 and body['required_satisfied_count']==0
                assert all(c['status']=='UNASSESSED' and c['condition_evidence_refs']==[] for c in body['conditions'])
                assert 'MISSING_INDEPENDENT_REVIEW' in body['blockers'] and not body['goal_completed']
                assert context['raw_item_count']==(384 if index==0 else 3)
                assert context['machine_status']==('MACHINE_VERIFIED' if index==0 else 'MACHINE_ACCEPTED_PENDING_REVIEW')
                assert context['machine_case_count']==(0 if index==0 else 21)
                assert not any(context['original_model_budget'].values())
                assert context['evidence_role']=='UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE'
                assert context['original_proposal_sha256']==body['proposal_sha256']
                # Two different strings pass the generic structural schema,
                # but are NOT an issued independent Review or acceptance cap.
                fake={'id':'fake_evidence','goal_id':proposal['goal_id'],'condition_id':body['conditions'][0]['id'],
                    'artifact_ids':[key],'candidate_hash':context['candidate_sha256'],
                    'configuration_hash':context['configuration_sha256'],'data_version_hash':'sha256:'+'a'*64,
                    'evaluation_rule_hash':body['conditions'][0]['verification_sha256'],'verifier_version':'self_claim',
                    'implementer_session_id':'different_1','reviewer_session_id':'different_2','verdict':'PASS',
                    'limitations':[],'counter_evidence_ids':[]}
                validate('Evidence',fake)
                assert client.post(url(service,kind,key),headers=headers,json=fake).status_code==405
                assert client.get(url(service,kind,key)+'?verdict=PASS').status_code==400
                for secret in (str(service.store.root),'nonce','producer_identity','lease_id','registry_witness'):
                    assert secret not in response.text
                assert client.get(url(services[1-index],kind,key)).status_code==404
        assert [s.store.version() for s in services]==versions
        print('actual_original_delivery_gaps',dict(cpu_raw=384,engineering_AST=21,real_required_conditions=True,
            fake_SESSION_strings_not_acceptance=True,Goal=False,new_Popen=0,new_writes=0),flush=True)

def test_actual_current_contract_change_old_mapping_never_activates_and_cold_history(application):
    host,units,services,observers,app,token,headers=application
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        references=execute(client,services,units,headers)
        service=services[1];kind,key=references[1]
        before=client.get(url(service,kind,key)).json()
        head=service.store.get(GOALS[1],before['goal_ref'])
        proposal=deepcopy(service.store.get(GOALS[0],head['contract_key'])['contract']['proposal'])
        proposal['contract_version']+=1
        proposal['global_conditions'].append({'id':'new_required_review','description':'Independent milestone review required',
            'required':True,'verification':{'method':'independent_review','rule':'Raw evidence before interpretation',
                'evidence_required':['Actual issued independent readonly Review conclusion']}})
        service.store._hybrid_draft_service.submit(proposal,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,
            idempotency_key='new_contract',expected_revision=head['revision'],expected_state_version=service.store.version())
        response=client.get(url(service,kind,key));assert response.status_code==200,response.text
        changed=response.json();assert changed['contract_revision']==before['contract_revision']+1
        assert changed['required_count']==before['required_count']+1
        assert 'CURRENT_CONTRACT_DIFFERS' in changed['blockers'] and 'CURRENT_CONSENT_UNAVAILABLE' in changed['blockers']
        assert changed['result_activation']=='HISTORICAL_ONLY'
        assert all(not c['machine_context_refs'] for c in changed['conditions'])
        assert changed['machine_context']==before['machine_context']
        assert not changed['goal_completed']
        # Independently attached cold Store/source; no runtime adoption.
        from rlflow.store import Store
        from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
        cold=Store.attach_existing(service.store.root,project_id=service.project_id,data_mode='fixture')
        reader=DeliveryEvidenceReader(CandidateOutputReader(cold,service.runtime.plans.registry,
            project_id=service.project_id,store_epoch=service.store_epoch))
        version=service.store.version()
        for unit in units:unit.runtime.shutdown()
        host.pool.shutdown()
        after=reader.inspect(key)
        assert after['conditions']==changed['conditions'] and after['machine_context']==changed['machine_context']
        assert service.store.version()==version and cold._hybrid_budget_service is None
        print('actual_changed_contract_delivery_block',dict(new_required_condition=True,old_mapping_not_active=True,
            cold_owner_closed_read=True,Goal=False),flush=True)

def test_actual_registry_drift_and_original_head_rollbacks_fail_closed(application):
    import json
    from datetime import datetime,timedelta
    from rlflow.store import Conflict,canonical
    from rlflow.hybrid_registry import Registry
    from rlflow.hybrid_authority import SECTIONS as AUTHORITY
    from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
    host,units,services,observers,app,token,headers=application
    service=services[1];store=service.store
    with TestClient(app,base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session',token)
        response=client.post(path(service)+'/commands',headers=headers,json=start(service))
        assert response.status_code==202,response.text
        key=units[1]._last['fact']['request']['prior_output_key']
        before=client.get(url(service,'ENGINEERING',key)).json()
        # The isolated approval clock is pinned to Oct 9, not wall-clock Oct
        # 10. Historical HTTP must correctly report unavailable today; the
        # positive-current source check uses that original fixture clock.
        from rlflow.hybrid_candidate_output import SECTIONS as OUTPUT
        binding=store.get(OUTPUT[1],key)['sources']
        now=datetime.fromisoformat(binding['evaluated_at'].replace('Z','+00:00'))+timedelta(seconds=1)
        def reader(registry):
            return DeliveryEvidenceReader(CandidateOutputReader(store,registry,project_id=service.project_id,
                store_epoch=service.store_epoch,clock=lambda:now))
        registry=service.runtime.plans.registry
        original=reader(registry)
        assert original.inspect(key)['consent_status']=='CURRENT_AS_OF'
        config=json.loads(registry._raw)
        config['project_policy']['configuration']['delivery_drift']=True
        drift=reader(Registry(config)).inspect(key)
        assert drift['consent_status']=='UNAVAILABLE_AS_OF' and drift['result_activation']=='HISTORICAL_ONLY'
        assert drift['machine_context']==before['machine_context'] and not drift['goal_completed']
        goal=before['goal_ref'];old_authority=store.get(AUTHORITY[2],goal)
        proposal=deepcopy(store.get(GOALS[0],store.get(GOALS[1],goal)['contract_key'])['contract']['proposal'])
        store._hybrid_authority_service.revoke(token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,
            goal_id=proposal['goal_id'],approval_key=old_authority['approval_key'],expected_version=store.version(),
            expected_authority_revision=old_authority['authority_revision'],reason='Actual revoke rollback regression',
            idempotency_key='delivery_revoke')
        revoked=store.get(AUTHORITY[2],goal)
        def replace(section,value):
            # Deliberate projection corruption, not a production mutation or
            # API capability. Original append-only events remain untouched.
            with store.connect() as db:
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',
                    (canonical(value).decode(),section,goal))
        replace(AUTHORITY[2],old_authority)
        with pytest.raises(Conflict,match='not latest original head'):original.inspect(key)
        assert client.get(url(service,'ENGINEERING',key)).status_code==503
        replace(AUTHORITY[2],revoked)
        old_goal=store.get(GOALS[1],goal);proposal['contract_version']+=1
        store._hybrid_draft_service.submit(proposal,token=token,csrf=headers['X-CSRF-Token'],origin=ORIGIN,
            idempotency_key='delivery_v2',expected_revision=old_goal['revision'],expected_state_version=store.version())
        replace(GOALS[1],old_goal)
        with pytest.raises(Conflict,match='not latest original head'):original.inspect(key)
        assert client.get(url(service,'ENGINEERING',key)).status_code==503
        print('actual_delivery_current_proof',dict(Registry_drift_unavailable=True,
            genuine_v1_head_rollback_rejected=True,genuine_approval_after_revoke_rejected=True,Goal=False),flush=True)

def test_latest_head_window_bounds_gaps_and_baseline_are_not_current_proof():
    import sqlite3
    from rlflow.store import Conflict
    from rlflow.hybrid_reads import ReadBudget
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,previous_state_version INTEGER,new_state_version INTEGER,event_type TEXT,idempotency_key TEXT)')
    db.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[(n,n-1,n,'unrelated',f'key_{n}') for n in range(1,258)])
    reader=object.__new__(DeliveryEvidenceReader)
    reader._latest_head(db,ReadBudget(db),GOALS[1],'goal_a',1,257,'key_1')
    with pytest.raises(Conflict,match='window exceeded'):
        reader._latest_head(db,ReadBudget(db),GOALS[1],'goal_a',0,257,None)
    with pytest.raises(Conflict,match='baseline differs'):
        reader._latest_head(db,ReadBudget(db),GOALS[1],'goal_a',2,257,'key_1')
    db.execute('DELETE FROM events WHERE seq=128')
    with pytest.raises(Conflict,match='incomplete'):
        reader._latest_head(db,ReadBudget(db),GOALS[1],'goal_a',1,257,'key_1')
    with pytest.raises(Conflict,match='incomplete'):
        reader._latest_head(db,ReadBudget(db),GOALS[1],'goal_a',257,258,'key_257')
    db.close()

def test_source_conflict_is_preserved_not_reclassified_as_user_value_error(monkeypatch):
    from rlflow.store import Conflict
    reader=object.__new__(DeliveryEvidenceReader)
    def unavailable(self,key):raise Conflict('original head proof unavailable')
    monkeypatch.setattr(DeliveryEvidenceReader,'_inspect',unavailable)
    with pytest.raises(Conflict,match='original head proof unavailable'):reader.inspect('candidate_output_result_a')

@pytest.mark.parametrize('mode',['parse','expand','object','blob','witness','damaged_schema','expired','Registry'])
def test_current_source_budget_and_damage_never_downgrade_to_historical(monkeypatch,mode):
    import sqlite3
    from types import SimpleNamespace
    from datetime import datetime,timezone
    import rlflow.hybrid_delivery_evidence as delivery
    from rlflow.store import Conflict
    from rlflow.hybrid_reads import ReadBudget
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE projection(section TEXT,object_key TEXT,value TEXT)')
    db.execute("INSERT INTO projection VALUES('large','key','12345678901234567890')")
    reader=object.__new__(DeliveryEvidenceReader)
    reader.store=None;reader.source=SimpleNamespace(registry=object())
    reader.project_id='p';reader.data_mode='fixture';reader.store_epoch='e';reader.clock=lambda:datetime.now(timezone.utc)
    read=ReadBudget(db,8);calls=[]
    def load(*args,**kwargs):
        calls.append(True);assert kwargs['_budget'] is read
        if mode=='parse':read.parse(b'"12345678901234567890"')
        if mode=='expand':read.charge(9,1)
        if mode=='object':read.object('large','key')
        raise Conflict({'blob':'Hybrid blob unavailable','witness':'authority source exceeds bounded witness',
            'damaged_schema':'preparation source invalid','expired':'preparation current consent unavailable'}.get(mode,'unexpected'))
    monkeypatch.setattr(delivery,'load_sources',load)
    if mode in ('expired','Registry'):
        assert reader._current_sources(db,read,'goal_a',mode!='Registry') is None
        assert len(calls)==(0 if mode=='Registry' else 1)
    else:
        with pytest.raises(Conflict):reader._current_sources(db,read,'goal_a',True)
        assert calls==[True]
        if mode=='object':assert read.remaining==8  # SQL precheck, not a negative counter.
    db.close()
