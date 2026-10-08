from copy import deepcopy
from datetime import timedelta
import json
import hashlib

import pytest

from rlflow.hybrid_preparation import SECTIONS, EVENTS, intent_key, result_key
from rlflow.hybrid_preparation_service import PreparationService, MaterialWitness
from rlflow.hybrid_snapshot import SnapshotBuilder
from rlflow.hybrid_reads import ReadBudget
from rlflow.hybrid_authority import timestamp
from rlflow.hybrid_goals import digest
from rlflow.observation import rotate_epoch
from rlflow.store import Conflict, Store, canonical, sha
from rlflow.snapshot_maintenance import maintain
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def owned(tmp_path,prepared,native_setup):
    store,adapter,_,value,_,_=prepared
    _,_,candidate,_,_,calls=native_setup
    control=tmp_path/'owned-snapshots';control.mkdir(mode=0o700)
    builder=SnapshotBuilder(candidate,['module/source.py'],control)
    clock=[timestamp(value['created_at'])]
    service=PreparationService(store,adapter.registry,builder,adapter,
        project_id=value['request']['project_id'],data_mode=value['request']['data_mode'],
        store_epoch=value['sources']['store_epoch'],clock=lambda:clock[0])
    return service,deepcopy(value['request']),clock,calls


def test_actual_service_intent_precedes_publish_and_complete_is_nonexecuting(owned,monkeypatch):
    service,request,clock,calls=owned;store=service.store
    publish=service.adapter.publish_preparation
    def observed(bundle):
        intent=store.get(SECTIONS[0],intent_key(request))
        assert intent['bundle']==json.loads(bundle.raw) and intent['accepted_state_version']==3
        assert store.version()==3 and not store.objects(SECTIONS[1])
        return publish(bundle)
    monkeypatch.setattr(service.adapter,'publish_preparation',observed)
    value=service.prepare(request)
    assert value['result']['status']=='PREPARED' and store.version()==4
    assert value['result']['execution_enabled'] is False
    state=store.audit();assert state==store.replay()
    assert state[SECTIONS[0]][intent_key(request)]==value['intent']
    assert state[SECTIONS[1]][result_key(intent_key(request))]==value['result']
    assert not store.objects('sessions') and not store.objects('tasks')
    with pytest.raises(PermissionError):service.adapter.start(value['result'])
    store.snapshot();assert Store(store.root).recover()==state
    assert SECTIONS[0] not in store.view() and SECTIONS[1] not in store.view()


def test_actual_material_witness_checks_issued_files_but_is_only_as_of(owned,monkeypatch):
    service,request,_,_=owned;prepared=service.prepare(request);before=service.store.audit()
    witness=service.issue_material_witness(intent_key(request))
    record=service.check_material_witness(witness,prepared['intent'],prepared['result'])
    assert record['state']=='VERIFIED_AS_OF' and record['execution_enabled'] is False
    assert record['intent_hash']==digest(prepared['intent']) and record['result_hash']==digest(prepared['result'])
    monkeypatch.setattr(service.builder,'verify',lambda s:pytest.fail('writer check reopened files'))
    monkeypatch.setattr(service.adapter,'verify_bundle',lambda b:pytest.fail('writer check reopened bundle'))
    assert service.check_material_witness(witness,prepared['intent'],prepared['result'])==record
    assert service.store.audit()==before and not service.store.objects('sessions')


