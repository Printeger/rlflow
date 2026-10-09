"""Actual original participants with injected storage faults, never disk fill."""
import errno
import signal
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient

from rlflow.store import Conflict
from tests.test_hybrid_host_execution import shared
from tests.test_hybrid_finite_host_app import application,ORIGIN,path,start,stop
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_fixture_runtime import runtime,register
from tests.test_hybrid_engineering_output import engineering_runtime,engineering_lease
from tests.test_hybrid_usage_source import source_owner


@pytest.mark.parametrize('failure',['Project','Pool','partial_FD'])
def test_actual_preG_storage_failure_still_reaps_retains_exposure_and_original_retry(shared,monkeypatch,failure):
    host,units=shared;unit=units[0];runtime=unit.runtime;other=units[1]
    attempt=runtime._issued(unit.lease);other_version=other.runtime.store.version()
    register=runtime._register_release;signals=[];original_signal=signal.pidfd_send_signal
    def observed_signal(*args,**kwargs):
        signals.append(args[1]);return original_signal(*args,**kwargs)
    monkeypatch.setattr(signal,'pidfd_send_signal',observed_signal)
    def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'injected original critical ledger failure')
    def preG(row):
        source=runtime.sources._issued(row['source'])
        assert source['producer'].poll() is None and not row['release_entered']
        with monkeypatch.context() as patch:
            if failure in ('Project','partial_FD'):patch.setattr(runtime.store,'_commit',no_space)
            else:
                original=runtime.pool._fixture_runtime_change
                def pool_change(owner,lease,state,value):
                    if state=='FIXTURE_STOP_REQUESTED':no_space()
                    return original(owner,lease,state,value)
                patch.setattr(runtime.pool,'_fixture_runtime_change',pool_change)
            target=source['fds']['read'];close=__import__('os').close
            if failure=='partial_FD':
                def unavailable(fd):
                    if fd==target:raise OSError(errno.EIO,'injected original FD close failure')
                    return close(fd)
                patch.setattr(__import__('os'),'close',unavailable)
            result=unit.cancel()
            assert result['status']=='UNKNOWN_CLEANUP_REQUIRED'
            assert source['producer'].poll() is not None and signal.SIGTERM in signals
            assert row['terminal'] is None and runtime.pool.snapshot()['occupied']==2
            assert row['physical_safety_freeze'] and unit._cancelled.is_set()
            if failure=='partial_FD':assert source['fds']['read']==target
            else:assert all(fd is None for fd in source['fds'].values())
        # Actual original fallback can finish FD close after its fault heals,
        # but cannot mint terminal or release the original claim on its own.
        runtime._stop_original_participant(unit.lease)
        assert row['terminal'] is None and all(fd is None for fd in source['fds'].values())
        return register(row)  # The original final gate must refuse later G.
    monkeypatch.setattr(runtime,'_register_release',preG)
    with pytest.raises(Conflict):
        host.run(unit.lease,attempt['token'],idempotency_key='actual_storage_fault',expected_state_version=runtime.store.version())
    assert not attempt['release_entered'] and other.runtime.store.version()==other_version
    assert not other._cancelled.is_set() and not other._actual()['spawn_entered']
    # Normal original durable cleanup after storage heals; never redispatch.
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('original recovery must not spawn'))
    runtime.stop_to_terminal(unit.lease)
    assert runtime.pool.snapshot()['occupied']==1
    assert unit.resume()['status']=='CANCELLED_SCOPE_STOPPED'
    assert not attempt['release_entered']
    print('actual_storage_STOP',dict(fault=failure,reaped=True,original_FDs_closed=True,
        exposure_retained_during_fault=True,original_retry_no_spawn=True,other_project_untouched=True),flush=True)


