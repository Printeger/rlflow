"""Actual same-writer BLOCKED admission; never launches a candidate."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import threading

import pytest

from rlflow.hybrid_admission import SECTION, EVENT, fact_key
from rlflow.hybrid_admission_service import AdmissionService
from rlflow.hybrid_controller_service import ControllerToken
from rlflow.hybrid_authority import timestamp
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Store, Conflict, canonical, sha
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


def actual(admission):
    prep,controller,_,witness,value,_=admission
    service=AdmissionService(prep.store,prep.registry,controller,prep)
    token=controller._tokens[value['controller']['fact_key']]
    return service,deepcopy(value['request']),token,witness


def test_actual_admission_is_durable_blocked_and_recoverable(admission):
    service,request,token,witness=actual(admission);store=service.store
    result=service.admit(request,token,witness=witness);value=result['fact']
    assert result['duplicate'] is result['execution_enabled'] is False
    assert value['status']=='BLOCKED' and all(value[n] is False for n in
        ('execution_enabled','release_enabled','candidate_write_enabled'))
    assert value['gates']['writer_lease']==value['gates']['model_access']=='UNVERIFIED'
    assert store.version()==6 and dict(store.objects(SECTION))=={fact_key(request):value}
    assert not store.objects('sessions') and not store.objects('tasks')
    state=store.audit();assert state==store.replay()
    store.snapshot();assert Store(store.root).recover()==state
    assert service._active is None and service.controller._token_active is None


def test_actual_admission_issues_witness_outside_writer(admission,monkeypatch):
    service,request,token,_=actual(admission)
    issue=service.preparation.issue_material_witness
    def checked(key):
        assert service.controller._token_active is None and service._active is None
        return issue(key)
    monkeypatch.setattr(service.preparation,'issue_material_witness',checked)
    assert service.admit(request,token)['fact']['status']=='BLOCKED'


def test_duplicate_is_historical_without_material_reprobe(admission,monkeypatch):
    service,request,token,witness=actual(admission)
    first=service.admit(request,token,witness=witness)
    expired=timestamp(first['fact']['sources']['expires_at'])+timedelta(days=1)
    monkeypatch.setattr(service.preparation,'clock',lambda:expired)
    monkeypatch.setattr(service.controller,'clock',lambda:expired)
    def forbidden(*args,**kwargs):raise AssertionError('duplicate must not reprobe material')
    monkeypatch.setattr(service.preparation,'issue_material_witness',forbidden)
    monkeypatch.setattr(service.preparation,'check_material_witness',forbidden)
    duplicate=service.admit(request,token)
    assert duplicate=={**first,'duplicate':True} and service.store.version()==6
    changed={**request,'expected_state_version':6}
    with pytest.raises(Conflict,match='idempotency'):service.admit(changed,token)


@pytest.mark.parametrize('damage',['copied_token','json_token','json_witness','stale_version','scope'])
def test_forged_or_stale_inputs_do_not_write(admission,damage):
    service,request,token,witness=actual(admission);before=service.store.audit()
    if damage=='copied_token':token=ControllerToken(token.key,token.raw)
    elif damage=='json_token':token={'key':token.key,'raw':token.raw}
    elif damage=='json_witness':witness={'raw':witness.raw}
    elif damage=='stale_version':request['expected_state_version']=4
    else:request['project_id']='other'
    with pytest.raises((ValueError,PermissionError)):service.admit(request,token,witness=witness)
    assert service.store.audit()==before and service._active is None


def test_periodic_snapshot_closes_original_admission_proof(admission):
    service,request,token,witness=actual(admission)
    service.admit(request,token,witness=witness);state=service.store.audit()
    with service.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=6')
    maintain(service.store)
    assert service.store.recover()==state


@pytest.mark.parametrize('expiry',['source','witness'])
def test_expiry_during_final_controller_check_rolls_back_fact(admission,monkeypatch,expiry):
    service,request,token,witness=actual(admission);before=service.store.audit()
    check=service.controller.check_token_in_transaction;after_fact=[0]
    def expire_after_fact(db,passed,budget):
        result=check(db,passed,budget)
        if db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',
                      (SECTION,fact_key(request))).fetchone():
            assert service._active is not None;after_fact[0]+=1
            # First is the body guard, second the owned context final token
            # check. Expire only after that check, before its final callback.
            if after_fact[0]==2:
                if expiry=='source':
                    late=timestamp(admission[4]['sources']['expires_at'])
                    monkeypatch.setattr(service.controller,'clock',lambda:late)
                else:
                    monkeypatch.setattr(service.preparation,'_witness_monotonic_ns',
                                        lambda:witness.expires_monotonic_ns)
        return result
    monkeypatch.setattr(service.controller,'check_token_in_transaction',expire_after_fact)
    with pytest.raises(Conflict):service.admit(request,token,witness=witness)
    assert service.store.audit()==before and service._active is None
    assert service.controller._token_active is None
    assert after_fact[0]>=2


@pytest.mark.parametrize('damage',['extra','delete','marker','missing_marker','duplicate',
    'foreign','details','floating','wrong_hash'])
def test_original_admission_event_corruption_refuses_every_closure(admission,damage):
    service,request,token,witness=actual(admission);store=service.store
    service.admit(request,token,witness=witness);key=fact_key(request)
    with store.connect() as db:
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        payload=json.loads(db.execute('SELECT payload FROM events WHERE idempotency_key=?',(key,)).fetchone()[0])
        if damage=='extra':payload['extra']=None
        elif damage=='delete':payload['delete']=[[SECTION,key]]
        elif damage=='marker':payload['put'].append([SECTION,'',{'wrong':True}])
        elif damage=='missing_marker':payload['put']=[r for r in payload['put'] if r[1]]
        elif damage=='duplicate':payload['put'].append(deepcopy(payload['put'][0]))
        elif damage=='foreign':payload['put'].append(['sessions','foreign',{}])
        elif damage=='details':payload['details']={'fake':True}
        elif damage=='floating':payload['format']=2.0
        # Disposable DB fault injection; restore append-only protection before
        # every product call, never weaken a production validation path.
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?',
            (canonical(payload).decode(),sha(payload) if damage!='wrong_hash' else sha('wrong'),key))
        db.execute(trigger);db.execute('UPDATE snapshot_due SET due_version=6')
    for operation in (store.audit,store.snapshot,store.recover,
                      lambda:service.admit(request,token)):
        with pytest.raises(ValueError):operation()
    assert maintain(store) is False
    with store.connect() as db:
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()


@pytest.mark.parametrize('damage',['whole_domain','empty_domain','nonlatest_fact'])
def test_rehashed_snapshot_cannot_omit_admission_history(admission,damage):
    service,request,token,witness=actual(admission);store=service.store
    service.admit(request,token,witness=witness)
    second={**request,'idempotency_key':'second','expected_state_version':6}
    service.admit(second,token,witness=witness);state=store.audit()
    assert store._hybrid_admission_service._active is None
    if damage=='whole_domain':state.pop(SECTION)
    elif damage=='empty_domain':state[SECTION]={}
    else:del state[SECTION][fact_key(request)]
    raw=canonical(state)
    with store.connect() as db:
        db.execute('INSERT INTO snapshots VALUES(?,?,?)',(7,raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises(ValueError):store.recover()


def test_old_snapshot_new_tail_and_later_controller_head_are_valid_history(admission):
    service,request,token,witness=actual(admission);store=service.store
    service.admit(request,token,witness=witness);store.snapshot()
    second={**request,'idempotency_key':'second','expected_state_version':6}
    service.admit(second,token,witness=witness)
    renewed=service.controller.renew(token,'later-controller',expected_version=7)
    state=store.audit();assert state==store.replay()==Store(store.root).recover()
    assert renewed['fact']['head_revision']==2 and state['version']==8


def test_store_cannot_write_admission_without_actual_guard(admission):
    service,request,token,witness=actual(admission);store=service.store
    value=admission[4];key=fact_key(request);before=store.audit()
    with pytest.raises(PermissionError):
        store.transact_objects(EVENT,key,[(SECTION,key)],lambda state:None,
                               expected=5,object_id=sha(value),producer='hybrid-core')
    assert store.audit()==before and not store.objects(SECTION)


@pytest.mark.parametrize('entry',['duplicate','wrong_event','whole_state','duck_guard'])
def test_generic_writer_cannot_bypass_admission_guard(admission,entry):
    service,request,token,witness=actual(admission);store=service.store
    result=service.admit(request,token,witness=witness);value=result['fact'];key=fact_key(request)
    before=store.audit()
    def mutate(state):
        changed=deepcopy(value);changed['reason']='FORGED'
        state.setdefault(SECTION,{})[key]=changed
    with pytest.raises((PermissionError,ValueError)):
        if entry=='whole_state':
            store.transact(EVENT,'whole',mutate,expected=6)
        elif entry=='duck_guard':
            from contextlib import contextmanager
            class Duck:
                def check(self):pass
            @contextmanager
            def fake():yield Duck()
            store.transact_objects(EVENT,'fake',[(SECTION,key)],mutate,expected=6,_authorization=fake)
        else:
            store.transact_objects(EVENT if entry=='duplicate' else 'OTHER',
                key if entry=='duplicate' else 'other',[(SECTION,key)],mutate,expected=6,
                object_id=sha(value),producer='hybrid-core')
    assert store.audit()==before


def test_actual_admission_and_renewal_have_one_cas_winner_without_deadlock(admission):
    service,request,token,witness=actual(admission);barrier=threading.Barrier(2);outcomes=[]
    def admit():
        barrier.wait()
        try:outcomes.append(service.admit(request,token,witness=witness))
        except Conflict as exc:outcomes.append(exc)
    def renew():
        barrier.wait()
        try:outcomes.append(service.controller.renew(token,'race-renew',expected_version=5))
        except Conflict as exc:outcomes.append(exc)
    threads=[threading.Thread(target=admit),threading.Thread(target=renew)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=10);assert not thread.is_alive()
    assert len(outcomes)==2 and sum(isinstance(v,dict) for v in outcomes)==1
    assert service.store.version()==6 and service.store.audit()==service.store.replay()


def test_actual_admission_refuses_nested_controller_writer_before_lock(admission):
    service,request,token,witness=actual(admission);before=service.store.audit()
    with service.controller.token_transaction(token):
        with pytest.raises(Conflict,match='nested'):
            service.admit(request,token,witness=witness)
    assert service.store.audit()==before


def test_material_witness_is_asof_not_file_io_or_execution_under_writer(admission,monkeypatch):
    service,request,token,witness=actual(admission)
    def forbidden(*args,**kwargs):raise AssertionError('full material IO cannot run under writer')
    monkeypatch.setattr(service.preparation.builder,'verify',forbidden)
    monkeypatch.setattr(service.preparation.adapter,'verify_bundle',forbidden)
    result=service.admit(request,token,witness=witness)
    assert result['fact']['gates']['material_observation']=='VERIFIED_AS_OF'
    assert result['fact']['status']=='BLOCKED' and result['execution_enabled'] is False
