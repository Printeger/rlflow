"""Finite sequence flow harness. No actual Source/model/account qualification."""
import json
import threading
from types import SimpleNamespace

import pytest

from rlflow.hybrid_a_engineering_sequence import run,stop
from rlflow.store import Conflict


@pytest.fixture(autouse=True)
def synthetic_harness_creator(monkeypatch):
    # All owners below are deliberately fabricated flow DATA, not capabilities.
    monkeypatch.setattr('rlflow.hybrid_a_engineering_sequence._creator',lambda owner:None)


def harness(fault='none',demand=True):
    calls=[];budget=SimpleNamespace();membership=object()
    pool=SimpleNamespace(snapshot=lambda:{'version':1},
        claim=lambda *a,**k:calls.append('claim') or object())
    spec={'continuation_task':{'task_id':'next','objective':'Explicit demand'}} if demand else {}
    plans=SimpleNamespace(registry=SimpleNamespace(_raw=json.dumps({'tools':{'native_model':{'definition':{'spec':spec}}}})))
    def make(name):
        task=SimpleNamespace(id=name,raw=b'SYNTHETIC_NOT_QUALIFIED')
        current=SimpleNamespace(name=name,task=task,budget=budget,pool=pool,membership=membership,plans=plans,
            _actual=lambda:None,_unit_check=lambda attempt:None,_check_launch=lambda *a:None,
            _workflow_cpu_admission_lock=threading.RLock(),_safety_freeze=False,_live=True,
            store=SimpleNamespace(version=lambda:10))
        current.sources=SimpleNamespace(_live=True)
        current.controller=SimpleNamespace(_refuse_nested_writer=lambda:None,
            renew=lambda *a,**k:calls.append('renew') or {'token':object()})
        def model(*args,**kwargs):
            assert not current._workflow_cpu_admission_lock._is_owned()
            calls.append(name+'_run')
            if name=='reviewer' and fault in ('unknown','cleanup_fail'):raise Conflict('TEST original usage unknown')
            return {'SYNTHETIC_UNIT_ONLY':True,'result':{'review':{'verdict':'REVISE' if fault=='revise' else 'ACCEPT'}}}
        current.run_workflow_native=model
        current._issued=lambda lease:{'lease':lease}
        def shutdown():
            calls.append(name+'_stop')
            if fault=='cleanup_fail':raise OSError('TEST unresolved STOP')
            current._live=False;current._safety_freeze=True
            current.sources._live=False
        current.shutdown=shutdown
        current.shutdown_safety=lambda:calls.append(name+'_safety')
        current.register=lambda *a,**k:calls.append(name+'_register') or task
        current.prepare_workflow_reviewer_plan=lambda *a:(object(),object())
        current.issue_workflow_reviewer_grant=lambda *a:object()
        current.prepare_workflow_continuation_plan=lambda *a:(object(),object())
        current.issue_workflow_continuation_grant=lambda *a:object()
        return current
    engineer,cpu,reviewer,next_owner=map(make,('engineer','cpu','reviewer','continuation'))
    engineer._workflow_engineering_lock=threading.Lock()
    engineer._workflow_engineering_sequence=None;engineer._workflow_engineering_completed=None
    engineer._workflow_engineering_root=None;engineer._workflow_engineering_stop=threading.Event()
    engineer._workflow_engineering_stop_ack=None
    engineer._issued=lambda lease:{'token':object(),'origin':{'native_model':{'workflow':{
        'stage':'FIRST_ENGINEER','accounting_version':'A_REGISTRATION_CEILINGS_V1',
        'envelope_sha256':'sha256:'+'a'*64}}}}
    engineer.prepare_workflow_cpu_input=lambda *a:object()
    def handoff(old,new):
        calls.append(old.name+'_handoff');old._live=False;budget._fixture_runtime=new
        if new is next_owner and fault=='lost_install':raise OSError('TEST installed child return lost')
        return new
    engineer.handoff_workflow_cpu=lambda *a,**k:handoff(engineer,cpu)
    cpu._workflow_cpu_sequence={'lease':cpu.task}
    def execute(*args):
        assert not cpu._workflow_cpu_admission_lock._is_owned()
        calls.append('cpu_run')
        return {'machine_acceptance':{'status':'FAIL' if fault=='cpu_fail' else 'PASS'},
            'execution':{'status':'SUCCEEDED'}}
    cpu.execute_workflow_cpu=execute
    cpu.prepare_workflow_reviewer_input=lambda *a:object()
    cpu.handoff_workflow_reviewer=lambda *a,**k:handoff(cpu,reviewer)
    def accept(*a,**k):calls.append('accept');return {'SYNTHETIC_UNIT_ONLY':True}
    reviewer.accept_workflow_conditions=accept
    reviewer.prepare_workflow_continuation_input=lambda *a:object()
    reviewer.handoff_workflow_continuation=lambda *a,**k:handoff(reviewer,next_owner)
    budget._fixture_runtime=engineer
    def issuer(current,task):
        assert task is current.task;calls.append(current.name+'_launch')
        if fault=='stop_at_launch':current._safety_freeze=True
        return object()
    return engineer,issuer,calls


@pytest.mark.parametrize('fault,status,reason',[
    ('none','ACCEPTED_AND_CONTINUED','ORIGINAL_CONDITION_ACCEPTANCE_AND_ONE_NEXT_RUN'),
    ('cpu_fail','NOT_ACCEPTED','CPU_CHECKS_FAILED'),
    ('revise','NOT_ACCEPTED','REVIEWER_NOT_ACCEPTED')])
