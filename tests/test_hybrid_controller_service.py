"""Real SQLite fencing with actual process identity; no child/model execution."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import threading
import hashlib
import gc

import pytest

from rlflow.hybrid_controller import SECTIONS, EVENT, head, fact_key, scope_key
from rlflow.hybrid_controller_service import ControllerService, ControllerToken
from rlflow.hybrid_goals import digest
from rlflow.jobs import identity
from rlflow.observation import enable, rotate_epoch
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Store, Conflict, canonical, sha
from tests.test_hybrid_registry import bound, catalog


@pytest.fixture
def owned(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    registry,_=bound(catalog());clock=[datetime(2026,10,9,tzinfo=timezone.utc)];mono=[100*10**9]
    with store.read_connection() as db:
        epoch=db.execute('SELECT store_epoch FROM observation_meta WHERE singleton=1').fetchone()[0]
    service=ControllerService(store,registry,project_id='project_fixture',data_mode='fixture',
        store_epoch=epoch,clock=lambda:clock[0],monotonic_ns=lambda:mono[0])
    return service,clock,mono


def other(owned,epoch=None):
    service,clock,mono=owned
    return ControllerService(Store(service.store.root),service.registry,project_id=service.project_id,
        data_mode=service.data_mode,store_epoch=epoch or service.store_epoch,
        clock=lambda:clock[0],monotonic_ns=lambda:mono[0])


def advance(owned,seconds):
    _,clock,mono=owned;clock[0]+=timedelta(seconds=seconds);mono[0]+=seconds*10**9


def acquire(service,key='initial',**kwargs):
    return service.acquire(key,expected_version=service.store.version(),**kwargs)


def test_real_issued_token_is_core_only_and_history_survives_expiry(owned):
    service,clock,mono=owned;result=acquire(service);token=result['token'];value=result['fact']
    assert value['request']['owner']['process']==identity(value['request']['owner']['process']['pid'])
    assert service.check_token(token)=={'controller_epoch':1,'head_revision':1,
        'authority_domain':'HYBRID_CORE_FACTS_ONLY','execution_enabled':False}
    state=service.store.audit();assert state==service.store.replay()
    assert not service.store.objects('sessions') and not service.store.objects('tasks')
    assert all(s not in service.store.view() for s in SECTIONS)
    advance(owned,30)
    with pytest.raises(Conflict):service.check_token(token)
    service.store.snapshot();assert Store(service.store.root).recover()==state
    retried=service.acquire('initial',expected_version=0)
    assert retried=={'fact':value,'token':None,'duplicate':True,'execution_enabled':False}
    assert service.store.version()==1


def test_renewal_invalidates_old_revision_without_new_controller_epoch(owned):
    service,_,_=owned;initial=acquire(service);advance(owned,10)
    renewed=service.renew(initial['token'],'renewal',expected_version=1,ttl_seconds=40)
    assert renewed['fact']['controller_epoch']==1 and renewed['fact']['head_revision']==2
    assert service.check_token(renewed['token'])['head_revision']==2
    with pytest.raises(Conflict):service.check_token(initial['token'])
    assert service.store.audit()==service.store.replay()
    retry=service.renew(initial['token'],'renewal',expected_version=1,ttl_seconds=40)
    assert retry['fact']==renewed['fact'] and retry['token'] is None and retry['duplicate']


def test_two_actual_owners_acquire_one_winner(owned):
    service,_,_=owned;second=other(owned);barrier=threading.Barrier(2);outcomes=[]
    def attempt(owner):
        barrier.wait()
        try:outcomes.append(owner.acquire('competing',expected_version=0))
        except Conflict as exc:outcomes.append(exc)
    threads=[threading.Thread(target=attempt,args=(s,)) for s in (service,second)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=10);assert not thread.is_alive()
    assert len([v for v in outcomes if isinstance(v,dict)])==1
    assert len([v for v in outcomes if isinstance(v,Conflict)])==1
    assert service.store.version()==1 and len(service.store.objects(SECTIONS[0]))==1


def test_expired_takeover_increments_fence_but_cleanup_stays_unknown(owned):
    service,_,_=owned;initial=acquire(service);second=other(owned)
    with pytest.raises(Conflict):acquire(second,'early')
    advance(owned,30);changed=acquire(second,'takeover')
    assert changed['fact']['controller_epoch']==2 and changed['fact']['reason']=='EXPIRED_PREDECESSOR'
    assert changed['fact']['prior_runtime_recovery']=='UNVERIFIED'
    assert changed['fact']['candidate_write_enabled'] is changed['fact']['execution_enabled'] is False
    with pytest.raises(Conflict):service.renew(initial['token'],'late',expected_version=2)
    assert service.store.audit()==service.store.replay()


@pytest.mark.parametrize('damage',['copy','json','foreign_service','made_up'])
def test_only_exact_actual_token_object_is_usable(owned,damage):
    service,_,_=owned;result=acquire(service);token=result['token']
    if damage=='copy':token=ControllerToken(token.key,token.raw)
    elif damage=='json':token=json.loads(token.raw)
    elif damage=='foreign_service':service=other(owned)
    else:token=ControllerToken('fake',b'{}')
    with pytest.raises(PermissionError):service.check_token(token)


@pytest.mark.parametrize('clock_change',['utc_expired','mono_expired','utc_forward_only','utc_backward','mono_backward'])
def test_both_live_deadlines_and_regression_are_checked(owned,clock_change):
    service,clock,mono=owned;result=acquire(service)
    if clock_change in ('utc_expired','utc_forward_only'):clock[0]+=timedelta(seconds=30)
    elif clock_change=='mono_expired':mono[0]+=30*10**9
    elif clock_change=='utc_backward':clock[0]-=timedelta(seconds=1)
    else:mono[0]-=1
    with pytest.raises(Conflict):service.check_token(result['token'])
    if clock_change=='utc_forward_only':
        second=other(owned)
        with pytest.raises(Conflict):acquire(second,'premature-takeover')
        assert service.store.version()==1


@pytest.mark.parametrize('damage',['pid_reuse','boot_change','owner_change','registry_change','stop'])
def test_live_identity_config_and_stop_refuse_without_writing(owned,monkeypatch,damage):
    service,_,_=owned;result=acquire(service);before=service.store.audit()
    if damage in ('pid_reuse','boot_change'):
        process=deepcopy(service.owner['process'])
        process['starttime' if damage=='pid_reuse' else 'boot_id']='different'
        monkeypatch.setattr('rlflow.hybrid_controller_service.identity',lambda pid:process)
    elif damage=='owner_change':service.owner['id']='other'
    elif damage=='registry_change':
        config=json.loads(service.registry._raw);config['project_policy']['configuration']={'new':True}
        from rlflow.hybrid_registry import Registry
        service.registry=Registry(config)
    else:monkeypatch.setattr('rlflow.hybrid_controller_service.stopped',lambda root:['STOP'])
    with pytest.raises(Conflict):service.renew(result['token'],'blocked',expected_version=1)
    assert service.store.audit()==before


@pytest.mark.parametrize('entry',['new','duplicate','whole_state','duck_guard','wrong_event'])
def test_unguarded_store_cannot_write_or_return_duplicate(owned,entry):
    service,_,_=owned;result=acquire(service);value=result['fact'];key=fact_key(value['request']);store=service.store
    before=store.audit()
    if entry=='whole_state':
        with pytest.raises(PermissionError):store.transact(EVENT,key,lambda s:None,object_id=digest(value))
    else:
        if entry=='wrong_event':value={**value,'config_hash':digest('changed')}
        class Fake:
            def check(self):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with pytest.raises(PermissionError):
            store.transact_objects(EVENT if entry!='wrong_event' else 'OTHER',key if entry=='duplicate' else 'other',
                [(SECTIONS[0],key)],lambda s:s.setdefault(SECTIONS[0],{}).update({key:value}),
                object_id=digest(value),producer='hybrid-core',_authorization=(lambda:Fake()) if entry=='duck_guard' else None)
    assert store.audit()==before


def test_final_guard_rejects_predecessor_expiring_after_live_write_check(owned,monkeypatch):
    service,_,_=owned;result=acquire(service);advance(owned,29);check=service.check_live_write
    def expire(db,payload,guard):
        check(db,payload,guard);advance(owned,1)
    monkeypatch.setattr(service,'check_live_write',expire)
    with pytest.raises(Conflict,match='predecessor expired'):service.renew(result['token'],'expired',expected_version=1)
    assert service.store.version()==1 and len(service.store.objects(SECTIONS[0]))==1


def test_new_observation_epoch_fences_old_owner_without_runtime_cleanup_claim(owned):
    service,_,_=owned;initial=acquire(service);rotate_epoch(service.store)
    with service.store.read_connection() as db:
        epoch=db.execute('SELECT store_epoch FROM observation_meta WHERE singleton=1').fetchone()[0]
    changed=acquire(other(owned,epoch),'new-epoch')
    assert changed['fact']['reason']=='NEW_STORE_EPOCH' and changed['fact']['controller_epoch']==2
    with pytest.raises(Conflict):service.check_token(initial['token'])
    assert changed['fact']['prior_runtime_recovery']=='UNVERIFIED'
    service.store.snapshot();assert Store(service.store.root).recover()==service.store.audit()


def test_restart_never_adopts_fact_as_token(owned):
    service,_,_=owned;initial=acquire(service);restarted=other(owned)
    with pytest.raises(PermissionError):restarted.check_token(initial['token'])
    with pytest.raises(Conflict):acquire(restarted,'restart')
    advance(owned,30);result=acquire(restarted,'after-expiry')
    assert result['fact']['controller_epoch']==2


@pytest.mark.parametrize('change',['ttl','expected','operation'])
def test_changed_request_same_idempotency_key_refused(owned,change):
    service,_,_=owned;initial=acquire(service)
    with pytest.raises(Conflict):
        if change=='operation':service.renew(initial['token'],'initial',expected_version=0)
        else:service.acquire('initial',expected_version=1 if change=='expected' else 0,
                             ttl_seconds=31 if change=='ttl' else 30)
    assert service.store.version()==1


def test_periodic_snapshot_includes_original_controller_pairs(owned):
    service,_,_=owned;initial=acquire(service)
    service.renew(initial['token'],'renew',expected_version=1)
    with service.store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=2 WHERE singleton=1');db.commit()
    assert maintain(service.store,seconds=10)
    assert Store(service.store.root).recover()==service.store.audit()


def test_missing_current_head_refuses_initial_reset_inside_writer(owned):
    service,_,_=owned;acquire(service)
    with service.store.connect() as db:
        db.execute('DELETE FROM projection WHERE section=?',(SECTIONS[1],));db.commit()
    with pytest.raises(Conflict,match='head missing'):acquire(other(owned),'reset')
    assert service.store.version()==1


def test_stale_head_cannot_create_a_second_renewal_branch(owned):
    service,_,_=owned;initial=acquire(service)
    service.renew(initial['token'],'renew',expected_version=1)
    with service.store.connect() as db:
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',
                   (canonical(head(initial['fact'])).decode(),SECTIONS[1],scope_key(service.project_id,service.data_mode)))
        db.commit()
    with pytest.raises(Conflict,match='original event tip'):
        service.renew(initial['token'],'fork',expected_version=2)
    assert service.store.version()==2


def test_removed_controller_projection_cannot_reset_existing_event_history(owned):
    service,_,_=owned;acquire(service)
    with service.store.connect() as db:
        for section in SECTIONS:db.execute('DELETE FROM projection WHERE section=?',(section,))
        db.commit()
    with pytest.raises(Conflict,match='head missing'):acquire(other(owned),'reset')
    assert service.store.version()==1


def test_current_controller_tip_lookup_uses_fixed_index(owned):
    service,_,_=owned;acquire(service)
    with service.store.read_connection() as db:
        plan=db.execute('EXPLAIN QUERY PLAN SELECT idempotency_key,new_state_version FROM events WHERE event_type=? ORDER BY seq DESC LIMIT 1',(EVENT,)).fetchall()
    assert any('events_type_tip' in row['detail'] for row in plan)


@pytest.mark.parametrize('damage',['renew_marker','initial_marker_missing','delete','extra','duplicate',
    'details','floating_format','head_mismatch','sha','raw_bound'])
def test_corrupted_original_source_rejected_by_all_historical_and_live_paths(owned,damage):
    service,_,_=owned;initial=acquire(service)
    renewed=service.renew(initial['token'],'renew',expected_version=1)
    store=service.store;store.snapshot();before_version=store.version()
    key=initial['token'].key if damage=='initial_marker_missing' else renewed['token'].key
    with store.connect() as db:
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        payload=json.loads(db.execute('SELECT payload FROM events WHERE idempotency_key=?',(key,)).fetchone()[0])
        if damage=='renew_marker':payload['put'].append([SECTIONS[0],'',{}])
        elif damage=='initial_marker_missing':payload['put']=[r for r in payload['put'] if r[1]]
        elif damage=='delete':payload['delete']=[[SECTIONS[0],initial['token'].key]]
        elif damage=='extra':payload['put'].append(['sessions','unapproved',{}])
        elif damage=='duplicate':payload['put'].append(deepcopy(payload['put'][0]))
        elif damage=='details':payload['details']={'unverified_grant':True}
        elif damage=='floating_format':payload['format']=2.0
        elif damage=='head_mismatch':payload['put'][1][2]['revision']+=1
        elif damage=='raw_bound':payload['details']='x'*(256*1024)
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?',
                   (canonical(payload).decode(),sha('wrong') if damage=='sha' else sha(payload),key))
        db.execute(trigger)
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()
        db.execute('UPDATE snapshot_due SET due_version=2 WHERE singleton=1')
        db.commit()
    with pytest.raises(ValueError):store.audit()
    with pytest.raises(Conflict):store.snapshot()
    with pytest.raises(Conflict):Store(store.root).recover()
    with pytest.raises(Conflict):service.check_token(renewed['token'])
    assert maintain(store,seconds=10) is False
    assert store.version()==before_version


@pytest.mark.parametrize('damage',['absent','empty'])
def test_rehashed_snapshot_cannot_omit_entire_controller_domain(owned,damage):
    service,_,_=owned;acquire(service);store=service.store;store.snapshot()
    with store.connect() as db:
        state=json.loads(db.execute('SELECT state FROM snapshots WHERE version=1').fetchone()[0])
        for section in SECTIONS:
            if damage=='absent':state.pop(section)
            else:state[section]={}
        raw=canonical(state)
        db.execute('UPDATE snapshots SET state=?,sha256=? WHERE version=1',(raw,hashlib.sha256(raw).hexdigest()))
        db.commit()
    with pytest.raises(Conflict,match='domain omitted'):Store(store.root).recover()
    assert store.version()==1


@pytest.mark.parametrize('damage',['absent','empty'])
def test_projection_domain_omission_cannot_publish_new_snapshot(owned,damage):
    service,_,_=owned;acquire(service);store=service.store
    with store.connect() as db:
        for section in SECTIONS:
            db.execute('DELETE FROM projection WHERE section=?'+(" AND object_key!=''" if damage=='empty' else ''),(section,))
        db.execute('UPDATE snapshot_due SET due_version=1 WHERE singleton=1');db.commit()
    with pytest.raises(Conflict):store.snapshot()
    assert maintain(store,seconds=10) is False
    with store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due WHERE singleton=1').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]==0


def test_old_valid_snapshot_uses_its_historical_tip_not_newest_global_tip(owned):
    service,_,_=owned;initial=acquire(service);service.store.snapshot()
    advance(owned,10);service.renew(initial['token'],'newer',expected_version=1)
    expected=service.store.audit()
    assert Store(service.store.root).recover()==expected


def test_discarded_token_is_not_retained_or_reconstructed(owned):
    service,_,_=owned;result=acquire(service);key=result['token'].key
    del result;gc.collect()
    assert key not in service._tokens
    value=service.store.get(SECTIONS[0],key)
    with pytest.raises(PermissionError):service.check_token(ControllerToken(key,canonical(value)))


def test_released_old_revisions_do_not_accumulate_in_owner_cache(owned):
    service,_,_=owned;result=acquire(service)
    for index in range(16):
        result=service.renew(result['token'],f'renew_{index}',expected_version=service.store.version())
    gc.collect()
    assert len(service._tokens)==1 and service.check_token(result['token'])['head_revision']==17
