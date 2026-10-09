"""Original-source-bound renewal, actual unknown COMMIT and memory ACK."""
from datetime import timedelta
from contextlib import contextmanager
import json
import threading

import pytest

from rlflow.store import Store,Conflict
from rlflow.hybrid_workspace import SECTIONS,fact_key,head_key
from rlflow.hybrid_working_copy import PendingRenewal
from tests.test_hybrid_workspace_service import (workspace,admission,owned,prepared,
    native_setup,close_request)
from tests.test_hybrid_budget_service import cleanup


def renewal(request):
    return {**request,'operation':'renew','idempotency_key':'actual-renewal',
            'expected_state_version':7,'expected_workspace_revision':1}


def test_actual_renewal_same_fd_epoch_and_full_history(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    held=service.working._slot(old)[0]['hold'];pending=service.prepare_renewal(old)
    assert service.working.check(old)['epoch']==1
    with pytest.raises(PermissionError):service.working.check(pending.candidate)
    result=service.record(renewal(request),token,pending);new=pending.candidate
    assert result['fact']['observation']==json.loads(new.raw)
    assert service.working.check(new)['epoch']==2 and service.working._slot(new)[0]['hold'] is held
    assert service._slots[request['workspace_id']]['observation'] is new
    assert not service.working._renewals
    assert service.ack_renewal(fact_key(renewal(request)),pending) is new
    assert service.ack_renewal(fact_key(renewal(request)),pending) is new
    assert service.record(renewal(request),token,pending)['duplicate']
    state=service.store.audit();assert state==service.store.replay()
    service.store.snapshot();assert Store(service.store.root).recover()==state


def test_before_commit_failure_explicit_abort_retains_original_fd(workspace,monkeypatch):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);before=service.store.audit();original=service.store._commit
    def fault(*args,**kwargs):original(*args,**kwargs);raise Conflict('before actual SQL commit')
    monkeypatch.setattr(service.store,'_commit',fault)
    with pytest.raises(Conflict,match='before actual'):service.record(renewal(request),token,pending)
    monkeypatch.undo()
    assert service.store.audit()==before and service.working.check(old)['epoch']==1
    assert service.abort_renewal(pending) is old and not service.working._renewals


def test_actual_commit_unknown_return_then_expired_ack_and_new_lineage_close(workspace,monkeypatch):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);original=service.store.connect
    class Connection:
        def __init__(self,db):self.db=db
        def __getattr__(self,name):return getattr(self.db,name)
        def __enter__(self):self.db.__enter__();return self
        def __exit__(self,*args):return self.db.__exit__(*args)
        def commit(self):self.db.commit();raise Conflict('unknown actual commit return')
    monkeypatch.setattr(service.store,'connect',lambda:Connection(original()))
    with pytest.raises(Conflict,match='unknown actual'):service.record(renewal(request),token,pending)
    monkeypatch.undo()
    assert service.store.version()==8 and service.working.check(old)['epoch']==1
    with pytest.raises(Conflict,match='event exists'):service.abort_renewal(pending)
    # Actual clocks, not a caller TTL assertion; ACK needs historical proof
    # and Kernel hold but does not revive the expired candidate.
    clock=[service.controller.clock()+timedelta(seconds=31)];mono=[service.controller.monotonic_ns()+31*10**9]
    service.controller.clock=lambda:clock[0];service.controller.monotonic_ns=lambda:mono[0]
    service.working._clock=lambda:clock[0];service.working._monotonic_ns=lambda:mono[0]
    new=service.ack_renewal(fact_key(renewal(request)),pending)
    with pytest.raises(Conflict,match='expired'):service.working.check(new)
    # Original Controller also expires at30s. Obtain a real fresh fence, not
    # a fabricated long-lived token; workspace cleanup keeps original lineage.
    fresh=service.controller.acquire('cleanup-controller',expected_version=8)
    token=fresh['token']
    closing=close_request(request,'request_close',9,2);service.record(closing,token,new)
    witness=service.close_physical_pre_runtime(fact_key(closing),new)
    assert witness.observation is new
    complete=close_request(request,'complete_close',10,3);service.record(complete,token,new)
    assert service.store.get(SECTIONS[1],head_key(request))['state']=='CLOSED_PRE_RUNTIME'
    assert service.store.audit()==service.store.replay()