def test_finite_flow_results_not_test_counts_and_no_automatic_repair(fault,status,reason):
    owner,issuer,calls=harness(fault)
    result=run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert result['status']==status and result['reason']==reason
    assert not result['goal_completed'] and not result['repair_dispatched']
    assert calls.count('engineer_run')==calls.count('cpu_run')==1
    assert calls.count('reviewer_run')==(fault!='cpu_fail')
    assert calls.count('accept')==calls.count('continuation_run')==(fault=='none')
    count=len(calls)
    with pytest.raises(Conflict,match='no redispatch'):run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert len(calls)==count


def test_no_demand_accepts_original_task_without_inventing_a_next_task():
    owner,issuer,calls=harness(demand=False)
    result=run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert result['status']=='ACCEPTED' and result['reason']=='NO_EXPLICIT_CONTINUATION_DEMAND'
    assert 'accept' in calls and 'continuation_launch' not in calls


@pytest.mark.parametrize('fault',['unknown','cleanup_fail','stop_at_launch','lost_install'])
def test_failure_or_stop_never_accepts_redispatches_or_cleans_retired_parent(fault):
    owner,issuer,calls=harness(fault)
    with pytest.raises((Conflict,OSError)) as caught:
        run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert owner._workflow_engineering_sequence['phase']=='FAILED'
    assert owner._workflow_engineering_completed is None
    assert 'continuation_run' not in calls and 'engineer_stop' not in calls and 'cpu_stop' not in calls
    assert ('continuation_stop' if fault=='lost_install' else 'reviewer_stop') in calls
    if fault=='cleanup_fail':
        assert 'TEST original usage unknown' in str(caught.value)
        assert caught.value.__notes__==['Original A owner STOP incomplete: OSError']
        assert 'reviewer_safety' in calls
    if fault!='lost_install':assert 'accept' not in calls
    count=len(calls)
    with pytest.raises(Conflict,match='no redispatch'):run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert len(calls)==count


def test_no_implicit_launch_issuer_and_invalid_original_launch_does_not_latch():
    owner,issuer,calls=harness()
    with pytest.raises(TypeError):run(owner,owner.task,launch=object(),launch_issuer=None)
    def invalid(*args):raise PermissionError('TEST foreign launch')
    owner._check_launch=invalid
    with pytest.raises(PermissionError):run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert owner._workflow_engineering_sequence is None and calls==[]


def test_held_authorized_issuer_does_not_hold_admission_or_block_stop():
    owner,_,calls=harness();entered=threading.Event();release=threading.Event();stopped=threading.Event()
    errors=[];captured=[]
    def held_issuer(current,task):
        assert not current._workflow_cpu_admission_lock._is_owned()
        captured.append(current);entered.set()
        assert release.wait(3),'TEST issuer barrier timeout'
        return object()
    def execute():
        try:run(owner,owner.task,launch=object(),launch_issuer=held_issuer)
        except BaseException as error:errors.append(error)
    worker=threading.Thread(target=execute);worker.start()
    stopper=None
    try:
        assert entered.wait(3),'TEST no issuer entry'
        current=captured[0]
        def stop():
            from rlflow.hybrid_a_engineering_sequence import stop as root_stop
            result=root_stop(owner)
            assert result['stop_latched'] and result['new_work_enabled'] is False
            stopped.set()
        stopper=threading.Thread(target=stop);stopper.start()
        assert stopped.wait(1),'STOP waited for external issuer'
        assert not release.is_set() and 'reviewer_run' not in calls
    finally:
        release.set();worker.join(3)
        if stopper is not None:stopper.join(3)
    assert not worker.is_alive() and not stopper.is_alive()
    assert len(errors)==1 and isinstance(errors[0],Conflict)
    assert 'reviewer_run' not in calls and 'accept' not in calls
    assert owner._workflow_engineering_sequence['phase']=='FAILED'
    assert owner._workflow_engineering_stop.is_set() and not owner._live


def test_original_root_stop_remains_valid_after_successful_handoffs():
    owner,issuer,calls=harness()
    run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert not owner._live and owner.budget._fixture_runtime.name=='continuation'
    result=stop(owner)
    assert result['stop_latched'] and not result['new_work_enabled']
    assert 'continuation_stop' in calls and 'engineer_stop' not in calls
    count=len(calls);assert stop(owner)==result;assert len(calls)==count


def test_pre_entry_stop_is_permanent_and_does_not_invoke_model_or_issuer():
    owner,issuer,calls=harness()
    assert stop(owner)['stop_latched']
    with pytest.raises(Conflict,match='permanently stopped'):
        run(owner,owner.task,launch=object(),launch_issuer=issuer)
    assert calls==['engineer_stop'] and owner._workflow_engineering_sequence is None


def test_safety_retired_flag_or_lost_shutdown_return_is_not_normal_stop_ack():
    for fault in ('retired','lost_return'):
        owner,issuer,calls=harness()
        run(owner,owner.task,launch=object(),launch_issuer=issuer)
        current=owner.budget._fixture_runtime
        if fault=='retired':
            current._live=False;current.sources._live=False
        else:
            normal=current.shutdown
            def lost():normal();raise OSError('TEST shutdown return lost')
            current.shutdown=lost
            with pytest.raises(OSError):stop(owner)
        result=stop(owner)
        assert result['status']=='UNKNOWN' and not result['normal_stop_confirmed']
        assert owner._workflow_engineering_stop_ack is None and not result['new_work_enabled']
