"""CPU-only tests of durable state and authorization; no model calls or runtime."""
import copy
import json
import sqlite3
from pathlib import Path
import pytest
from rlflow.store import Store, Conflict, canonical, sha
from rlflow import policy, engine, migration
from rlflow.contracts import ContractError, validate_runtime_event, validate_runtime_state, classify_change


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'research')


@pytest.fixture
def demo(store):
    migration.seed_demo(store)
    return store


def test_event_replay_and_atomic_projections(store):
    store.transact('PAUSED','pause1',lambda s:s.update(paused=True),expected=0)
    store.transact('RESUMED','resume1',lambda s:s.update(paused=False),expected=1)
    expected=store.replay()
    store.export()
    (store.root/'state/RESEARCH_STATE.json').write_text('broken projection')
    assert store.rebuild()==expected
    store.export()
    assert json.loads((store.root/'state/RESEARCH_STATE.json').read_text())==expected
    rows=[json.loads(line) for line in (store.root/'events/events.jsonl').read_text().splitlines()]
    assert [row['seq'] for row in rows]==[1,2]
    for row in rows: validate_runtime_event(row)
    validate_runtime_state(expected)


def test_transaction_exception_rolls_back_all_mutations(store):
    def interrupted(s):
        s['paused']=True
        s['historical']['reserved']=42
        raise RuntimeError('injected interruption before commit')
    with pytest.raises(RuntimeError):store.transact('INTERRUPTED','first',interrupted)
    assert store.replay()['version']==0
    assert store.replay()['historical']=={}
    assert not store.replay()['paused']


def test_commit_survives_export_interruption(store,monkeypatch):
    export=store._export
    def fail(*args): raise OSError('injected power loss before projection write')
    monkeypatch.setattr(store,'_export',fail)
    store.transact('PAUSED','pause1',lambda s:s.update(paused=True))
    with pytest.raises(OSError):store.export()
    assert store.replay()['version']==1 and store.replay()['paused']
    monkeypatch.setattr(store,'_export',export)
    assert store.rebuild()['version']==1


def test_duplicate_event_never_repeats_reservation(store):
    calls=[]
    def reserve(s):
        calls.append(1);s['historical']['consumed']=1
    first=store.transact('RESERVE','same',reserve,expected=0)
    second=store.transact('RESERVE','same',reserve,expected=0)
    assert first==second and len(calls)==1
    with pytest.raises(Conflict):store.transact('OTHER','same',reserve)
    with pytest.raises(Conflict):store.transact('RESERVE','same',reserve,object_id='different')


def test_stale_version_rejects_without_mutation(store):
    store.transact('PAUSED','one',lambda s:s.update(paused=True))
    with pytest.raises(Conflict,match='stale'):
        store.transact('RESUMED','two',lambda s:s.update(paused=False),expected=0)
    assert store.replay()['paused'] and store.replay()['version']==1


def test_history_append_only_sql_triggers(store):
    store.transact('PAUSED','one',lambda s:s.update(paused=True))
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError,match='append only'):db.execute('DELETE FROM events')
        with pytest.raises(sqlite3.IntegrityError,match='append only'):db.execute("UPDATE events SET event_type='OTHER'")


def proposal(demo,sid='CPU-SECOND'):
    repo=demo.root/'workspaces/budget-parser-demo'
    return policy.make_proposal(demo,sid,repo,'Fix parser CPU only',{'role_calls':2,'wall_seconds':60,'fake_starts':1})


def test_approval_requires_exact_shown_hash_and_candidate(demo):
    pid=proposal(demo);digest=demo.replay()['proposals'][pid]['sha256']
    with pytest.raises(Conflict,match='show'):policy.decide(demo,pid,digest,'APPROVED','test')
    policy.show_proposal(demo,pid)
    with pytest.raises(Conflict,match='exact'):policy.decide(demo,pid,'0'*64,'APPROVED','test')
    (demo.root/'workspaces/budget-parser-demo/task_config.py').write_text('changed after shown')
    with pytest.raises(Conflict,match='candidate changed'):policy.decide(demo,pid,digest,'APPROVED','test')
    assert 'CPU-SECOND' not in demo.replay()['stages']


