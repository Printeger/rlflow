"""Approval-driven stage loops; all role workers are simulated, no model calls."""
import pytest
from rlflow import engine, policy, cli
from rlflow.store import Conflict
from test_engine import harness, deliver, result_for, implement


def approve_loop(h, calls=6):
    def reset(s):
        s['tasks']={};s['stages']={};s['paused']=True
    h.store.transact('FIXTURE_LOOP','fixture-loop',reset)
    pid=policy.make_proposal(h.store,'CPU',h.repo,'reject invalid budgets',
                             {'role_calls':calls,'wall_seconds':60,'fake_starts':0},stage_loop=True)
    shown=policy.show_proposal(h.store,pid)
    assert not h.store.replay()['sessions'] and not h.store.replay()['tasks']
    policy.decide(h.store,pid,shown['sha256'],'APPROVED','bounded stage test')
    h.task_id=next(iter(h.store.replay()['tasks']))
    return pid,shown


def test_approve_creates_task_and_runs_rework_without_start_or_resume(harness):
    h=harness;approve_loop(h)
    assert h.store.replay()['paused']  # other manual tasks stay paused
    assert h.store.replay()['autonomous_tasks']==[h.task_id]
    deliver(h,engine.dispatch_one(h.store))
    implement(h)
    sid=engine.dispatch_one(h.store)
    deliver(h,sid,result_for(h,sid,'FAIL'))
    implement(h)
    state=deliver(h,engine.dispatch_one(h.store))
    assert state['tasks'][h.task_id]['status']=='DONE'
    assert state['stages']['CPU']['used_calls']==5
    assert state['stages']['CPU']['compute']['used']=={'sol':5,'astra':0}
    assert engine.dispatch_one(h.store) is None
    assert len(h.store.rebuild()['sessions'])==5


def test_loop_stops_at_total_budget_and_never_refunds(harness):
    h=harness;approve_loop(h,calls=3)
    deliver(h,engine.dispatch_one(h.store));implement(h)
    sid=engine.dispatch_one(h.store);deliver(h,sid,result_for(h,sid,'FAIL'))
    for _ in range(3):assert engine.dispatch_one(h.store) is None
    s=h.store.replay()
    assert s['tasks'][h.task_id]['status']=='BUDGET_EXHAUSTED'
    assert s['stages']['CPU']['used_calls']==3
    assert len(s['sessions'])==3


def test_loop_stop_and_explicit_pause_do_not_launch(harness):
    h=harness;approve_loop(h)
    (h.store.root/'STOP').write_text('stop')
    assert engine.dispatch_one(h.store) is None
    (h.store.root/'STOP').unlink()
    assert cli.main(['--state-dir',str(h.store.root),'pause'])==0
    assert h.store.replay()['autonomous_tasks']==[]
    assert engine.dispatch_one(h.store) is None
    assert not h.store.replay()['sessions']


def test_loop_does_not_wake_unrelated_paused_task(harness):
    h=harness;other=h.task_id
    pid=policy.make_proposal(h.store,'SECOND',h.repo,'bounded second task',
                             {'role_calls':3,'wall_seconds':60,'fake_starts':0},stage_loop=True)
    shown=policy.show_proposal(h.store,pid)
    h.store.transact('FIXTURE_PAUSED','paused',lambda s:s.update(paused=True))
    policy.decide(h.store,pid,shown['sha256'],'APPROVED','test')
    sid=engine.dispatch_one(h.store)
    s=h.store.replay()
    assert s['sessions'][sid]['stage_id']=='SECOND'
    assert s['tasks'][other]['status']=='QUEUED'


