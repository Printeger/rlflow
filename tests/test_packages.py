import copy
import json
import pytest
from rlflow import engine, packages, policy, cli
from rlflow.store import Conflict
from test_engine import harness, deliver, result_for


def specification(h):
    return {'id': 'PKG', 'goal': 'complete independent CPU conditions', 'repo': str(h.repo),
            'module_roots': ['.'], 'protected_paths': ['.git'], 'budget': {'role_calls': 15},
            'tasks': [{'id': name, 'text': 'verify ' + name, 'depends_on': deps,
                       'criteria': [{'id': 'C-' + name, 'description': 'parser accepts valid inputs', 'layer': 'cpu'}]}
                      for name, deps in [('a', []), ('b', ['a']), ('c', [])]]}


def approved(h, spec=None):
    h.store.transact('FIXTURE_RESET', 'reset-package', lambda s: s.update(tasks={}, stages={}, paused=True))
    spec = spec or specification(h)
    pid = packages.propose(h.store, spec)
    shown = policy.show_proposal(h.store, pid)
    policy.decide(h.store, pid, shown['sha256'], 'APPROVED', 'test only')
    return h.store.replay()['packages']['PKG']


def step(h, verdict='PASS'):
    sid = engine.dispatch_one(h.store)
    assert sid is not None
    state = h.store.replay();se = state['sessions'][sid];h.task_id = se['task_id'];task=state['tasks'][h.task_id]
    result = result_for(h, sid, verdict)
    if se['role'] == 'PI':
        result['payload']['task_interpretation'].update(stage_id='PKG',
            budget=state['stages']['PKG']['budget'], acceptance_criteria=[c['id'] for c in task['criteria']])
    elif se['role'] == 'Engineer':
        result['payload']['changes'] = []
    elif se['role'] == 'Evaluator':
        result['payload']['evidence_coverage'] = [c['id'] for c in task['criteria']]
        for f in result['payload']['findings']:
            f.update(contract=task['criteria'][0]['id'], evidence_refs=[next(iter(state['evidence']))])
    return deliver(h, sid, result)


def test_one_approval_dependency_graph_completes_and_replays(harness):
    h=harness;p=approved(h)
    assert h.store.replay()['stages']['PKG']['budget']['wall_seconds']==54000
    for i in range(9): state=step(h)
    assert state['packages']['PKG']['status']=='DONE'
    assert state['goals']['PKG']['status']=='DONE'
    assert all(state['tasks'][tid]['status']=='DONE' for tid in p['tasks'])
    assert len(state['approvals'])==1 and state['stages']['PKG']['used_calls']==9
    assert state['stages']['PKG']['reserved_calls']==0
    assert engine.dispatch_one(h.store) is None
    assert h.store.rebuild()==state


def test_blocked_branch_does_not_block_independent_work(harness):
    h=harness;p=approved(h);a,b,c=p['tasks']
    h.store.transact('FIXTURE_BLOCK','block',lambda s:s['tasks'][a].update(status='CONTRACT_DECISION'))
    for _ in range(3):state=step(h)
    assert state['tasks'][c]['status']=='DONE'
    assert state['tasks'][b]['status']=='QUEUED'
    assert engine.dispatch_one(h.store) is None
    assert state['stages']['PKG']['used_calls']==3


def test_package_pause_resume_and_read_only_status(harness,capsys,monkeypatch):
    h=harness;approved(h)
    packages.pause(h.store,'PKG',True)
    assert engine.dispatch_one(h.store) is None
    before=h.store.replay()
    monkeypatch.setattr(engine,'reconcile',lambda *_:pytest.fail('status must not reconcile'))
    assert cli.main(['--state-dir',str(h.store.root),'status'])==0
    assert h.store.replay()==before
    packages.pause(h.store,'PKG',False)
    assert engine.dispatch_one(h.store)


def test_pi_cannot_rewrite_package_acceptance(harness):
    h=harness;approved(h);sid=engine.dispatch_one(h.store)
    h.task_id=h.store.replay()['sessions'][sid]['task_id']
    state=deliver(h,sid,result_for(h,sid))
    assert state['sessions'][sid]['status']=='REJECTED'
    assert state['tasks'][h.task_id]['status']=='CONTRACT_DECISION'