@pytest.mark.parametrize('damage',['copy','json','foreign_owner','expired','wrong_intent','wrong_result','material_slot'])
def test_material_witness_cannot_be_copied_rebound_or_extended(owned,damage):
    service,request,clock,_=owned;prepared=service.prepare(request)
    witness=service.issue_material_witness(intent_key(request));intent=prepared['intent'];outcome=prepared['result']
    if damage=='copy':witness=MaterialWitness(witness.id,witness.raw,witness.materials,
        witness.boot_id,witness.issued_monotonic_ns,witness.expires_monotonic_ns)
    elif damage=='json':witness=json.loads(witness.raw)
    elif damage=='foreign_owner':service._witnesses.clear()
    elif damage=='expired':clock[0]+=timedelta(seconds=30)
    elif damage=='wrong_intent':intent={**intent,'created_at':'2026-10-09T00:00:00Z'}
    elif damage=='wrong_result':outcome={**outcome,'accepted_state_version':5}
    else:service._materials[intent_key(request)]=tuple(list(witness.materials))
    with pytest.raises((Conflict,PermissionError)):service.check_material_witness(witness,intent,outcome)


def test_material_witness_rejects_actual_snapshot_tamper_before_issue(owned):
    service,request,_,_=owned;service.prepare(request)
    snapshot,_,_=service._materials[intent_key(request)]
    (snapshot.path/'module/source.py').write_text('tampered\n')
    with pytest.raises(Conflict):service.issue_material_witness(intent_key(request))
    assert not service._witnesses


def test_material_witness_never_adopts_disk_after_owner_restart(owned):
    service,request,_,_=owned;service.prepare(request);service._materials.clear()
    with pytest.raises(PermissionError):service.issue_material_witness(intent_key(request))


@pytest.mark.parametrize('damage',['utc_stalled','utc_backward','mono_backward','boolean'])
def test_material_witness_real_elapsed_deadline_cannot_be_extended_by_clock(owned,damage):
    service,request,clock,_=owned;mono=[100*10**9];service._witness_monotonic_ns=lambda:mono[0]
    prepared=service.prepare(request);witness=service.issue_material_witness(intent_key(request))
    if damage=='utc_stalled':mono[0]+=30*10**9
    elif damage=='utc_backward':
        clock[0]+=timedelta(seconds=10);mono[0]+=10*10**9
        service.check_material_witness(witness,prepared['intent'],prepared['result'])
        clock[0]-=timedelta(seconds=1);mono[0]+=1*10**9
    elif damage=='mono_backward':mono[0]-=1
    else:mono[0]=True
    with pytest.raises(Conflict):service.check_material_witness(witness,prepared['intent'],prepared['result'])


def test_original_retry_is_no_regeneration_even_after_expiry(owned,monkeypatch):
    service,request,clock,calls=owned;original=service.prepare(request)
    clock[0]=timestamp(original['intent']['sources']['expires_at'])
    monkeypatch.setattr(service.builder,'build',lambda:pytest.fail('retry copied again'))
    monkeypatch.setattr(service.adapter,'build_preparation',lambda p:pytest.fail('retry probed again'))
    before=service.store.version();retried=service.prepare(request)
    assert retried=={**original,'duplicate':True} and service.store.version()==before
    changed={**request,'context':{'text':'different request'}}
    with pytest.raises(Conflict,match='idempotency'):service.prepare(changed)


@pytest.mark.parametrize('operation',['new','duplicate','whole_state','duck_guard'])
def test_unowned_store_entry_cannot_write_or_return_duplicate(owned,operation):
    service,request,_,_=owned;value=service.prepare(request);key=intent_key(request)
    store=service.store;before=store.audit()
    if operation=='whole_state':
        with pytest.raises(PermissionError):store.transact(EVENTS[0],key,lambda s:None,object_id=digest(value['intent']))
    else:
        class Fake:
            def check(self):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with pytest.raises(PermissionError):
            store.transact_objects(EVENTS[0],key if operation!='new' else 'other',[(SECTIONS[0],key)],
                lambda s:s.setdefault(SECTIONS[0],{}).update({key:value['intent']}),
                object_id=digest(value['intent']),producer='hybrid-core',
                _authorization=(lambda:Fake()) if operation=='duck_guard' else None)
    assert store.audit()==before