@pytest.mark.parametrize('tamper',['hash','version','budget','revocation','scope','module','protected'])
def test_approval_binding_rechecked_before_dispatch(demo,tamper):
    pid=proposal(demo);shown=policy.show_proposal(demo,pid)
    policy.decide(demo,pid,shown['sha256'],'APPROVED','test')
    state=demo.replay();stage=policy.require_stage(state,'CPU-SECOND');approval=state['approvals'][stage['approval_id']]
    if tamper=='hash':state['proposals'][pid]['content']['task']='new scope'
    elif tamper=='version':state['proposals'][pid]['version']+=1
    elif tamper=='budget':stage['budget']['wall_seconds']+=1
    elif tamper=='revocation':approval['revoked']=True
    elif tamper=='scope':approval['scope']='SANDBOX_ONLY'
    elif tamper=='module':stage['module_roots']=['../']
    else:stage['protected_paths']=[]
    with pytest.raises(Conflict):policy.require_stage(state,'CPU-SECOND')


def test_rejected_proposal_does_not_authorize(demo):
    pid=proposal(demo);shown=policy.show_proposal(demo,pid)
    policy.decide(demo,pid,shown['sha256'],'REJECTED','insufficient scope')
    with pytest.raises(Conflict):policy.require_stage(demo.replay(),'CPU-SECOND')


def test_proposal_binds_module_roots_and_read_only_cpu_runtime(demo, tmp_path):
    repo=demo.root/'workspaces/budget-parser-demo'
    runtime=tmp_path/'runtime';runtime.mkdir()
    python=runtime/'python';python.write_bytes(b'fixed-cpu-python')
    python.chmod(0o755)
    pid=policy.make_proposal(
        demo,'CPU-SCOPED',repo,'scoped CPU repair',
        {'role_calls':3,'wall_seconds':90,'fake_starts':0},
        module_roots=['task_config.py'],protected_paths=['.git','CONTRACT.md'],
        cpu_runtime_root=runtime,cpu_python=python)
    shown=policy.show_proposal(demo,pid)
    content=shown['content']
    assert content['module_roots']==['task_config.py']
    assert content['protected_paths']==['.git','CONTRACT.md']
    assert content['cpu_runtime']['root']==str(runtime)
    assert content['cpu_runtime']['address_space_bytes']==8*1024**3
    policy.decide(demo,pid,shown['sha256'],'APPROVED','test')
    stage=policy.require_stage(demo.replay(),'CPU-SCOPED')
    assert stage['cpu_runtime']==content['cpu_runtime']
    python.write_bytes(b'drift')
    with pytest.raises(Conflict,match='identity changed'):
        policy.require_stage(demo.replay(),'CPU-SCOPED')


@pytest.mark.parametrize('root', ['/absolute', '../escape', 'missing'])
def test_proposal_rejects_invalid_or_missing_module_roots(demo, root):
    repo=demo.root/'workspaces/budget-parser-demo'
    with pytest.raises(Conflict):
        policy.make_proposal(demo,'CPU-BAD-'+root.replace('/','x'),repo,'bad scope',
                             {'role_calls':1,'wall_seconds':10,'fake_starts':0},module_roots=[root])


def test_stage_budget_exhaustion_is_cumulative(demo,monkeypatch):
    from rlflow import isolation
    monkeypatch.setattr(isolation,'require_doctor',lambda root:None)
    monkeypatch.setattr(engine,'stopped',lambda root:[])
    tid=engine.add_task(demo,'CPU-DEMO','parser')
    demo.transact('FIXTURE_CONSUMPTION','used',lambda s:s['stages']['CPU-DEMO'].update(used_calls=6))
    assert engine.dispatch_one(demo) is None
    state=demo.replay()
    assert state['tasks'][tid]['status']=='BUDGET_EXHAUSTED'
    assert state['stages']['CPU-DEMO']['used_calls']==6
    assert not state['sessions']
    with pytest.raises(Conflict):engine.add_task(demo,'CPU-DEMO','another task does not reset limits')