def test_actual_HTTP_stop_intent_commit_failure_still_cleans_then_same_key_recovers(application,monkeypatch):
    host,units,services,observers,app,token,headers=application
    unit=units[0];service=services[0];runtime=unit.runtime
    attempt=runtime._issued(unit.lease);entered=threading.Event();register=runtime._register_release
    def waiting(row):
        entered.set();assert unit._cancelled.wait(2);return register(row)
    monkeypatch.setattr(runtime,'_register_release',waiting)
    def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'injected original STOP intent storage failure')
    with TestClient(app,base_url=ORIGIN) as client,ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session',token)
        future=worker.submit(client.post,path(service)+'/commands',headers=headers,json=start(service))
        assert entered.wait(8)
        source=runtime.sources._issued(attempt['source']);assert source['producer'].poll() is None
        stop_headers={**headers,'Idempotency-Key':'storage_stop'}
        with monkeypatch.context() as patch:
            patch.setattr(service.store,'_commit',no_space)
            response=client.post(path(service)+'/commands',headers=stop_headers,json=stop(service))
            assert response.status_code==503,response.text
            assert future.result(timeout=10).status_code==202  # Original Run acceptance, not execution success.
            assert unit._cancelled.is_set() and not attempt['release_entered']
            assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
            assert attempt['terminal'] is None and host.pool.snapshot()['occupied']==2
        with monkeypatch.context() as patch:
            patch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('STOP recovery must not spawn'))
            recovered=client.post(path(service)+'/commands',headers=stop_headers,json=stop(service))
            assert recovered.status_code==202,recovered.text
            assert recovered.json()['recorded_phase']=='STOP_INTENT_ACCEPTED'
            version=service.store.version()
            duplicate=client.post(path(service)+'/commands',headers=stop_headers,json=stop(service))
            assert duplicate.status_code==202 and service.store.version()==version
        assert host.pool.snapshot()['occupied']==1 and not units[1]._cancelled.is_set()
        print('actual_HTTP_storage_STOP',dict(failed_acceptance=503,physical_reaped=True,
            original_same_key_recovery=202,extra_spawn=0,other_scope_untouched=True),flush=True)


@pytest.mark.parametrize('cleanup',['attempt','owner','owner_partial_FD'])
def test_actual_bare_runtime_cleanup_without_ledger_or_unit(runtime,monkeypatch,cleanup):
    owner=runtime[0];lease=register(runtime,'running');attempt=owner._issued(lease)
    release=owner._register_release;sources=[]
    def unavailable(*args,**kwargs):raise OSError(errno.ENOSPC,'injected original ledger unavailable')
    def preG(row):
        source=owner.sources._issued(row['source']);sources.append(source)
        assert source['producer'].poll() is None
        with monkeypatch.context() as patch:
            patch.setattr(owner.store,'_commit',unavailable)
            if cleanup=='attempt':
                with pytest.raises(OSError):owner.stop_to_terminal(lease)
            else:
                # Read failure as well as write failure must not cut off cleanup.
                patch.setattr(owner.controller,'_original',unavailable)
                if cleanup=='owner_partial_FD':
                    import os
                    target=source['fds']['read'];close=os.close
                    def failed_close(fd):
                        if fd==target:raise OSError(errno.EIO,'original FD close unavailable')
                        return close(fd)
                    patch.setattr(os,'close',failed_close)
                    with pytest.raises(Conflict):owner.shutdown_safety()
                    assert owner._live and owner.sources._live
                    assert source['fds']['read']==target
                else:
                    result=owner.shutdown_safety()
                    assert result['state']=='PHYSICAL_CLOSED_EXPOSURE_UNKNOWN'
                    assert not result['pool_slots_freed'] and not result['refund_enabled']
            assert source['producer'].poll() is not None
            assert row['terminal'] is None and owner.pool.snapshot()['occupied']==1
            assert row['physical_safety_freeze'] and not row['release_entered']
        if cleanup=='owner_partial_FD':
            result=owner.shutdown_safety()
            assert result['state']=='PHYSICAL_CLOSED_EXPOSURE_UNKNOWN'
        assert all(fd is None for fd in source['fds'].values())
        return release(row)
    monkeypatch.setattr(owner,'_register_release',preG)
    with pytest.raises((Conflict,PermissionError)):owner.start(lease)
    assert len(sources)==1 and not attempt['release_entered']
    monkeypatch.setattr(owner,'_register_release',release)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('frozen original cannot spawn'))
    if cleanup=='attempt':
        with pytest.raises(Conflict):owner.start(lease)
        owner.stop_to_terminal(lease)
        assert owner.pool.snapshot()['occupied']==0
    else:assert owner.pool.snapshot()['occupied']==1
    print('actual_bare_storage_STOP',dict(cleanup=cleanup,reaped=True,all_FDs_closed=True,
        no_new_G=True,no_refund_on_safety_shutdown=cleanup!='attempt'),flush=True)


