from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from rlflow.hybrid_goals import propose, SECTIONS, revision_key, head_key, validate_complete
from rlflow.hybrid_protocol import ProtocolError
from rlflow.observation import enable
from rlflow.store import Store, Conflict
from rlflow.web_auth import Principal
from rlflow.contracts import ContractError


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path/'state');enable(store, 'project_fixture', data_mode='fixture')
    proposal = json.loads(Path('docs/rlflow_hybrid_spec_v1/examples/goal.fixture.json').read_text())
    actor = Principal('fixture_operator', 'agent', frozenset({'operator'}), frozenset({'project_fixture'}))
    return store, proposal, actor


def submit(setup, *, key='first', expected=0, proposal=None, actor=None, project='project_fixture', mode='fixture'):
    store, original, principal = setup
    return propose(store, original if proposal is None else proposal, principal=principal if actor is None else actor,
        project_id=project, data_mode=mode, idempotency_key=key, expected_revision=expected)


def test_persistent_draft_is_not_execution_authority(setup):
    store, proposal, actor = setup;before = store.replay();result = submit(setup)
    assert result['contract']['state']=='DRAFT' and result['contract']['approval_id'] is None
    assert result['accepted_state_version']==1 and not result['duplicate']
    after = store.replay();assert all(after[k]==v for k,v in before.items() if k!='version')
    assert all(section not in store.view() for section in SECTIONS)
    assert len(store.objects(SECTIONS[0]))==len(store.objects(SECTIONS[1]))==len(store.objects(SECTIONS[2]))==1
    assert store.audit()==after
    proposal['objective']='Caller mutation must not rewrite an immutable persisted draft.'
    assert store.get(SECTIONS[0],revision_key(proposal))['contract']['proposal']['objective']!=proposal['objective']


def test_retry_returns_original_receipt_after_other_revisions(setup):
    store, proposal, actor = setup;first = submit(setup)
    second = deepcopy(proposal);second['contract_version']=2;second['objective']+=' 新版本。'
    changed = submit(setup,key='second',expected=1,proposal=second)
    retry = submit(setup)
    assert changed['accepted_state_version']==2 and retry['accepted_state_version']==1
    assert retry['duplicate'] and retry['contract']==first['contract'] and store.version()==2
    old = store.get(SECTIONS[0],revision_key(proposal));new = store.get(SECTIONS[0],revision_key(second))
    assert old['contract']==first['contract'] and new['previous_hash']==first['contract']['hash']
    assert {r['path'] for r in new['changes']}=={'/contract_version','/objective'}


def test_same_key_different_content_rejected_atomically(setup):
    store, p, actor = setup;submit(setup)
    changed=deepcopy(p);changed['objective']+=' Different payload.'
    with pytest.raises(Conflict,match='idempotency'):submit(setup,proposal=changed)
    next_p=deepcopy(p);next_p['contract_version']=2
    with pytest.raises(Conflict,match='idempotency'):submit(setup,expected=1,proposal=next_p)
    assert store.version()==1


def test_concurrent_same_key_different_payload_has_one_winner(setup):
    store,p,actor=setup;changed=deepcopy(p);changed['objective']+=' Another proposal.'
    def run(value):
        try:return submit(setup,proposal=value)
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[p,changed]))
    assert results.count('conflict')==1 and store.version()==1


def test_concurrent_head_revisions_have_one_winner(setup):
    store,p,actor=setup;submit(setup);p=deepcopy(p);p['contract_version']=2
    def run(key):
        try:return submit(setup,key=key,expected=1,proposal=p)
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['revision-a','revision-b']))
    assert results.count('conflict')==1 and store.version()==2 and len(store.objects(SECTIONS[0]))==2


@pytest.mark.parametrize('field,value',[('approval_status','APPROVED'),('approved_by','human'),('approval_id','approved'),('state','READY')])
def test_input_cannot_forge_approval(setup,field,value):
    store,p,actor=setup;p[field]=value
    with pytest.raises(ProtocolError):submit(setup)
    assert store.version()==0


def test_unscoped_viewer_and_json_actor_cannot_submit(setup):
    store,p,actor=setup
    for principal in [Principal('viewer','human',{'viewer'},{'project_fixture'}),Principal('other','agent',{'operator'},{'elsewhere'}),{'id':actor.id,'kind':'human','roles':['approver']}]:
        with pytest.raises(ProtocolError,match='operator'):submit(setup,actor=principal)
    assert store.version()==0


