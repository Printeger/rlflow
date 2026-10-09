"""Cold arithmetic, immutable decisions, no Reviewer/Goal permission upgrade."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest
from rlflow.hybrid_cpu_cold_verifier import derive,SPEC,verify
from rlflow.hybrid_cpu_trial import inputs
from rlflow.hybrid_cpu_assessment import SECTION,EVENT,fact_key
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.store import Store,Conflict,canonical
from tests.test_hybrid_cpu_trial_runtime import trial_runtime,grant_and_lease
from tests.test_execution_adapter import setup as native_setup


def test_cold_raw_derivation_is_independent_of_explanation_and_rejects_counterfeit():
    raw=inputs();derived=derive(SPEC,raw)
    assert derived['inside_counts']==[96,101,104] and derived['mean_absolute_error']==0.08821911547006896
    # No producer metrics/assessment/conversation can enter the stage-one API.
    with pytest.raises(TypeError):derive(SPEC,raw,{'hypothesis_outcome':'REFUTED'})
    for changed in [raw[:2],raw+[raw[0]],[*raw[:2],raw[0]]]:
        with pytest.raises(Conflict):derive(SPEC,changed)
    changed=deepcopy(raw);changed[0]['points'][0][0]+=1
    with pytest.raises(Conflict,match='sequence'):derive(SPEC,changed)
    changed=deepcopy(raw);changed[0]['points'][0][0]=True
    with pytest.raises(Conflict,match='integer'):derive(SPEC,changed)
    with pytest.raises(Conflict):derive({**SPEC,'baseline':4},raw)
    wrong={'raw_samples':raw,'input_sha256':derived['raw_sha256'],**{k:v for k,v in derived.items() if k not in ('raw_sha256','spec_sha256')},'source_sha256':'sha256:'+'a'*64}
    wrong['hypothesis_supported']=False
    with pytest.raises(Conflict,match='metrics'):verify(wrong)


def test_actual_CPU_cold_decision_persist_original_proofs_recovery_and_no_repeat(trial_runtime,monkeypatch):
    owner,_,token,_,_,_,utc,mono=trial_runtime;_,lease=grant_and_lease(trial_runtime)
    owner.run_cpu_trial(lease);service=CpuAssessmentService(owner)
    appraisal=service.assess(lease,token,idempotency_key='appraisal',expected_state_version=owner.store.version())
    pk=fact_key(appraisal['fact']['request']);before=owner.store.version()
    args={'assessment_key':pk,'idempotency_key':'cold_decision','expected_state_version':before}
    accepted=service.decide(lease,token,**args);value=accepted['fact'];key=fact_key(value['request'])
    assert owner.store.version()==before+1
    machine=value['machine_verification'];assert machine['status']=='MACHINE_VERIFIED'
    assert machine['derived']['inside_counts']==[96,101,104]
    assert machine['next_action']=='REQUEST_INDEPENDENT_REVIEW'
    assert machine['independent_review_status']=='NOT_PERFORMED' and machine['condition_coverage']==[]
    assert not machine['goal_completed'] and not machine['dispatch_enabled']
    with monkeypatch.context() as patch:
        patch.setattr(owner,'run_cpu_trial',lambda *a:pytest.fail('no new computation'))
        duplicate=service.decide(lease,token,**args);assert duplicate['duplicate'] and duplicate['current_activation']=='NOT_RECHECKED'
    state=owner.store.audit();assert owner.store.replay()==state
    from rlflow.hybrid_cpu_assessment import validate_links
    from rlflow.hybrid_goals import digest
    future=deepcopy(state[SECTION][pk]);future['recorded_at']=future['sources']['evaluated_at']='2026-10-09T00:00:01Z'
    altered=deepcopy(value);altered['prior_assessment_hash']=digest(future)
    with pytest.raises(Conflict,match='appraisal binding'):
        validate_links(altered,lambda s,k:future if (s,k)==(SECTION,pk) else state.get(s,{}).get(k))
    owner.store.snapshot();assert owner.store.recover()==state
    cold=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    reader=CpuAssessmentReader(cold,owner.plans.registry,project_id=owner.workspace.project_id,store_epoch=owner.workspace.store_epoch,clock=lambda:utc[0])
    assert reader.assessment(key)['experiment']['assessment']['independent_review_status']=='NOT_PERFORMED'
    assert service.inspect(key)['fact']['machine_verification']==machine
    with pytest.raises(Conflict,match='plain'):service.decide(lease,token,assessment_key=key,idempotency_key='nested',expected_state_version=owner.store.version())
    with pytest.raises(PermissionError):owner.store.transact(EVENT,'forged',lambda s:None)
    with owner.store.connect() as db:
        raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(SECTION,pk)).fetchone()[0]
        broken=json.loads(raw);broken['assessment']['hypothesis_outcome']='REFUTED'
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(broken).decode(),SECTION,pk))
    with pytest.raises(Conflict):service.inspect(key)
    with pytest.raises(Conflict):reader.assessment(key)
    with owner.store.connect() as db:db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,SECTION,pk))
    utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
    assert service.inspect(key)['current_activation']=='HISTORICAL_ONLY'
    assert reader.assessment(key)['experiment']['current_activation']=='HISTORICAL_ONLY'
    assert owner.store.version()==before+1 and owner.pool.snapshot()['occupied']==0


def test_no_G_cold_decision_is_unavailable_and_no_automatic_retry(trial_runtime):
    owner,_,token,*_=trial_runtime;_,lease=grant_and_lease(trial_runtime);owner.stop_to_terminal(lease)
    service=CpuAssessmentService(owner);appraisal=service.assess(lease,token,idempotency_key='plain',expected_state_version=owner.store.version())
    accepted=service.decide(lease,token,assessment_key=fact_key(appraisal['fact']['request']),idempotency_key='unavailable',expected_state_version=owner.store.version())
    v=accepted['fact']['machine_verification'];assert v['status']=='UNAVAILABLE' and v['derived'] is None
    assert v['next_action']=='NO_AUTOMATIC_RETRY' and not v['goal_completed']
    assert not owner._issued(lease)['spawn_entered'] and owner.store.audit()==owner.store.replay()


def test_decision_lost_COMMIT_snapshot_historical_code_identity_types_and_final_TTL(trial_runtime,monkeypatch):
    from rlflow import hybrid_cpu_cold_verifier as verifier
    from rlflow.hybrid_cpu_assessment import validate_record,validate_links
    from rlflow.snapshot_maintenance import maintain
    owner,_,token,_,_,_,utc,mono=trial_runtime;_,lease=grant_and_lease(trial_runtime);owner.stop_to_terminal(lease)
    service=CpuAssessmentService(owner);store=owner.store
    original=service.assess(lease,token,idempotency_key='plain',expected_state_version=store.version())
    pk=fact_key(original['fact']['request']);args={'assessment_key':pk,'idempotency_key':'lost','expected_state_version':store.version()}
    connect=store.connect
    class LostReturn:
        def __init__(self,db):self.db=db
        def __getattr__(self,n):return getattr(self.db,n)
        def commit(self):self.db.commit();raise OSError('actual cold decision COMMIT lost receipt')
        def __enter__(self):return self
        def __exit__(self,*a):return self.db.__exit__(*a)
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',lambda:LostReturn(connect()))
        with pytest.raises(OSError,match='lost receipt'):service.decide(lease,token,**args)
    version=store.version();accepted=service.decide(lease,token,**args);value=accepted['fact'];key=fact_key(value['request'])
    assert accepted['duplicate'] and store.version()==version
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(version,))
    assert maintain(store,seconds=30);state=store.audit();assert store.recover()==state
    # History must survive a later source implementation identity and perform no file IO.
    with monkeypatch.context() as patch:
        patch.setattr(verifier,'implementation_hash',lambda:pytest.fail('historical verification cannot read today source'))
        assert store.audit()==state and store.recover()==state and service.inspect(key)['fact']==value
    for field in ('goal_completed','dispatch_enabled'):
        forged=deepcopy(value);forged['machine_verification'][field]=0
        with pytest.raises((Conflict,ValueError)):validate_record(key,forged)
    forged=deepcopy(value);forged['machine_verification']['extra']='unsafe'
    with pytest.raises(ValueError):validate_record(key,forged)
    with monkeypatch.context() as patch:
        patch.setattr(verifier,'implementation_hash',lambda:'sha256:'+'e'*64)
        with pytest.raises(Conflict,match='implementation'):service.decide(lease,token,assessment_key=pk,idempotency_key='changed_code',expected_state_version=version)
    assert store.version()==version
    # Fresh proof may expire before final writer gate; no decision is appended.
    dependencies=service._dependencies
    def expire_after_proof(*a):
        result=dependencies(*a)
        if 'machine_verification' in a[1]:utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
        return result
    with monkeypatch.context() as patch:
        patch.setattr(service,'_dependencies',expire_after_proof)
        with pytest.raises(Conflict):service.decide(lease,token,assessment_key=pk,idempotency_key='expired',expected_state_version=version)
    assert store.version()==version and service.inspect(key)['current_activation']=='HISTORICAL_ONLY'


def test_decide_rejects_missing_original_and_closed_machine_integer_float_confusion(trial_runtime):
    from rlflow.hybrid_cpu_assessment import validate_record
    owner,_,token,*_=trial_runtime;_,lease=grant_and_lease(trial_runtime);owner.stop_to_terminal(lease)
    service=CpuAssessmentService(owner);before=owner.store.version()
    for key in (None,True,'','../escape'):
        with pytest.raises(ValueError):service.decide(lease,token,assessment_key=key,idempotency_key='bad',expected_state_version=before)
    assert owner.store.version()==before
    plain=service.assess(lease,token,idempotency_key='plain',expected_state_version=before)
    accepted=service.decide(lease,token,assessment_key=fact_key(plain['fact']['request']),idempotency_key='typed',expected_state_version=owner.store.version())
    value=deepcopy(accepted['fact']);key=fact_key(value['request'])
    value['machine_verification'].update(status='MACHINE_VERIFIED',derived=derive(SPEC,inputs()),source_sha256='sha256:'+'a'*64)
    for changed in (96.0,True):
        forged=deepcopy(value);forged['machine_verification']['derived']['inside_counts'][0]=changed
        with pytest.raises((Conflict,ValueError)):validate_record(key,forged)
    for changed in (1,0):
        forged=deepcopy(value);forged['machine_verification']['derived']['hypothesis_supported']=changed
        with pytest.raises((Conflict,ValueError)):validate_record(key,forged)