def test_expiry_during_material_verification_refuses_intent(owned,monkeypatch):
    service,request,clock,_=owned;verify=service.builder.verify
    def expire(snapshot):
        result=verify(snapshot);clock[0]+=timedelta(days=1);return result
    monkeypatch.setattr(service.builder,'verify',expire)
    with pytest.raises(Conflict):service.prepare(request)
    assert service.store.version()==2 and not service.store.objects(SECTIONS[0])


def test_publish_failure_preserves_original_intent_explicit_unknown_no_regeneration(owned,monkeypatch):
    service,request,_,_=owned
    monkeypatch.setattr(service.adapter,'publish_preparation',lambda b:(_ for _ in ()).throw(Conflict('fixture fail')))
    with pytest.raises(Conflict):service.prepare(request)
    assert service.store.version()==3
    pending=service.prepare(request)
    assert pending['result'] is None and pending['duplicate'] is True
    outcome=service.reconcile(request)
    assert outcome['result']['status']=='UNKNOWN' and outcome['result']['sources'] is None
    assert service.store.version()==4 and service.store.audit()==service.store.replay()
    assert service.reconcile(request)=={**outcome,'duplicate':True}


def test_epoch_change_after_publish_never_records_prepared(owned,monkeypatch):
    service,request,_,_=owned;publish=service.adapter.publish_preparation
    def rotated(bundle):
        result=publish(bundle);rotate_epoch(service.store);return result
    monkeypatch.setattr(service.adapter,'publish_preparation',rotated)
    with pytest.raises(Conflict):service.prepare(request)
    assert service.store.version()==3 and not service.store.objects(SECTIONS[1])
    with pytest.raises(Conflict):service.reconcile(request)
    service.store.audit()


def test_periodic_snapshot_captures_both_preparation_original_proofs(owned):
    service,request,_,_=owned;service.prepare(request);state=service.store.audit()
    with service.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=4')
    assert maintain(service.store)
    assert service.store.recover()==state


@pytest.mark.parametrize('section',SECTIONS)
@pytest.mark.parametrize('damage',['extra','set','delete','marker','duplicate','foreign','descriptor','wrong_hash'])
def test_rehashed_original_event_corruption_fails_all_closures_and_retries(owned,section,damage):
    service,request,_,_=owned;value=service.prepare(request);store=service.store
    key=intent_key(request) if section==SECTIONS[0] else result_key(intent_key(request))
    with store.connect() as db:
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        row=db.execute('SELECT payload FROM events WHERE idempotency_key=?',(key,)).fetchone()
        payload=json.loads(row[0])
        if damage=='extra':payload['extra']=None
        elif damage=='set':payload['set']={}
        elif damage=='delete':payload['delete']=[[section,key]]
        elif damage=='marker':payload['put'].append([section,'',{'wrong':True}])
        elif damage=='duplicate':payload['put'].append(payload['put'][0])
        elif damage=='foreign':payload['put'].append(['sessions','foreign',{}])
        elif damage=='descriptor':payload['put'][0].append(None)
        else:payload['details']='different bytes'
        # Privileged fault injection only into this disposable fixture. Restore
        # the original append-only trigger BEFORE any product path is exercised.
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?',
            (canonical(payload).decode(),sha(payload) if damage!='wrong_hash' else sha('wrong'),key))
        db.execute(trigger)
        db.execute('UPDATE snapshot_due SET due_version=4')
    with pytest.raises((Conflict,ValueError)):store.audit()
    with pytest.raises((Conflict,ValueError)):store.snapshot()
    with pytest.raises((Conflict,ValueError)):service.prepare(request)
    assert maintain(store) is False
    with store.connect() as db:
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()


