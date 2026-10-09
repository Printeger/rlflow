"""Actual source-bound workspace commits and finite pre-runtime cleanup."""
import json
from datetime import timedelta
import threading

import pytest

from rlflow.hybrid_workspace import SECTIONS,fact_key,head_key
from rlflow.hybrid_workspace_service import WorkspaceService
from rlflow.hybrid_working_copy import WorkingCopyOwner,WorkingCopyObservation
from rlflow.hybrid_workspace_kernel import DirectoryHold
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.hybrid_budget import zero
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_controller_service import ControllerService
from rlflow.hybrid_preparation import intent_key
from rlflow.hybrid_authority import timestamp
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Store,Conflict,canonical,sha
from tests.test_hybrid_budget_service import actual,cleanup
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def workspace(admission,tmp_path):
    budget,command,token=actual(admission);budget.record(command,token)
    prep=budget.preparation;namespace=tmp_path/'actual-workspaces';namespace.mkdir(mode=0o700)
    working=WorkingCopyOwner(prep.builder,namespace,clock=budget.controller.clock,
        monotonic_ns=budget.controller.monotonic_ns)
    service=WorkspaceService(prep.store,prep.registry,budget.controller,prep,budget,working)
    observation=service.stage(command['preparation_intent_key']);raw=json.loads(observation.raw)
    request={n:command[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    request.update({'idempotency_key':'workspace-acquire','expected_state_version':6,'expected_workspace_revision':0,
        'workspace_id':raw['workspace_id'],'reservation_id':reservation_key(command),'operation':'acquire','ttl_seconds':30})
    try:yield service,request,token,observation,command
    finally:
        for slot in tuple(working._issued.values()):working.close_pre_runtime(slot['observation'])
        for witness in tuple(working._closed_witnesses.values()):working.retire_closed_witness(witness)


def close_request(original,operation,version,revision):
    request={**original,'idempotency_key':'workspace-'+operation,'operation':operation,
        'expected_state_version':version,'expected_workspace_revision':revision}
    request.pop('ttl_seconds',None)
    return request


def test_actual_acquire_audit_replay_snapshot_recover_not_execution(workspace):
    service,request,token,observation,_=workspace
    result=service.record(request,token,observation)
    assert result['fact']['state']=='HELD_PRE_RUNTIME' and not result['execution_enabled'] and not result['release_enabled']
    state=service.store.audit();assert state==service.store.replay()
    service.store.snapshot();assert Store(service.store.root).recover()==state
    assert not service.store.objects('sessions') and not service.store.objects('jobs')
    assert service.record(request,token,observation)=={**result,'duplicate':True}


def test_close_is_durable_request_then_actual_fd_close_then_completion(workspace):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    requested=close_request(request,'request_close',7,1);service.record(requested,token,observation)
    assert service.store.get(SECTIONS[1],head_key(request))['state']=='CLOSE_REQUESTED'
    completed=close_request(request,'complete_close',8,2)
    before=service.store.audit()
    with pytest.raises((Conflict,PermissionError)):service.record(completed,token,observation)
    assert service.store.audit()==before
    witness=service.close_physical_pre_runtime(fact_key(requested),observation)
    assert service.working.check_closed_witness(witness)['state']=='CLOSED_PRE_RUNTIME'
    result=service.record(completed,token,observation)
    assert result['fact']['state']=='CLOSED_PRE_RUNTIME' and not service.working._closed_witnesses
    state=service.store.audit();assert state==service.store.replay()
    service.store.snapshot();assert Store(service.store.root).recover()==state
    assert service.record(completed,token,observation)=={**result,'duplicate':True}


def test_failed_acquire_commit_retains_actual_fd_and_no_persistent_fact(workspace,monkeypatch):
    service,request,token,observation,_=workspace;before=service.store.audit()
    original=service.store._commit
    def fault(*args,**kwargs):original(*args,**kwargs);raise Conflict('disposable after-write fault')
    monkeypatch.setattr(service.store,'_commit',fault)
    with pytest.raises(Conflict,match='after-write'):service.record(request,token,observation)
    assert service.store.audit()==before and service._active is None and service.controller._token_active is None
    slot=service.working._issued[request['workspace_id']]
    with pytest.raises(Conflict):DirectoryHold(slot['copy'].path)
    assert service.working.check(observation)['execution_enabled'] is False


def test_cancelled_budget_rejects_current_acquire_without_releasing_fd(workspace):
    service,request,token,observation,budget_request=workspace
    service.budget.record(cleanup(budget_request,'CANCEL_BEFORE_RUNTIME'),token)
    request={**request,'expected_state_version':7};before=service.store.audit()
    with pytest.raises(Conflict):service.record(request,token,observation)
    assert service.store.audit()==before
    slot=service.working._issued[request['workspace_id']]
    with pytest.raises(Conflict):DirectoryHold(slot['copy'].path)


@pytest.mark.parametrize('section',SECTIONS)
def test_generic_write_to_workspace_domain_denied_before_idempotency(workspace,section):
    service,_,_,_,_=workspace;before=service.store.audit()
    with pytest.raises(PermissionError):
        service.store.transact_objects('FAKE','bypass',[(section,'fake')],
            lambda state:state.setdefault(section,{}).update(fake={}),expected=6)
    assert service.store.audit()==before


def test_forged_actual_type_or_foreign_stage_refused(workspace):
    service,request,token,observation,_=workspace
    fake=WorkingCopyObservation(observation.id,b'['*3000,observation.issued_monotonic_ns,observation.expires_monotonic_ns)
    with pytest.raises(PermissionError):service.record(request,token,fake)
    assert service.store.version()==6


def test_physical_close_before_durable_request_is_refused(workspace):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    with pytest.raises(Conflict):service.close_physical_pre_runtime(fact_key(request),observation)
    assert service.working.check(observation)['state']=='HELD_PRE_RUNTIME'


@pytest.mark.parametrize('phase',['request','completion'])
def test_close_commit_failure_retains_held_fd_or_actual_closed_witness(workspace,monkeypatch,phase):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    requested=close_request(request,'request_close',7,1)
    if phase=='completion':
        service.record(requested,token,observation)
        witness=service.close_physical_pre_runtime(fact_key(requested),observation)
        command=close_request(request,'complete_close',8,2)
    else:command=requested
    before=service.store.audit();commit=service.store._commit
    def fault(*args,**kwargs):commit(*args,**kwargs);raise Conflict('disposable close commit fault')
    monkeypatch.setattr(service.store,'_commit',fault)
    with pytest.raises(Conflict,match='close commit fault'):service.record(command,token,observation)
    assert service.store.audit()==before and service._active is None and service.controller._token_active is None
    if phase=='completion':
        assert service.working.check_closed_witness(witness)['state']=='CLOSED_PRE_RUNTIME'
        assert service._slots[request['workspace_id']]['closed'] is witness
    else:
        slot=service.working._issued[request['workspace_id']]
        with pytest.raises(Conflict):DirectoryHold(slot['copy'].path)
    monkeypatch.undo()
    assert service.record(command,token,observation)['fact']['state']==('CLOSED_PRE_RUNTIME' if phase=='completion' else 'CLOSE_REQUESTED')


def test_actual_physical_close_failure_preserves_requested_state_and_no_completion(workspace,monkeypatch):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    requested=close_request(request,'request_close',7,1);service.record(requested,token,observation)
    hold=service.working._issued[request['workspace_id']]['hold'];before=service.store.audit()
    def fault():raise Conflict('disposable kernel cleanup fault')
    monkeypatch.setattr(hold,'close',fault)
    with pytest.raises(Conflict,match='cleanup fault'):service.close_physical_pre_runtime(fact_key(requested),observation)
    assert service.store.audit()==before and not service.working._closed_witnesses
    with pytest.raises((Conflict,PermissionError)):
        service.record(close_request(request,'complete_close',8,2),token,observation)
    monkeypatch.undo()


def test_historical_duplicate_after_expiry_never_regrants_actual_hold(workspace,monkeypatch):
    service,request,token,observation,_=workspace;result=service.record(request,token,observation)
    expired=timestamp(result['fact']['observation']['expires_at'])+timedelta(seconds=1)
    monkeypatch.setattr(service.controller,'clock',lambda:expired)
    assert service.record(request,token,observation)=={**result,'duplicate':True}
    assert result['execution_enabled'] is False and result['release_enabled'] is False
    with pytest.raises(Conflict):service.record({**request,'idempotency_key':'new','expected_state_version':7},token,observation)


@pytest.mark.parametrize('clock',['controller','working','material'])
def test_final_owner_work_cannot_outlive_any_observation_deadline(workspace,monkeypatch,clock):
    service,request,token,observation,_=workspace;before=service.store.audit();original=service.controller._final_token_freshness
    def final_owner(*args):
        # Inject AFTER all source/head/FD checks, immediately before the exact
        # actual final Controller sample and internal deadline callback.
        if clock=='controller':monkeypatch.setattr(service.controller,'monotonic_ns',lambda:1000*10**9)
        elif clock=='working':monkeypatch.setattr(service.working,'_monotonic_ns',lambda:1000*10**9)
        else:monkeypatch.setattr(service.preparation,'_witness_monotonic_ns',lambda:1000*10**9)
        return original(*args)
    monkeypatch.setattr(service.controller,'_final_token_freshness',final_owner)
    with pytest.raises(Conflict):service.record(request,token,observation)
    assert service.store.audit()==before
    assert service._active is None and service.controller._token_active is None
    slot=service.working._issued[request['workspace_id']]
    with pytest.raises(Conflict):DirectoryHold(slot['copy'].path)


@pytest.mark.parametrize('damage',['all','nonlatest','extra_claim'])
def test_rehashed_snapshot_cannot_omit_workspace_history_or_invent_claim(workspace,damage):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    requested=close_request(request,'request_close',7,1);service.record(requested,token,observation)
    state=service.store.audit();original_state=canonical(state)
    if damage=='all':
        for section in SECTIONS:state.pop(section)
    elif damage=='nonlatest':state[SECTIONS[0]].pop(fact_key(request))
    else:state[SECTIONS[2]]['orphan']=dict(next(iter(state[SECTIONS[2]].values())))
    raw=canonical(state)
    with service.store.connect() as db:
        db.execute('INSERT OR REPLACE INTO snapshots(version,state,sha256) VALUES(?,?,?)',(8,raw,sha(state)))
        if damage=='all':
            for section in SECTIONS:db.execute('DELETE FROM projection WHERE section=?',(section,))
        elif damage=='nonlatest':db.execute('DELETE FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],fact_key(request)))
        else:db.execute('INSERT INTO projection(section,object_key,value,version) VALUES(?,?,?,?)',
            (SECTIONS[2],'orphan',canonical(state[SECTIONS[2]]['orphan']).decode(),8))
        db.execute('UPDATE snapshot_due SET due_version=8')
    # Full event audit ignores damaged snapshot/projection and remains valid;
    # recover and projection-based maintenance must reject the damaged copies.
    assert canonical(service.store.audit())==original_state
    with pytest.raises(ValueError):service.store.recover()
    assert maintain(service.store) is False


def test_stage_copy_does_not_hold_store_writer(workspace,monkeypatch):
    from rlflow.hybrid_snapshot import SnapshotBuilder
    service,_,_,_,budget_request=workspace;original=SnapshotBuilder.build
    def observed(builder):
        # A distinct open-file-description must acquire the actual lock NOW;
        # nonblocking acquisition would fail if this copy held the writer.
        with service.store.lock(nonblocking=True):pass
        return original(builder)
    monkeypatch.setattr(SnapshotBuilder,'build',observed)
    second=service.stage(budget_request['preparation_intent_key'])
    assert service.working.check(second)['execution_enabled'] is False


@pytest.mark.parametrize('after_retire',[False,True])
def test_memory_ack_failure_after_durable_close_is_retryable_without_adoption(workspace,monkeypatch,after_retire):
    service,request,token,observation,_=workspace;service.record(request,token,observation)
    requested=close_request(request,'request_close',7,1);service.record(requested,token,observation)
    service.close_physical_pre_runtime(fact_key(requested),observation)
    completed=close_request(request,'complete_close',8,2);retire=service.working.retire_closed_witness;calls=[0]
    def fault(witness):
        calls[0]+=1
        if calls[0]==1:
            if after_retire:retire(witness)
            raise Conflict('disposable post-commit memory ACK fault')
        retire(witness)
    monkeypatch.setattr(service.working,'retire_closed_witness',fault)
    with pytest.raises(Conflict,match='memory ACK'):service.record(completed,token,observation)
    assert service.store.version()==9 and service.store.get(SECTIONS[1],head_key(request))['state']=='CLOSED_PRE_RUNTIME'
    assert request['workspace_id'] in service._slots
    result=service.record(completed,token,observation)
    assert result['duplicate'] and not result['execution_enabled'] and not result['release_enabled']
    assert not service.working._closed_witnesses and request['workspace_id'] not in service._slots
    assert service.store.audit()==service.store.replay()


def test_controller_expiry_while_waiting_actual_writer_keeps_staged_fd(workspace,monkeypatch):
    service,request,token,observation,_=workspace;before=service.store.audit();started=threading.Event();results=[]
    def waiting():
        started.set()
        try:service.record(request,token,observation)
        except Conflict:results.append('denied')
        except BaseException as error:results.append(type(error).__name__)
        else:results.append('unexpected success')
    with service.store.lock():
        thread=threading.Thread(target=waiting);thread.start();assert started.wait(timeout=5)
        monkeypatch.setattr(service.controller,'monotonic_ns',lambda:1000*10**9)
    thread.join(timeout=10);assert not thread.is_alive() and results==['denied']
    assert service.store.audit()==before
    with pytest.raises(Conflict):DirectoryHold(service.working._issued[request['workspace_id']]['copy'].path)


def test_large_legal_preparation_actual_stage_acquire_close_full_closure(owned,tmp_path,monkeypatch):
    prep,preparation_request,clock,_=owned
    schema={'type':'object','description':'workspace literal capacity fixture',
        'examples':[{'$rlflow_blob':0} for _ in range(180000)]}
    assert len(canonical(schema))<4*1024**2
    monkeypatch.setattr('rlflow.execution_adapter.role_schema',lambda role:schema)
    prepared=prep.prepare(preparation_request);prep._witness_monotonic_ns=lambda:100*10**9
    controller=ControllerService(prep.store,prep.registry,project_id=prep.project_id,data_mode=prep.data_mode,
        store_epoch=prep.store_epoch,clock=lambda:clock[0],monotonic_ns=lambda:100*10**9)
    acquired=controller.acquire('large-workspace-controller',expected_version=4)
    budget=BudgetService(prep.store,prep.registry,controller,prep)
    command={'project_id':prep.project_id,'data_mode':prep.data_mode,'store_epoch':prep.store_epoch,
        'goal_ref':preparation_request['goal_ref'],'idempotency_key':'large-workspace-reserve','expected_state_version':5,
        'action':'RESERVE','preparation_intent_key':intent_key(preparation_request),
        'amount':{**zero(),'wall_seconds':1},'purpose':'EXECUTION'}
    budget.record(command,acquired['token'])
    namespace=tmp_path/'large-working';namespace.mkdir(mode=0o700)
    working=WorkingCopyOwner(prep.builder,namespace,clock=lambda:clock[0],monotonic_ns=lambda:100*10**9)
    service=WorkspaceService(prep.store,prep.registry,controller,prep,budget,working)
    observation=service.stage(command['preparation_intent_key'])
    request={n:command[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    request.update({'idempotency_key':'large-workspace-acquire','expected_state_version':6,'expected_workspace_revision':0,
        'workspace_id':json.loads(observation.raw)['workspace_id'],'reservation_id':reservation_key(command),
        'operation':'acquire','ttl_seconds':30})
    try:
        result=service.record(request,acquired['token'],observation)
        assert service.record(request,acquired['token'],observation)=={**result,'duplicate':True}
        requested=close_request(request,'request_close',7,1);service.record(requested,acquired['token'],observation)
        service.close_physical_pre_runtime(fact_key(requested),observation)
        service.record(close_request(request,'complete_close',8,2),acquired['token'],observation)
        state=prep.store.audit();assert state==prep.store.replay()
        prep.store.snapshot();assert prep.store.recover()==state
        with prep.store.connect() as db:
            assert db.execute('SELECT MAX(length(data)) FROM blobs').fetchone()[0]>16*1024**2
            db.execute('UPDATE snapshot_due SET due_version=9')
        assert maintain(prep.store,seconds=30,max_bytes=64*1024**2,max_nodes=8*1024**2)
        assert prep.store.recover()==state and prepared['result']['status']=='PREPARED'
    finally:
        for slot in tuple(working._issued.values()):working.close_pre_runtime(slot['observation'])
        for witness in tuple(working._closed_witnesses.values()):working.retire_closed_witness(witness)