def test_actual_whole_STOP_failed_acceptance_cleanup_exactly_once(application,monkeypatch):
    from rlflow.hybrid_finite_host_stop import ACTION
    host,units,services,observers,app,token,headers=application
    coordinator=app.state.finite_host_stop;calls=[];cancel=units[0].cancel
    def observed_cancel():calls.append(True);return cancel()
    def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'original STOP ledger unavailable')
    batch=coordinator.prepare({'action':ACTION},token=token,csrf=headers['X-CSRF-Token'],
        origin=ORIGIN,idempotency_key='accept_failure_once')
    with monkeypatch.context() as patch:
        patch.setattr(units[0],'cancel',observed_cancel)
        patch.setattr(services[0].store,'_commit',no_space)
        result=coordinator.execute_prepared(batch)
        assert result['status']=='PARTIAL_OR_UNKNOWN' and len(calls)==1
        assert result['items'][0]['intent_status']=='UNKNOWN'
        assert result['items'][0]['cleanup_status']=='UNKNOWN'
        assert not services[0].store.objects(services[0]._stop_domain.SECTION)
        assert host.pool.snapshot()['occupied']==1
    recovered=coordinator.execute_prepared(batch,_resume_unknown=True)
    assert recovered['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
    assert host.pool.snapshot()['occupied']==0
    print('actual_whole_storage_STOP',dict(automatic_cancel_calls=1,unknown_not_accepted=True,
        original_explicit_recovery=True,occupied=0),flush=True)


@pytest.mark.parametrize('prior_rollback',[False,True])
def test_actual_cleanup_COMMIT_lost_return_never_signs_rollback_or_rebases(runtime,monkeypatch,prior_rollback):
    from copy import deepcopy
    owner=runtime[0];lease=register(runtime);attempt=owner._issued(lease)
    commit=owner.store._commit;seen=[]
    if prior_rollback:
        def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'first original write rolled back')
        with monkeypatch.context() as patch:
            patch.setattr(owner.store,'_commit',no_space)
            with pytest.raises(OSError):owner.stop_to_terminal(lease)
        assert attempt['known_cleanup_rollback']['STOP_REQUESTED']
    def committed_then_lost(db,*args,**kwargs):
        result=commit(db,*args,**kwargs)
        guard=kwargs.get('_authorization')
        if guard is not None and guard.owner is owner and not seen:
            seen.append(True);db.commit()
            assert not db.in_transaction
            raise OSError(errno.EIO,'actual COMMIT succeeded but return lost')
        return result
    with monkeypatch.context() as patch:
        patch.setattr(owner.store,'_commit',committed_then_lost)
        with pytest.raises(OSError):owner.stop_to_terminal(lease)
    assert seen and not attempt.get('known_cleanup_rollback')
    retained=deepcopy(attempt['entries']['STOP_REQUESTED'])
    owner.store.transact_objects('FIXTURE_PROGRESS','after_committed_stop',[],lambda state:None,
        expected=owner.store.version())
    # Historical exact committed STOP is confirmed; it is NOT rewritten with
    # this new version, nor issued as a new grant.
    owner.stop_to_terminal(lease)
    assert attempt['entries']['STOP_REQUESTED']==retained
    assert not attempt.get('known_cleanup_rollback') and owner.pool.snapshot()['occupied']==0
    print('actual_cleanup_lost_return',dict(prior_rollback=prior_rollback,committed=True,rollback_witness=False,
        retained_original_unchanged=True,occupied=0),flush=True)


