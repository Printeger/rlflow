"""Actual CPU result -> current research appraisal; no condition/Goal success."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
import json

import pytest

from rlflow.hybrid_cpu_assessment import SECTION,EVENT,fact_key
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.store import Conflict,canonical
from tests.test_hybrid_cpu_trial_runtime import trial_runtime,grant_and_lease
from tests.test_execution_adapter import setup as native_setup


def test_actual_trial_appraisal_persist_inspect_idempotence_expiry_recovery(trial_runtime):
    owner,_,token,_,_,_,utc,mono=trial_runtime
    _,lease=grant_and_lease(trial_runtime); service=CpuAssessmentService(owner)
    for bad in (replace(lease),json.loads(lease.raw)):
        with pytest.raises(PermissionError): service.assess(bad,token,idempotency_key='bad',expected_state_version=owner.store.version())
    with pytest.raises(Conflict,match='STOP'): service.assess(lease,token,idempotency_key='early',expected_state_version=owner.store.version())
    result=owner.run_cpu_trial(lease); original=json.loads(result.raw)
    before=owner.store.version(); args={'idempotency_key':'appraise','expected_state_version':before}
    accepted=service.assess(lease,token,**args); value=accepted['fact'];key=fact_key(value['request'])
    assert not accepted['duplicate'] and owner.store.version()==before+1
    assert value['assessment']['execution_status']=='SUCCEEDED'
    assert value['assessment']['scientific_validity']=='VALID' and value['assessment']['hypothesis_outcome']=='SUPPORTED'
    assert value['assessment']['next_action']=='REQUEST_INDEPENDENT_REVIEW'
    assert value['assessment']['condition_coverage']==[] and not value['assessment']['goal_completed']
    assert value['assessment']['independent_review_status']=='NOT_PERFORMED'
    version=owner.store.version(); inspected=service.inspect(key)
    assert inspected['current_activation']=='EXPERIMENT_CURRENT_AS_OF' and owner.store.version()==version
    assert service.assess(lease,token,**args)['duplicate'] and owner.store.version()==version
    assert json.loads(result.raw)==original and original['evidence_activation']=='AUDIT_ONLY'
    with pytest.raises(Conflict,match='idempotency'):
        service.assess(lease,token,idempotency_key='appraise',expected_state_version=version)
    state=owner.store.audit(); assert owner.store.replay()==state
    owner.store.snapshot(); assert owner.store.recover()==state
    utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9
    assert service.inspect(key)['current_activation']=='HISTORICAL_ONLY'
    assert owner.store.version()==version and owner.store.audit()==state
    # Exact old receipt is historical, not renewed activation or another compute.
    assert service.assess(lease,token,**args)['current_activation']=='NOT_RECHECKED'
    assert owner.store.version()==version and owner.pool.snapshot()['occupied']==0


def test_no_G_trial_is_unassessed_inconclusive_and_never_automatically_retried(trial_runtime):
    owner,_,token,*_=trial_runtime;_,lease=grant_and_lease(trial_runtime)
    owner.stop_to_terminal(lease);service=CpuAssessmentService(owner)
    accepted=service.assess(lease,token,idempotency_key='not_executed',expected_state_version=owner.store.version())
    value=accepted['fact']; appraisal=value['assessment'];key=fact_key(value['request'])
    assert appraisal['execution_status']=='NOT_EXECUTED' and appraisal['scientific_validity']=='UNASSESSED'
    assert appraisal['hypothesis_outcome']=='INCONCLUSIVE' and appraisal['next_action']=='NO_AUTOMATIC_RETRY'
    assert value['result_hash'] is None and not owner._issued(lease)['spawn_entered']
    assert owner.store.audit()==owner.store.replay()
    before=owner.store.version()
    # Generic/legacy writers and a lookalike guard cannot forge even a no-op.
    with pytest.raises(PermissionError): owner.store.transact(EVENT,key,lambda state:None,object_id='untrusted')
    with pytest.raises(PermissionError):
        owner.store.transact_objects(EVENT,key,[(SECTION,key)],lambda state:None,object_id='untrusted')
    with pytest.raises(PermissionError):
        owner.store.transact_objects('OTHER','forge',[(SECTION,key)],
            lambda state:state[SECTION][key].update(evidence_activation='EXPERIMENT_CURRENT_AS_OF'))
    assert owner.store.version()==before


@pytest.mark.parametrize('change',['revision','revoke'])
def test_actual_new_authority_or_contract_preserves_historical_trial_only(trial_runtime,change):
    owner,_,token,*_=trial_runtime;_,lease=grant_and_lease(trial_runtime)
    owner.stop_to_terminal(lease);service=CpuAssessmentService(owner)
    accepted=service.assess(lease,token,idempotency_key='original',expected_state_version=owner.store.version())
    value=accepted['fact'];key=fact_key(value['request']);store=owner.store
    approval=store._hybrid_authority_service
    session,access=approval.auth.login('fixture_human','Working plan isolated synthetic fixture passphrase')
    args={'token':session,'csrf':access.csrf,'origin':'http://127.0.0.1:8765'}
    proposal=store.get('hybrid_goal_contracts',value['sources']['contract_key'])['contract']['proposal']
    if change=='revoke':
        approval.revoke(**args,goal_id=proposal['goal_id'],approval_key=value['sources']['approval_key'],
            expected_version=store.version(),expected_authority_revision=1,reason='Isolated original trial appraisal revocation',idempotency_key='revoke')
    else:
        proposal=deepcopy(proposal);proposal['contract_version']+=1;proposal['objective']+=' Different current contract.'
        store._hybrid_draft_service.submit(proposal,**args,idempotency_key='revision',expected_revision=1,expected_state_version=store.version())
    version=store.version()
    assert service.inspect(key)['current_activation']=='HISTORICAL_ONLY'
    assert store.get(SECTION,key)==value and store.version()==version
    with pytest.raises(Conflict): service.assess(lease,token,idempotency_key='new',expected_state_version=version)
    assert store.version()==version and store.audit()==store.replay()


def test_actual_lost_commit_receipt_and_bounded_snapshot_original_proofs(trial_runtime,monkeypatch):
    from rlflow.snapshot_maintenance import maintain
    owner,_,token,*_=trial_runtime;_,lease=grant_and_lease(trial_runtime)
    owner.stop_to_terminal(lease);service=CpuAssessmentService(owner);store=owner.store
    args={'idempotency_key':'lost','expected_state_version':store.version()}
    connect=store.connect
    class LostReturn:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def commit(self):self.db.commit();raise OSError('actual assessment COMMIT lost receipt')
        def __enter__(self):return self
        def __exit__(self,*args):return self.db.__exit__(*args)
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',lambda:LostReturn(connect()))
        with pytest.raises(OSError,match='lost receipt'):service.assess(lease,token,**args)
    version=store.version();assert version==args['expected_state_version']+1
    accepted=service.assess(lease,token,**args);value=accepted['fact'];key=fact_key(value['request'])
    assert accepted['duplicate'] and store.version()==version
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(version,))
    assert maintain(store,seconds=30)
    assert store.recover()==store.audit()
    with store.connect() as db:
        raw=db.execute('SELECT state FROM snapshots WHERE version=?',(version,)).fetchone()[0]
        state=json.loads(raw);state.pop(SECTION)
        corrupt=canonical(state)
        db.execute('UPDATE snapshots SET state=?,sha256=? WHERE version=?',(corrupt,hashlib.sha256(corrupt).hexdigest(),version))
    with pytest.raises(Conflict,match='historical domain'):store.recover()
    with store.connect() as db:db.execute('UPDATE snapshots SET state=?,sha256=? WHERE version=?',(raw,hashlib.sha256(raw).hexdigest(),version))
    assert store.recover()==store.audit()
    # A deleted projection domain cannot be legitimized by periodic maintenance.
    with store.connect() as db:
        rows=list(db.execute('SELECT section,object_key,value,version FROM projection WHERE section=?',(SECTION,)))
        db.execute('DELETE FROM projection WHERE section=?',(SECTION,));db.execute('UPDATE snapshot_due SET due_version=?',(version,))
    assert not maintain(store,seconds=30)
    with store.connect() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0]==version
        db.executemany('INSERT INTO projection(section,object_key,value,version) VALUES(?,?,?,?)',[tuple(row) for row in rows])
    assert store.audit()==store.replay()


def test_read_final_TTL_and_historical_causal_order_and_bounded_headers(trial_runtime,monkeypatch):
    from rlflow.hybrid_cpu_assessment import validate_links
    from rlflow.hybrid_goals import digest
    owner,_,token,_,_,_,utc,mono=trial_runtime;_,lease=grant_and_lease(trial_runtime)
    utc[0]+=timedelta(seconds=1);mono[0]+=10**9
    owner.stop_to_terminal(lease);service=CpuAssessmentService(owner);store=owner.store
    accepted=service.assess(lease,token,idempotency_key='bounded',expected_state_version=store.version())
    value=accepted['fact'];key=fact_key(value['request']);state=store.audit()
    shifted=deepcopy(value);shifted['recorded_at']=shifted['sources']['evaluated_at']='2026-10-09T00:00:00Z'
    with pytest.raises(Conflict,match='original trial'): validate_links(shifted,lambda s,k:state.get(s,{}).get(k))
    lookup=service._current_sources
    def expire_after_proof(*args):
        current=lookup(*args);utc[0]+=timedelta(seconds=120);mono[0]+=120*10**9;return current
    with monkeypatch.context() as patch:
        patch.setattr(service,'_current_sources',expire_after_proof)
        assert service.inspect(key)['current_activation']=='HISTORICAL_ONLY'
    # Huge hostile header is rejected by SQL CASE, not fetched into the reader.
    with store.connect() as db:
        original=db.execute('SELECT producer FROM events WHERE idempotency_key=?',(key,)).fetchone()[0]
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET producer=? WHERE idempotency_key=?',('x'*1000000,key))
        db.execute(trigger)
    with pytest.raises(Conflict,match='bound'):service.inspect(key)
    with store.connect() as db:
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET producer=? WHERE idempotency_key=?',(original,key))
        db.execute(trigger)
    assert store.audit()==state