def test_stage_extension_preserves_usage_and_requeues_only_evaluator(demo):
    pid=proposal(demo,'CPU-EXTENSION')
    shown=policy.show_proposal(demo,pid)
    policy.decide(demo,pid,shown['sha256'],'APPROVED','fixture base approval')
    tid=engine.add_task(demo,'CPU-EXTENSION','parser review')
    def exhaust(s):
        s['stages']['CPU-EXTENSION'].update(used_calls=2,used_seconds=31)
        s['tasks'][tid].update(status='BUDGET_EXHAUSTED',next_role='Evaluator')
    demo.transact('FIXTURE_EXTENSION_BOUNDARY','exhaust extension fixture',exhaust)
    before=demo.replay();old_version=before['tasks'][tid]['version']
    extension=policy.make_extension_proposal(
        demo,'CPU-EXTENSION',tid,1,600,'one independent evaluator retry')
    extension_shown=policy.show_proposal(demo,extension)
    content=extension_shown['content']
    assert content['recorded_budget']=={'role_calls':2,'wall_seconds':60,'fake_starts':1}
    assert content['recorded_usage']=={
        'used_calls':2,'used_seconds':31,'reserved_seconds':0,'used_fake_starts':0}
    assert content['additional_budget']=={'role_calls':1,'wall_seconds':600,'fake_starts':0}
    assert content['additional_compute']=={'sol':1,'astra':0}
    policy.decide(demo,extension,extension_shown['sha256'],'APPROVED','fixture extension approval')
    state=demo.replay();stage=policy.require_stage(state,'CPU-EXTENSION');task=state['tasks'][tid]
    assert stage['budget']=={'role_calls':3,'wall_seconds':660,'fake_starts':1}
    assert (stage['used_calls'],stage['used_seconds'])==(2,31)
    assert len(stage['approval_extensions'])==1
    assert task['status']=='QUEUED' and task['next_role']=='Evaluator'
    assert task['version']==old_version+1
    tampered=copy.deepcopy(state)
    tampered['proposals'][extension]['content']['additional_budget']['role_calls']=2
    with pytest.raises(Conflict,match='extension approval invalid'):
        policy.require_stage(tampered,'CPU-EXTENSION')


def test_unknown_consumption_is_not_zero(demo):
    state=demo.replay();state['stages']['CPU-DEMO']['used_seconds']=None
    with pytest.raises(Conflict,match='unknown'):policy.require_stage(state,'CPU-DEMO')


def test_stop_prevents_dispatch_without_budget_reservation(demo):
    engine.add_task(demo,'CPU-DEMO','parser')
    (demo.root/'STOP').write_text('test canonical local STOP')
    assert engine.dispatch_one(demo) is None
    assert demo.replay()['stages']['CPU-DEMO']['used_calls']==0


def test_runtime_schema_rejects_broken_models_and_hashes(demo):
    state=demo.replay();validate_runtime_state(state)
    invalid=copy.deepcopy(state);invalid['stages']['CPU-DEMO']['budget']['role_calls']=-1
    with pytest.raises(ContractError):validate_runtime_state(invalid)
    with demo.connect() as db:row=dict(db.execute('SELECT * FROM events LIMIT 1').fetchone())
    validate_runtime_event(row)
    row['payload_sha256']='0'*64
    with pytest.raises(ContractError):validate_runtime_event(row)


def test_mixed_change_requires_every_approved_category(tmp_path):
    change={'path':str(tmp_path/'implementation.py'),'categories':['ENGINEERING_FIX','EVALUATION_CHANGE'],'review_categories':['ENGINEERING_FIX','EVALUATION_CHANGE'],'contract_ref':'frozen-v1'}
    kwargs={'module_roots':[str(tmp_path)],'candidate':{'head':'a'},'diff_sha256':'a'*64}
    result=classify_change([change],['ENGINEERING_FIX'],**kwargs)
    assert result['status']=='APPROVAL_REQUIRED' and result['unauthorized']==['EVALUATION_CHANGE']
    change['review_categories']=['ENGINEERING_FIX']
    assert classify_change([change],['ENGINEERING_FIX','EVALUATION_CHANGE'],**kwargs)['status']=='UNRESOLVED'