@pytest.mark.parametrize('cleanup',['attempt','owner'])
def test_actual_bare_engineering_source_close_failure_still_closes_original_input(engineering_runtime,monkeypatch,cleanup):
    import os
    owner=engineering_runtime[0];grant,lease=engineering_lease(engineering_runtime)
    attempt=owner._issued(lease);row=owner._engineering_grants[id(grant)]
    release=owner._register_release
    def preG(actual):
        source=owner.sources._issued(actual['source']);target=source['fds']['read'];close=os.close
        assert source['producer'].poll() is None and row['fd'] is not None
        def unavailable(*args,**kwargs):raise OSError(errno.ENOSPC,'original ledger full')
        def failed_close(fd):
            if fd==target:raise OSError(errno.EIO,'original source close unavailable')
            return close(fd)
        with monkeypatch.context() as patch:
            patch.setattr(owner.store,'_commit',unavailable);patch.setattr(os,'close',failed_close)
            if cleanup=='attempt':
                with pytest.raises(OSError):owner.stop_to_terminal(lease)
            else:
                with pytest.raises(Conflict):owner.shutdown_safety()
                assert owner._live and owner.sources._live
            assert source['producer'].poll() is not None
            assert source['fds']['read']==target and row['fd'] is None
            assert actual['physical_safety_freeze'] and actual['terminal'] is None
            assert owner.pool.snapshot()['occupied']==1
        if cleanup=='attempt':owner._stop_original_participant(lease)
        else:owner.shutdown_safety()
        assert all(fd is None for fd in source['fds'].values()) and row['fd'] is None
        return release(actual)
    monkeypatch.setattr(owner,'_register_release',preG)
    with pytest.raises((Conflict,PermissionError)):owner.start(lease)
    assert not attempt['release_entered']
    if cleanup=='attempt':owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==(0 if cleanup=='attempt' else 1)
    print('actual_bare_engineering_storage_STOP',dict(reaped=True,source_retry_closed=True,
        input_closed_despite_source_error=True,no_G=True,occupied=owner.pool.snapshot()['occupied']),flush=True)


@pytest.mark.parametrize('prior_rollback',[False,True])
def test_actual_cleanup_rollback_failure_never_signs_witness(runtime,monkeypatch,prior_rollback):
    import sqlite3
    from copy import deepcopy
    owner=runtime[0];lease=register(runtime);attempt=owner._issued(lease)
    connect=sqlite3.connect;seen=[]
    class RollbackFailure(sqlite3.Connection):
        def rollback(self):
            seen.append(True);raise OSError(errno.EIO,'original rollback return unavailable')
    def connection(*args,**kwargs):return connect(*args,**{**kwargs,'factory':RollbackFailure})
    def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'original cleanup write unavailable')
    if prior_rollback:
        with monkeypatch.context() as patch:
            patch.setattr(owner.store,'_commit',no_space)
            with pytest.raises(OSError):owner.stop_to_terminal(lease)
        assert attempt['known_cleanup_rollback']['STOP_REQUESTED']
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3,'connect',connection);patch.setattr(owner.store,'_commit',no_space)
        with pytest.raises(OSError,match='rollback'):owner.stop_to_terminal(lease)
    assert seen and not attempt.get('known_cleanup_rollback')
    retained=deepcopy(attempt['entries']['STOP_REQUESTED'])
    owner.store.transact_objects('FIXTURE_PROGRESS','after_unknown_rollback',[],lambda state:None,
        expected=owner.store.version())
    with pytest.raises(Conflict,match='CAS changed'):owner.stop_to_terminal(lease)
    assert attempt['entries']['STOP_REQUESTED']==retained
    assert not attempt.get('known_cleanup_rollback') and owner.pool.snapshot()['occupied']==1
    result=owner.shutdown_safety()
    assert result['state']=='PHYSICAL_CLOSED_EXPOSURE_UNKNOWN'
    print('actual_cleanup_rollback_failure',dict(prior_rollback=prior_rollback,witness=False,rebase=False,exposure_retained=True),flush=True)


def test_actual_source_owner_partial_cleanup_still_reaps_other_original_source(source_owner,monkeypatch):
    import os
    owner,member,claim=source_owner
    first=owner.start_fixture(member,claim,'linger')
    second_claim=owner.pool.claim(member,expected_version=owner.pool.snapshot()['version'],request_key='other_original_source')
    second=owner.start_fixture(member,second_claim,'linger')
    rows=[owner._issued(value) for value in (first,second)]
    target=rows[0]['fds']['read'];close=os.close
    def failed_close(fd):
        if fd==target:raise OSError(errno.EIO,'first original source close unavailable')
        return close(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os,'close',failed_close)
        with pytest.raises(Conflict):owner.shutdown_safety()
        assert owner._live
        assert all(row['producer'].poll() is not None for row in rows)
        assert rows[0]['fds']['read']==target
        assert all(fd is None for fd in rows[1]['fds'].values())
        assert owner.pool.snapshot()['occupied']==2
    owner.shutdown_safety()
    assert not owner._live and all(fd is None for row in rows for fd in row['fds'].values())
    assert owner.pool.snapshot()['occupied']==2
    print('actual_source_owner_cleanup',dict(first_partial=True,other_original_reaped=True,
        retained_owner_retry=True,no_pool_refund=True),flush=True)