@pytest.mark.parametrize('field',['observation','witness','renewal_ack','renewal'])
def test_each_partial_service_memory_assignment_retries_original_pending(workspace,field):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);original=service._slots[request['workspace_id']]
    class FaultSlot(dict):
        fired=False
        def __setitem__(self,key,value):
            super().__setitem__(key,value)
            if key==field and not self.fired:
                self.fired=True;raise MemoryError('partial service '+field)
    service._slots[request['workspace_id']]=FaultSlot(original)
    with pytest.raises(MemoryError,match='partial service'):service.record(renewal(request),token,pending)
    assert service.store.version()==8
    new=service.ack_renewal(fact_key(renewal(request)),pending)
    assert new is pending.candidate and service.working.check(new)['epoch']==2
    assert service.ack_renewal(fact_key(renewal(request)),pending) is new


def test_foreign_pending_does_not_parse_or_replace_actual_stage(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);fake=PendingRenewal(pending.id,None,None)
    try:
        with pytest.raises(PermissionError):service.record(renewal(request),token,fake)
        with pytest.raises(PermissionError):service.ack_renewal(fact_key(renewal(request)),fake)
        assert service.store.version()==7
    finally:service.abort_renewal(pending)


@pytest.mark.parametrize('field',['workspace_id','reservation_id','goal_ref'])
def test_rejected_request_scope_cannot_poison_original_pending_retry_or_abort(workspace,field):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);correct=renewal(request)
    wrong={**correct,field:'wrong_'+field}
    with pytest.raises((Conflict,PermissionError)):service.record(wrong,token,pending)
    assert service.store.version()==7 and service.working.check(old)['epoch']==1
    assert service._slots[request['workspace_id']]['renewal']['request'] is None
    if field=='workspace_id':
        assert service.abort_renewal(pending) is old
    else:
        service.record(correct,token,pending)
        assert service.working.check(pending.candidate)['epoch']==2


def test_actual_repeated_renewals_refresh_original_material_outside_writer(workspace,monkeypatch):
    service,request,token,current,_=workspace;service.record(request,token,current)
    original_witness=service._slots[request['workspace_id']]['witness']
    clock=[service.controller.clock()];mono=[service.controller.monotonic_ns()]
    service.controller.clock=lambda:clock[0];service.controller.monotonic_ns=lambda:mono[0]
    service.working._clock=lambda:clock[0];service.working._monotonic_ns=lambda:mono[0]
    service.preparation.clock=lambda:clock[0];service.preparation._witness_monotonic_ns=lambda:mono[0]
    verify=service.preparation.builder.verify;probed=[]
    def outside_writer(snapshot):
        with service.store.lock(nonblocking=True):probed.append(snapshot.id)
        return verify(snapshot)
    monkeypatch.setattr(service.preparation.builder,'verify',outside_writer)
    held=service.working._slot(current)[0]['hold']
    for index in range(2):
        clock[0]+=timedelta(seconds=20);mono[0]+=20*10**9
        fresh=service.controller.renew(token,'renew-controller-'+str(index),expected_version=service.store.version())
        token=fresh['token'];pending=service.prepare_renewal(current)
        command={**renewal(request),'idempotency_key':'renew-workspace-'+str(index),
                 'expected_state_version':service.store.version(),'expected_workspace_revision':index+1}
        service.record(command,token,pending);current=pending.candidate
        assert service.working.check(current)['epoch']==index+2
        assert service.working._slot(current)[0]['hold'] is held
    latest=service._slots[request['workspace_id']]['witness']
    assert latest is not original_witness and latest.materials is original_witness.materials
    assert latest.issued_monotonic_ns==mono[0] and len(probed)==2
    assert service.store.audit()==service.store.replay()