@pytest.mark.parametrize('damage',['intent_profile','intent_seal','result_material','result_version'])
def test_rehashed_snapshot_cannot_redefine_original_preparation_facts(owned,damage):
    service,request,_,_=owned;service.prepare(request);store=service.store
    state=store.audit();ik=intent_key(request);rk=result_key(ik)
    if damage=='intent_profile':state[SECTIONS[0]][ik]['plan']['profile']['command_seconds']+=1
    elif damage=='intent_seal':state[SECTIONS[0]][ik]['bundle']['seal']['manifest_hash']=digest('wrong')
    elif damage=='result_material':state[SECTIONS[1]][rk]['material']['manifest_hash']=digest('wrong')
    else:state[SECTIONS[1]][rk]['accepted_state_version']=3
    raw=canonical(state)
    with store.connect() as db:
        db.execute('INSERT INTO snapshots VALUES(?,?,?)',(4,raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises(ValueError):store.recover()


@pytest.mark.parametrize('kind',['raw','aliases'])
def test_historical_reads_reject_before_unbounded_parse_or_expansion(owned,monkeypatch,kind):
    service,request,_,_=owned;service.prepare(request);store=service.store
    from rlflow import hybrid_preparation_service as module
    monkeypatch.setattr(module,'TRANSACTION_BYTES',2048)
    with store.connect() as db:
        if kind=='raw':encoded=' '*4096
        else:
            raw=canonical('x'*1000);key=hashlib.sha256(raw).hexdigest()
            db.execute('INSERT INTO blobs VALUES(?,?)',(key,raw))
            # Leave enough raw budget for the first blob. Repeated cached
            # aliases must then exhaust the separate expanded-data envelope.
            encoded=canonical([{'$rlflow_blob':key,'literal':True}]*10).decode()
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',
            (encoded,SECTIONS[0],intent_key(request)))
    parsed=[];parse=ReadBudget.parse
    def bounded(self,raw):
        parsed.append(len(raw));return parse(self,raw)
    monkeypatch.setattr(ReadBudget,'parse',bounded)
    with pytest.raises(Conflict,match='budget'):service.prepare(request)
    assert all(size<=2048 for size in parsed)
    if kind=='raw':assert parsed==[]
    else:assert len(parsed)==2


@pytest.mark.parametrize('domain',['draft','approval'])
def test_historical_retry_requires_original_referenced_sources_even_after_expiry(owned,domain):
    service,request,clock,_=owned;value=service.prepare(request);store=service.store
    clock[0]=timestamp(value['intent']['sources']['expires_at'])
    key=value['intent']['sources']['draft_command_key' if domain=='draft' else 'approval_command_key']
    with store.connect() as db:
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        payload=json.loads(db.execute('SELECT payload FROM events WHERE idempotency_key=?',(key,)).fetchone()[0])
        payload['put'].append(['sessions','unapproved',{}])
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE idempotency_key=?',
                   (canonical(payload).decode(),sha(payload),key));db.execute(trigger)
    with pytest.raises(Conflict):service.prepare(request)
    with pytest.raises(Conflict):service.reconcile(request)


def test_cumulative_budget_accepts_four_mib_literal_projection_and_source_expansion(owned):
    service,_,_,_=owned;store=service.store
    # Marker-looking payload is literal content, not a recursive alias grant.
    value={'text':'x'*(4*1024**2-256),'$rlflow_blob':'not-a-descriptor'}
    raw=canonical(value);key=hashlib.sha256(raw).hexdigest()
    with store.connect() as db:
        db.execute('INSERT INTO blobs VALUES(?,?)',(key,raw))
        budget=ReadBudget(db,64*1024**2)
        descriptor={'$rlflow_blob':key,'literal':True}
        assert budget.decode(descriptor)==value
        assert budget.decode(descriptor)==value
        assert budget.expanded<64*1024**2-7*1024**2


