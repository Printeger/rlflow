import copy
import json
from pathlib import Path
import pytest
from rlflow import engine, model_policy, role_config
from rlflow.store import Conflict, Store, atomic, canonical
from test_engine import harness, deliver


def test_six_defaults_and_role_authority():
    policy=model_policy.load_policy()
    expected={'PI':'medium','Engineer':'medium','Evaluator':'high','Critic':'high','Designer':'medium','Scout':'low'}
    for role,effort in expected.items():
        d=role_config.load_role(role)
        choice=model_policy.select({'compute':model_policy.new_budget(6)},role,policy)
        assert (choice['model'],choice['effort'])==('gpt-5.6-sol',effort)
        assert not {'model','model_reasoning_effort'} & set(d)
        assert d['candidate_access']==('write' if role=='Engineer' else 'read')
    assert not policy['astra']['enabled']


def test_model_in_role_and_permission_expansion_rejected(tmp_path):
    (tmp_path/'roles').mkdir()
    original=(role_config.ROOT/'roles/Critic.toml').read_text()
    p=tmp_path/'roles/Critic.toml'
    p.write_text('model = "gpt-6-astra"\n'+original)
    with pytest.raises(Conflict):role_config.load_role('Critic',tmp_path)
    p.write_text(original.replace('candidate_access = "read"','candidate_access = "write"'))
    with pytest.raises(Conflict):role_config.load_role('Critic',tmp_path)


def test_policy_duplicates_and_scout_astra_rejected(tmp_path):
    p=tmp_path/'policy.yaml';p.write_text('version: 1\nversion: 1')
    with pytest.raises(Conflict):model_policy.load_policy(p)
    policy=model_policy.load_policy();policy.pop('sha256')
    policy['roles']['Scout'].append({'model':'gpt-6-astra','effort':'high'})
    p.write_text(json.dumps(policy))
    with pytest.raises(Conflict):model_policy.load_policy(p)


def test_compute_accounting_is_durable_and_never_refunded(harness):
    h=harness;sid=engine.dispatch_one(h.store)
    s=h.store.replay();se=s['sessions'][sid]
    assert se['compute']['model']=='gpt-5.6-sol'
    assert se['compute']['effort']=='medium'
    b=s['stages']['CPU']['compute']
    assert b['used']=={'sol':0,'astra':0} and b['reserved_seconds']['sol']==5
    assert b['reserved_calls']['sol']==1
    assert se['role_definition']['name']=='PI'
    state=deliver(h,sid,code=7)
    assert state['stages']['CPU']['compute']['used']['sol']==1
    assert state['stages']['CPU']['compute']['reserved_seconds']['sol']==0
    assert state['stages']['CPU']['compute']['used_seconds']['sol']==1
    engine.accept_result(Store(h.store.root),sid)
    assert h.store.replay()==state


def test_unknown_receipt_keeps_compute_reservation(harness):
    h=harness;sid=engine.dispatch_one(h.store)
    state=deliver(h,sid,elapsed=None)
    assert state['stages']['CPU']['compute']['reserved_seconds']['sol']==5
    assert state['stages']['CPU']['compute']['used']['sol']==0
    assert state['stages']['CPU']['compute']['reserved_calls']['sol']==1


def test_tier_budget_blocks_without_spending(harness):
    h=harness
    model_policy.set_budget(h.store,'CPU',0,0,'unit fixture disable compute')
    assert engine.dispatch_one(h.store) is None
    s=h.store.replay()
    assert s['tasks'][h.task_id]['status']=='COMPUTE_BLOCKED'
    assert s['stages']['CPU']['used_calls']==0
    assert not s['sessions']


def test_astra_policy_and_stage_budget_both_required():
    p=model_policy.load_policy();stage={'compute':model_policy.new_budget(4)}
    stage['compute']['limits']['astra']=1
    with pytest.raises(Conflict,match='disabled'):model_policy.select(stage,'Critic',p,1)
    p['astra']['enabled']=True
    stage['compute']['limits']['astra']=0
    with pytest.raises(Conflict,match='exhausted'):model_policy.select(stage,'Critic',p,1)
    stage['compute']['limits']['astra']=1
    assert model_policy.select(stage,'Critic',p,1)['tier']=='astra'


def test_budget_change_cannot_reset_or_exceed(harness):
    h=harness;sid=engine.dispatch_one(h.store)
    with pytest.raises(Conflict,match='active'):model_policy.set_budget(h.store,'CPU',7,1,'active')
    deliver(h,sid)
    with pytest.raises(Conflict):model_policy.set_budget(h.store,'CPU',0,1,'refund')
    with pytest.raises(Conflict):model_policy.set_budget(h.store,'CPU',8,1,'over-allocation')


def test_operator_budget_allocation_releases_only_compute_block(harness):
    h=harness;model_policy.set_budget(h.store,'CPU',0,0,'disable')
    assert engine.dispatch_one(h.store) is None
    model_policy.set_budget(h.store,'CPU',8,0,'explicit restore')
    assert h.store.replay()['tasks'][h.task_id]['status']=='QUEUED'
    assert engine.dispatch_one(h.store)


def test_role_and_model_snapshot_survive_policy_edit(harness,tmp_path,monkeypatch):
    h=harness;sid=engine.dispatch_one(h.store)
    se=h.store.replay()['sessions'][sid]
    path=Path(se['directory'])/'request.json'
    request=json.loads(path.read_text())
    policy=model_policy.load_policy();policy.pop('sha256');policy['roles']['PI'][0]['effort']='low'
    changed=tmp_path/'changed.yaml';changed.write_text(json.dumps(policy));monkeypatch.setattr(model_policy,'POLICY',changed)
    assert json.loads(path.read_text())['compute']==request['compute']
    assert request['compute']['effort']=='medium'
    assert request['role_definition']['sha256']==se['role_definition']['sha256']
    assert Path(request['schema']).is_relative_to(Path(se['directory']))


def test_stale_daemon_cannot_be_silently_reused(harness,monkeypatch):
    from rlflow.jobs import identity
    import os
    h=harness
    atomic(h.store.root/'runtime/daemon.json',canonical(identity(os.getpid())))
    with pytest.raises(Conflict,match='stale code'):engine.ensure_daemon(h.store)