@pytest.mark.parametrize('fault',['working_attach_after','service_attach_before'])
def test_lost_prepare_canonical_pending_blocks_close_until_actual_recovery(workspace,fault):
    service,request,token,old,_=workspace;service.record(request,token,old)
    class FaultRegistry(dict):
        fired=False
        def __setitem__(self,key,value):
            super().__setitem__(key,value)
            if not self.fired:self.fired=True;raise MemoryError('lost working attach')
    class FaultSlot(dict):
        fired=False
        def __setitem__(self,key,value):
            if key=='renewal' and not self.fired:
                self.fired=True;raise MemoryError('lost service attach')
            super().__setitem__(key,value)
    if fault=='working_attach_after':service.working._renewals=FaultRegistry()
    else:service._slots[request['workspace_id']]=FaultSlot(service._slots[request['workspace_id']])
    with pytest.raises(MemoryError,match='lost'):service.prepare_renewal(old)
    assert service._slots[request['workspace_id']]['renewal'] is None
    retained=service.working.pending_renewal(old)
    assert type(retained) is PendingRenewal
    closing=close_request(request,'request_close',7,1)
    with pytest.raises(Conflict,match='unresolved'):service.record(closing,token,old)
    assert service.store.version()==7
    assert service.prepare_renewal(old) is retained
    assert service.abort_renewal(retained) is old
    service.record(closing,token,old)
    service.close_physical_pre_runtime(fact_key(closing),old)
    service.record(close_request(request,'complete_close',8,2),token,old)
    assert service.store.audit()==service.store.replay()


@pytest.mark.parametrize('action',['CANCEL_BEFORE_RUNTIME','MARK_UNKNOWN'])
def test_budget_wins_before_renewal_no_candidate_commit_or_automatic_fd_close(workspace,action):
    service,request,token,old,budget_request=workspace;service.record(request,token,old)
    held=service.working._slot(old)[0]['hold'];pending=service.prepare_renewal(old)
    service.budget.record(cleanup(budget_request,action,version=7),token)
    attempted={**renewal(request),'expected_state_version':8}
    with pytest.raises(Conflict):service.record(attempted,token,pending)
    assert service.store.version()==8 and not held._closed
    assert service.abort_renewal(pending) is old
    # Original historical HELD workspace source permits conservative cleanup,
    # without treating current CANCELLED/UNKNOWN reservation as new authority.
    closing=close_request(request,'request_close',8,1);service.record(closing,token,old)
    service.close_physical_pre_runtime(fact_key(closing),old)
    service.record(close_request(request,'complete_close',9,2),token,old)
    assert service.store.audit()==service.store.replay()


def test_writer_wait_old_deadline_cannot_revive_into_longer_candidate(workspace,monkeypatch):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old,ttl_seconds=60);original=service.store.lock
    main=threading.get_ident();waiting=threading.Event();outcomes=[]
    mono=[service.working._monotonic_ns()];service.working._monotonic_ns=lambda:mono[0]
    @contextmanager
    def lock(*args,**kwargs):
        if threading.get_ident()!=main:waiting.set()
        with original(*args,**kwargs):yield
    monkeypatch.setattr(service.store,'lock',lock)
    def attempt():
        try:service.record({**renewal(request),'ttl_seconds':60},token,pending)
        except BaseException as exc:outcomes.append(exc)
    with original():
        thread=threading.Thread(target=attempt);thread.start();assert waiting.wait(timeout=5)
        mono[0]+=31*10**9
    thread.join(timeout=10);assert not thread.is_alive()
    assert len(outcomes)==1 and isinstance(outcomes[0],Conflict)
    assert service.store.version()==7 and not service.working._slot(old)[0]['hold']._closed
    assert service.controller.check_token(token)['execution_enabled'] is False
    assert mono[0]<pending.candidate.expires_monotonic_ns # specifically OLD expiry
    assert service.abort_renewal(pending) is old


def test_helper_retire_after_delete_failure_service_retains_original_ack(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old)
    class FaultRegistry(dict):
        fired=False
        def __delitem__(self,key):
            super().__delitem__(key)
            if not self.fired:self.fired=True;raise MemoryError('helper retired return lost')
    service.working._renewals=FaultRegistry(service.working._renewals)
    with pytest.raises(MemoryError,match='helper retired'):service.record(renewal(request),token,pending)
    assert service.store.version()==8 and not service.working._renewals
    assert service._slots[request['workspace_id']]['renewal']['pending'] is pending
    assert service.ack_renewal(fact_key(renewal(request)),pending) is pending.candidate
    assert service.working.check(pending.candidate)['epoch']==2