def test_large_legal_literal_result_schema_survives_actual_persistent_closures(owned,monkeypatch):
    service,request,_,_=owned
    from rlflow import execution_adapter as module
    # Valid schema annotations are inert JSON. Store literal encoding expands
    # each marker-looking value, despite the actual schema remaining <4MiB.
    schema={'type':'object','description':'bounded literal encoding capacity fixture',
            'examples':[{'$rlflow_blob':0} for _ in range(180000)]}
    assert len(canonical(schema))<4*1024**2
    monkeypatch.setattr(module,'role_schema',lambda role:schema)
    value=service.prepare(request);store=service.store
    assert value['result']['status']=='PREPARED'
    with store.connect() as db:
        assert db.execute('SELECT MAX(length(data)) FROM blobs').fetchone()[0]>16*1024**2
    state=store.audit();store.snapshot();assert store.recover()==state
    assert service.prepare(request)=={**value,'duplicate':True}
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=4')
    # Optional maintenance retains its explicit total raw+expanded budget;
    # increase it for this pathological but legal encoding capacity fixture.
    assert maintain(store,seconds=30,max_bytes=64*1024**2,max_nodes=8*1024**2)
    assert store.recover()==state


@pytest.mark.parametrize('column',['source_version','projection_version'])
def test_historical_duplicate_requires_consistent_actual_core_tip(owned,column):
    service,request,_,_=owned;service.prepare(request)
    with service.store.connect() as db:
        if column=='source_version':db.execute('UPDATE observation_meta SET source_version=100')
        else:db.execute('UPDATE projection_meta SET version=100')
    with pytest.raises(Conflict,match='source version'):service.prepare(request)


@pytest.mark.parametrize('kind',['aliases','oversize','cycle','deep'])
def test_preparation_replay_uses_bounded_decode_before_transition(owned,monkeypatch,kind):
    service,request,_,_=owned;store=service.store
    state=store.audit();key=intent_key(request)
    from rlflow import store as module
    monkeypatch.setattr(module,'PREPARATION_READ_BYTES',2048 if kind!='deep' else 64*1024**2)
    with store.connect() as db:
        if kind=='cycle':
            blob_key='a'*64;raw=canonical({'$rlflow_blob':blob_key})
            db.execute('INSERT INTO blobs VALUES(?,?)',(blob_key,raw))
        elif kind=='deep':
            raw=canonical({});blob_key=hashlib.sha256(raw).hexdigest()
            db.execute('INSERT INTO blobs VALUES(?,?)',(blob_key,raw))
            # Exceed the interpreter recursion envelope rather than merely
            # reaching the later record-shape rejection with a shallow DAG.
            for _ in range(1200):
                raw=canonical({'$rlflow_blob':blob_key});blob_key=hashlib.sha256(raw).hexdigest()
                db.execute('INSERT INTO blobs VALUES(?,?)',(blob_key,raw))
        else:
            raw=canonical('x'*(1000 if kind=='aliases' else 4096));blob_key=hashlib.sha256(raw).hexdigest()
            db.execute('INSERT INTO blobs VALUES(?,?)',(blob_key,raw))
        value={'$rlflow_blob':blob_key}
        if kind=='aliases':value=[value]*10
        payload={'format':2,'put':[[SECTIONS[0],key,value]],'delete':[],'details':None}
        monkeypatch.setattr(store,'_decode_value',lambda *args:pytest.fail('prep replay used legacy decode'))
        with pytest.raises(Conflict):
            store._apply(state,payload,db,{'event_type':EVENTS[0],'idempotency_key':key,
                'object_id':digest('fixture'),'producer':'hybrid-core','new_state_version':3})
    assert SECTIONS[0] not in state and store.version()==2


def test_preparation_replay_applies_the_already_verified_decoded_payload_once(owned,monkeypatch):
    service,request,_,_=owned;value=service.prepare(request);store=service.store
    state=store.audit();state.pop(SECTIONS[1]);state.pop(SECTIONS[0]);state['version']=2
    with store.connect() as db:
        event=db.execute('SELECT * FROM events WHERE idempotency_key=?',(intent_key(request),)).fetchone()
        monkeypatch.setattr(store,'_decode_value',lambda *args:pytest.fail('prep replay decoded a second time'))
        store._apply(state,json.loads(event['payload']),db,event)
    assert state[SECTIONS[0]][intent_key(request)]==value['intent']