def test_registered_project_and_mode_required(setup,tmp_path):
    store,p,actor=setup
    with pytest.raises(ProtocolError):submit(setup,mode='live')
    other=Store(tmp_path/'other');enable(other,'other_project',data_mode='fixture')
    with pytest.raises(ProtocolError):submit((other,p,actor))
    empty=Store(tmp_path/'empty')
    with pytest.raises(ProtocolError):submit((empty,p,actor))
    assert store.version()==other.version()==empty.version()==0


@pytest.mark.parametrize('mutation',['rewrite','delete','head','receipt'])
def test_generic_transactions_cannot_rewrite_or_delete_drafts(setup,mutation):
    store,p,actor=setup;submit(setup);rk=revision_key(p);hk=head_key('project_fixture','fixture',p['goal_id'])
    command=store.objects(SECTIONS[2])[0][0];selected=[(SECTIONS[0],rk),(SECTIONS[1],hk),(SECTIONS[2],command)]
    def change(s):
        if mutation=='rewrite':s[SECTIONS[0]][rk]['submitted_by']['id']='forged'
        elif mutation=='delete':del s[SECTIONS[0]][rk]
        elif mutation=='head':s[SECTIONS[1]][hk]['contract_hash']='sha256:'+'0'*64
        else:s[SECTIONS[2]][command]['accepted_state_version']=999
    with pytest.raises((Conflict,ProtocolError)):store.transact_objects('FORGED_DRAFT','bad',selected,change)
    assert store.version()==1 and store.audit()==store.replay()


def test_snapshot_recover_and_legacy_control_keep_all_draft_records(setup):
    store,p,actor=setup;submit(setup);store.snapshot()
    store.transact('PAUSE_FIXTURE','pause-fixture',lambda s:s.update(paused=True))
    expected=store.replay();assert store.recover()==store.audit()==expected
    assert len(expected[SECTIONS[0]])==1 and expected['paused']


def test_failed_commit_rolls_back_all_three_objects(setup,monkeypatch):
    from rlflow import observation
    store,p,actor=setup
    def failed(*args):raise RuntimeError('injected bridge failure')
    monkeypatch.setattr(observation,'commit',failed)
    with pytest.raises(RuntimeError,match='injected'):submit(setup)
    assert store.version()==0 and all(not store.objects(section) for section in SECTIONS)


@pytest.mark.parametrize('kind',['large','duplicate_condition','nan','path','integer'])
def test_bounded_input_failures_do_not_echo_secrets(setup,kind):
    store,p,actor=setup;secret='sensitive-text-should-not-appear'
    if kind=='large':p['objective']=secret*10000
    elif kind=='duplicate_condition':p['global_conditions'].append(deepcopy(p['global_conditions'][0]))
    elif kind=='nan':p['budget']['finalization_reserve_fraction']=float('nan')
    elif kind=='path':p['scope']['writable_paths']=[secret+'/../escape']
    else:p['budget']['model_sessions']=2**64
    with pytest.raises(ProtocolError) as error:submit(setup)
    assert secret not in str(error.value) and store.version()==0


def test_complete_snapshot_rejects_corrupt_links(setup):
    store,p,actor=setup;submit(setup);state=store.replay()
    with store.connect() as db:validate_complete(state,('project_fixture','fixture'),lambda k:store._goal_event(db,k),lambda k:store._goal_source(db,k))
    for section in SECTIONS:
        bad=deepcopy(state);bad[section].clear()
        with store.connect() as db:
            with pytest.raises(Conflict):validate_complete(bad,('project_fixture','fixture'),lambda k:store._goal_event(db,k),lambda k:store._goal_source(db,k))


def test_generic_record_validation_enforces_request_byte_cap(setup):
    from rlflow.hybrid_goals import digest
    store,p,actor=setup;submit(setup);ck=store.objects(SECTIONS[2])[0][0]
    def oversized(s):
        receipt=s[SECTIONS[2]][ck];proposal=receipt['request']['proposal']
        template=proposal['global_conditions'][0]
        proposal['global_conditions']=[{**deepcopy(template),'id':f'C{i}','description':'x'*4000} for i in range(100)]
        receipt['request_hash']=digest(receipt['request']);receipt['contract_hash']=digest(proposal)
    with pytest.raises(ContractError,match='bounded input'):
        store.transact_objects('HYBRID_GOAL_DRAFTED','oversize',[(SECTIONS[2],ck)],oversized,producer='hybrid-core')
    assert store.version()==1


@pytest.mark.parametrize('bad',['head','receipt','registration'])
def test_periodic_snapshot_rejects_incomplete_drafts_without_clearing_due(setup,bad):
    from rlflow.snapshot_maintenance import maintain
    store,p,actor=setup;submit(setup)
    with store.connect() as db:
        db.execute('UPDATE snapshot_due SET due_version=1')
        if bad=='registration':db.execute("UPDATE observation_meta SET project_id='wrong_project'")
        else:db.execute('DELETE FROM projection WHERE section=?',(SECTIONS[1] if bad=='head' else SECTIONS[2],))
    assert not maintain(store)
    with store.connect() as db:
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone())==(1,0)
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()