def test_actual_engineering_terminal_rollback_recovers_without_unfreezing_pwrite(engineering_runtime,monkeypatch):
    import os
    import json
    from copy import deepcopy
    from rlflow.hybrid_candidate_output_service import CandidateOutputService
    from rlflow.hybrid_engineering_patch import BEFORE,TARGET
    owner=engineering_runtime[0];_,lease=engineering_lease(engineering_runtime)
    attempt=owner._issued(lease);request_stop=owner.request_stop;commit=owner.store._commit
    def no_space(*args,**kwargs):raise OSError(errno.ENOSPC,'original STOP fact unavailable')
    def failed_stop(actual):
        with monkeypatch.context() as patch:
            patch.setattr(owner.store,'_commit',no_space)
            return request_stop(actual)
    with monkeypatch.context() as patch:
        patch.setattr(owner,'request_stop',failed_stop)
        with pytest.raises(OSError):owner.run_engineering_patch(lease)
    result=json.loads(owner._engineering_results[id(lease)].raw)
    assert result['baseline_failed_cases']==2 and result['repaired_passed_cases']==3
    assert attempt['physical_safety_freeze'] and attempt['terminal'] is None
    source=owner.sources._issued(attempt['source'])
    assert source['producer'].poll()==0 and all(fd is None for fd in source['fds'].values())
    terminal_attempts=[]
    def failed_terminal(db,*args,**kwargs):
        guard=kwargs.get('_authorization')
        if guard is not None and guard.owner is owner and json.loads(guard.raw)['request']['fixture_runtime']['phase']=='FIXTURE_SCOPE_STOPPED':
            terminal_attempts.append(True);raise OSError(errno.ENOSPC,'original terminal fact rolled back')
        return commit(db,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(owner.store,'_commit',failed_terminal)
        with pytest.raises(OSError):owner.stop_to_terminal(lease)
    assert terminal_attempts==[True] and attempt['known_cleanup_rollback']['FIXTURE_SCOPE_STOPPED']
    assert owner.pool.snapshot()['occupied']==1
    original_terminal=deepcopy(attempt['terminal'])
    original_key=attempt['entries']['FIXTURE_SCOPE_STOPPED']['request']['idempotency_key']
    owner.store.transact_objects('FIXTURE_PROGRESS','after_terminal_rollback',[],lambda state:None,
        expected=owner.store.version())
    writes=[];pwrite=os.pwrite
    with monkeypatch.context() as patch:
        patch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('terminal recovery cannot spawn'))
        patch.setattr(os,'pwrite',lambda *a,**k:(writes.append(True),pwrite(*a,**k))[1])
        owner.stop_to_terminal(lease)
        assert owner.pool.snapshot()['occupied']==0 and attempt['terminal']==original_terminal
        assert attempt['entries']['FIXTURE_SCOPE_STOPPED']['request']['idempotency_key']==original_key
        assert not attempt.get('known_cleanup_rollback')
        version=owner.store.version();output=CandidateOutputService(owner)
        with pytest.raises(Conflict,match='frozen after failed durable STOP'):
            output.apply(lease,engineering_runtime[2],idempotency_key='frozen_result',expected_state_version=version)
        assert owner.store.version()==version and not writes
    slot,_=owner.workspace.working._slot(attempt['observation'])
    assert (slot['copy'].path/TARGET).read_bytes()==BEFORE
    print('actual_engineering_terminal_recovery',dict(original_result=True,terminal_rollback=True,
        same_key_CAS_recovery=True,occupied=0,freeze_retained=True,pwrites=0),flush=True)