def test_two_real_threads_same_pending_have_one_fact_winner_no_abba(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);ready=threading.Barrier(2);outcomes=[]
    def attempt(index):
        try:
            ready.wait(timeout=5)
            outcomes.append(service.record({**renewal(request),'idempotency_key':'race-'+str(index)},token,pending))
        except BaseException as exc:outcomes.append(exc)
    threads=[threading.Thread(target=attempt,args=(index,)) for index in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=10);assert not thread.is_alive()
    assert len(outcomes)==2 and sum(type(result) is dict for result in outcomes)==1
    assert sum(isinstance(result,(Conflict,PermissionError)) for result in outcomes)==1
    assert service.store.version()==8 and service.working.check(pending.candidate)['epoch']==2
    assert service.store.audit()==service.store.replay()


def test_close_requested_head_wins_before_new_renewal_fact(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    closing=close_request(request,'request_close',7,1);service.record(closing,token,old)
    pending=service.prepare_renewal(old)
    with pytest.raises(Conflict):service.record({**renewal(request),'expected_state_version':8,
                                               'expected_workspace_revision':2},token,pending)
    assert service.store.version()==8 and service.abort_renewal(pending) is old
    service.close_physical_pre_runtime(fact_key(closing),old)
    service.record(close_request(request,'complete_close',8,2),token,old)
    assert service.store.audit()==service.store.replay()


def test_historical_duplicate_foreign_pending_is_only_receipt(workspace):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);command=renewal(request);service.record(command,token,pending)
    raw=pending.candidate.raw;expires=pending.candidate.expires_monotonic_ns
    fake=PendingRenewal(pending.id,None,None)
    result=service.record(command,token,fake)
    assert result['duplicate'] and not result['execution_enabled'] and not result['release_enabled']
    with pytest.raises(PermissionError):service.ack_renewal(fact_key(command),fake)
    current=service._slots[request['workspace_id']]['observation']
    assert current is pending.candidate and current.raw==raw and current.expires_monotonic_ns==expires


def test_ack_original_kernel_check_failure_retains_actual_pending(workspace,monkeypatch):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old)
    def fail_activation(*args):raise Conflict('activation before swap')
    with monkeypatch.context() as patch:
        patch.setattr(service,'_activate_renewal',fail_activation)
        with pytest.raises(Conflict,match='activation before'):service.record(renewal(request),token,pending)
    def failed_kernel(*args,**kwargs):raise Conflict('injected original Kernel proof failure')
    with monkeypatch.context() as patch:
        patch.setattr(service.working,'check_renewal',failed_kernel)
        with pytest.raises(Conflict,match='original Kernel'):service.ack_renewal(fact_key(renewal(request)),pending)
    assert service.working.pending_renewal(old) is pending
    assert service.ack_renewal(fact_key(renewal(request)),pending) is pending.candidate


def test_ack_rejects_actual_original_event_metadata_corruption(workspace,monkeypatch):
    service,request,token,old,_=workspace;service.record(request,token,old)
    pending=service.prepare_renewal(old);command=renewal(request);key=fact_key(command)
    def fail_activation(*args):raise Conflict('activation before swap')
    with monkeypatch.context() as patch:
        patch.setattr(service,'_activate_renewal',fail_activation)
        with pytest.raises(Conflict,match='activation before'):service.record(command,token,pending)
    with service.store.connect() as db:
        original=db.execute('SELECT input_versions FROM events WHERE idempotency_key=?',(key,)).fetchone()[0]
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='no_update'").fetchone()[0]
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET input_versions=? WHERE idempotency_key=?',('[]',key))
        db.execute(trigger);db.commit()
    try:
        with pytest.raises(Conflict):service.ack_renewal(key,pending)
        assert service.working.pending_renewal(old) is pending
    finally:
        # Disposable fixture only: restore original bytes/trigger, never a
        # product repair or disk adoption of the candidate/held FD.
        with service.store.connect() as db:
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET input_versions=? WHERE idempotency_key=?',(original,key))
            db.execute(trigger);db.commit()
    assert service.ack_renewal(key,pending) is pending.candidate
    assert service.store.audit()==service.store.replay()