def test_cpu_never_proves_real_or_formal_conditions(harness):
    h=harness;spec=specification(h);spec['tasks']=spec['tasks'][:1]
    spec['tasks'][0]['criteria'][0]['layer']='real_run';approved(h,spec)
    for _ in range(3):state=step(h)
    assert state['packages']['PKG']['status']=='ACTIVE'
    assert state['tasks'][h.task_id]['status']=='CONTRACT_DECISION'
    assert not state['tasks'][h.task_id]['completion']['real_run']


@pytest.mark.parametrize('mutation',[
    lambda s:s['tasks'][0]['depends_on'].append('b'),
    lambda s:s['tasks'][0]['depends_on'].append('missing'),
    lambda s:s['tasks'][0]['criteria'].clear(),
    lambda s:s['budget'].update(role_calls=True),
    lambda s:s.update(command_seconds=1801),
    lambda s:s.update(extra_authority=True)])
def test_invalid_package_never_creates_proposal(harness,mutation):
    spec=specification(harness);mutation(spec)
    with pytest.raises(Conflict):packages.propose(harness.store,spec)
    assert not harness.store.replay()['proposals']


def test_package_scope_revocation_and_rejected_rename(harness):
    from rlflow.authorizations import revoke
    h=harness;p=approved(h)
    revoke(h.store,p['approval_id'],'test')
    assert engine.dispatch_one(h.store) is None
    with pytest.raises(Conflict):packages.pause(h.store,'PKG',False)


def test_stored_task_contract_drift_is_rejected(harness):
    h=harness;p=approved(h);tid=p['tasks'][0]
    h.store.transact('FIXTURE_DRIFT','criteria-drift',lambda s:s['tasks'][tid]['criteria'][0].update(description='lower acceptance'))
    with pytest.raises(Conflict,match='conditions drifted'):engine.dispatch_one(h.store)


def test_reconcile_never_submits_new_experiments(harness,monkeypatch):
    from rlflow import experiments
    h=harness;p=approved(h);tid=p['tasks'][0]
    h.store.transact('FIXTURE_WAIT','wait-job',lambda s:s['tasks'][tid].update(status='WAITING_EXPERIMENT',experiment_request='pending'))
    monkeypatch.setattr(experiments,'submit',lambda *_:pytest.fail('reconcile must not dispatch'))
    before=h.store.replay();assert engine.reconcile(h.store)==before


def test_new_control_rollback_does_not_restore_historical_role_entries(harness,monkeypatch):
    from rlflow import migration
    h=harness;approved(h);before=h.store.replay()
    monkeypatch.setattr(migration,'atomic',lambda *_:pytest.fail('historical entries must remain unchanged'))
    result=migration.rollback(h.store)
    assert result['stages']==before['stages'] and result['approvals']==before['approvals']
    assert result['paused'] and not result['enabled'] and not result['autonomous_tasks']


def test_repeated_output_with_cosmetic_candidate_changes_routes_to_critic(harness):
    h=harness;approved(h);step(h)
    for n in range(2):
        sid=engine.dispatch_one(h.store);h.task_id=h.store.replay()['sessions'][sid]['task_id']
        (h.repo/'parser.py').write_text(f'def parse(value):\n    return value  # style {n}\n')
        result=result_for(h,sid);result['payload']['self_tests']=[]
        state=deliver(h,sid,result)
    task=state['tasks'][h.task_id]
    assert task['status']=='QUEUED' and task['next_role']=='Critic'
    assert task['continuation_requires_evidence'] and not task['last_failure']['blocked']
    assert state['stages']['PKG']['used_calls']==3


def test_optional_exact_control_release_cannot_drift(harness,monkeypatch):
    from rlflow import verification
    from rlflow.store import Conflict
    h=harness;v=specification(h);v['control_release']=verification.code_identity()
    p=approved(h,v)
    monkeypatch.setattr(verification,'code_identity',lambda:'0'*64)
    with pytest.raises(Conflict,match='control release'):packages.require_package(h.store.replay(),h.store.replay()['stages']['PKG'])