def test_periodic_snapshot_and_recovery_preserve_complete_draft(setup):
    from rlflow.snapshot_maintenance import maintain
    store,p,actor=setup;submit(setup)
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=1')
    assert maintain(store) and store.recover()==store.audit()==store.replay()


@pytest.mark.parametrize('bad',['missing','wrong_version'])
def test_retry_rejects_missing_or_corrupt_original_receipt(setup,bad):
    from rlflow.store import canonical
    store,p,actor=setup;submit(setup);ck,receipt=store.objects(SECTIONS[2])[0]
    with store.connect() as db:
        if bad=='missing':db.execute('DELETE FROM projection WHERE section=? AND object_key=?',(SECTIONS[2],ck))
        else:
            receipt['accepted_state_version']=999
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(receipt).decode(),SECTIONS[2],ck))
    with pytest.raises(Conflict,match='receipt'):submit(setup)
    assert store.version()==1


def test_recovery_rejects_wrong_original_receipt_version_even_below_snapshot_version(setup):
    import hashlib
    from rlflow.store import canonical
    store,p,actor=setup;submit(setup)
    store.transact('FIXTURE_PROGRESS','progress',lambda s:s.update(paused=True));store.snapshot()
    with store.connect() as db:
        state=json.loads(db.execute('SELECT state FROM snapshots WHERE version=2').fetchone()[0])
        next(iter(state[SECTIONS[2]].values()))['accepted_state_version']=2
        raw=canonical(state)
        db.execute('UPDATE snapshots SET state=?,sha256=? WHERE version=2',(raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises(Conflict,match='original core event'):store.recover()


def test_periodic_snapshot_rejects_wrong_original_receipt_version(setup):
    from rlflow.snapshot_maintenance import maintain
    from rlflow.store import canonical
    store,p,actor=setup;submit(setup)
    store.transact('FIXTURE_PROGRESS','progress',lambda s:s.update(paused=True))
    ck,receipt=store.objects(SECTIONS[2])[0];receipt['accepted_state_version']=2
    with store.connect() as db:
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(receipt).decode(),SECTIONS[2],ck))
        db.execute('UPDATE snapshot_due SET due_version=2')
    assert not maintain(store)
    with store.connect() as db:
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone())==(2,0)
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()


@pytest.mark.parametrize('missing_marker',[False,True])
def test_existing_collection_marker_in_new_goal_commit_is_rejected(setup,monkeypatch,missing_marker):
    store,p,actor=setup;submit(setup);before=store.audit()
    if missing_marker:
        with store.connect() as db:
            for section in SECTIONS:db.execute("DELETE FROM projection WHERE section=? AND object_key=''",(section,))
    original=store._commit
    def repeated(db,event_type,key,payload,*args):
        existing={(s,k) for s,k,v in payload['put']}
        payload={**payload,'put':payload['put']+[[s,'',{}] for s in SECTIONS if (s,'') not in existing]}
        return original(db,event_type,key,payload,*args)
    monkeypatch.setattr(store,'_commit',repeated)
    changed=deepcopy(p);changed['goal_id']='goal_second'
    with pytest.raises(Conflict,match='marker'):submit(setup,key='second-goal',proposal=changed)
    assert store.version()==1 and store.audit()==before


def test_historical_replay_rejects_repeated_collection_markers(setup):
    from rlflow.store import canonical, sha
    store,p,actor=setup;submit(setup)
    changed=deepcopy(p);changed['goal_id']='goal_second';submit(setup,key='second-goal',proposal=changed)
    with store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM events WHERE seq=2').fetchone()[0])
        payload['put'].extend([[s,'',{}] for s in SECTIONS])
        # Deliberate corruption of this disposable fixture only. The production
        # append-only trigger is not relaxed by the implementation.
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET payload=?,payload_sha256=? WHERE seq=2',(canonical(payload).decode(),sha(payload)))
    with pytest.raises(Conflict,match='marker'):store.audit()
    with pytest.raises(Conflict,match='marker'):store.recover()


def test_retry_checks_core_producer_as_well_as_hash_and_version(setup):
    store,p,actor=setup;submit(setup)
    with store.connect() as db:
        db.execute('DROP TRIGGER no_update')
        db.execute("UPDATE events SET producer='forged-producer' WHERE seq=1")
    with pytest.raises(Conflict,match='receipt'):submit(setup)
    assert store.version()==1