def test_extension_pool_keeps_usage_and_starts_selected_role(harness):
    h=harness
    h.store.transact('FIXTURE_USAGE','usage',lambda s:s['stages']['CPU'].update(used_calls=2,used_seconds=3))
    pid=policy.make_extension_proposal(h.store,'CPU',h.task_id,6,1800,'review and rework reserve',
                                        stage_loop=True,next_role='Evaluator')
    shown=policy.show_proposal(h.store,pid)
    policy.decide(h.store,pid,shown['sha256'],'APPROVED','test')
    s=h.store.replay()
    assert s['stages']['CPU']['budget']['role_calls']==14
    assert s['stages']['CPU']['used_calls']==2
    assert s['stages']['CPU']['used_seconds']==3
    assert s['tasks'][h.task_id]['next_role']=='Evaluator'
    assert s['autonomous_tasks']==[h.task_id]
    policy.decide(h.store,pid,shown['sha256'],'APPROVED','repeat')
    assert h.store.replay()['stages']['CPU']['budget']['role_calls']==14


def test_loop_approval_cli_starts_daemon_once_without_second_start(harness,monkeypatch):
    h=harness
    pid=policy.make_proposal(h.store,'SECOND',h.repo,'one bounded task',
                             {'role_calls':3,'wall_seconds':60,'fake_starts':0},stage_loop=True)
    shown=policy.show_proposal(h.store,pid);started=[]
    monkeypatch.setattr(engine,'ensure_daemon',lambda store:started.append(str(store.root)))
    assert cli.main(['--state-dir',str(h.store.root),'approve',pid,'--sha256',shown['sha256']])==0
    assert started==[str(h.store.root)]
    tid=next(t['id'] for t in h.store.replay()['tasks'].values() if t['stage_id']=='SECOND')
    before=h.store.replay()['tasks'][tid]
    assert engine.add_task(h.store,'SECOND','one bounded task')==tid
    assert h.store.replay()['tasks'][tid]==before


@pytest.mark.parametrize('calls,seconds',[(0,100),(101,100),(1,86401),(True,100)])
def test_extension_rejects_invalid_limits(harness,calls,seconds):
    with pytest.raises(Conflict):
        policy.make_extension_proposal(harness.store,'CPU',harness.task_id,calls,seconds,'test',stage_loop=True)


def test_contract_block_cannot_be_bypassed_by_loop_budget(harness):
    h=harness
    h.store.transact('FIXTURE_CONTRACT','contract',lambda s:s['tasks'][h.task_id].update(status='CONTRACT_DECISION'))
    with pytest.raises(Conflict,match='resolve the contract'):
        policy.make_extension_proposal(h.store,'CPU',h.task_id,6,1800,'test',stage_loop=True)


def test_committed_approval_recovers_daemon_start_failure_without_extra_task(harness,monkeypatch):
    h=harness
    pid=policy.make_proposal(h.store,'SECOND',h.repo,'recover after daemon error',
                             {'role_calls':4,'wall_seconds':60,'fake_starts':0},stage_loop=True)
    shown=policy.show_proposal(h.store,pid)
    def fail(store):raise OSError('fixture daemon failure')
    monkeypatch.setattr(engine,'ensure_daemon',fail)
    args=['--state-dir',str(h.store.root),'approve',pid,'--sha256',shown['sha256']]
    assert cli.main(args)==2
    before=h.store.rebuild()
    monkeypatch.setattr(engine,'ensure_daemon',lambda store:None)
    assert cli.main(args)==0
    assert h.store.replay()==before
    assert len(before['autonomous_tasks'])==1
    assert before['stages']['SECOND']['used_calls']==0


def test_stage_loop_candidate_drift_stops_without_spending(harness):
    h=harness;approve_loop(h)
    (h.repo/'parser.py').write_text('outside change')
    assert engine.dispatch_one(h.store) is None
    s=h.store.replay()
    assert s['tasks'][h.task_id]['status']=='CONTRACT_DECISION'
    assert s['stages']['CPU']['used_calls']==0


def test_extra_budget_cannot_retry_unchanged_infrastructure_failure(harness):
    h=harness
    h.store.transact('FIXTURE_INFRA','infra',lambda s:s['tasks'][h.task_id].update(
        status='INFRASTRUCTURE_ERROR',last_failure={'blocked':True}))
    with pytest.raises(Conflict,match='infrastructure'):
        policy.make_extension_proposal(h.store,'CPU',h.task_id,6,1800,'more calls',stage_loop=True)
