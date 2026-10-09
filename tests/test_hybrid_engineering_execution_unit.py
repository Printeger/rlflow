"""Actual one-call original engineering unit, cancellation and finite recovery."""
from dataclasses import replace
from datetime import timedelta
import os
import subprocess
import threading

import pytest

from rlflow.hybrid_engineering_execution_unit import EngineeringExecutionUnit
from rlflow.hybrid_candidate_output_service import CandidateOutputService
from rlflow.hybrid_candidate_output import SECTIONS, result_key
from rlflow.hybrid_engineering_patch import BEFORE, AFTER, TARGET
from rlflow.hybrid_fixture_runtime_control import FixtureRuntimeControlService
from rlflow.store import Conflict
from tests.test_hybrid_engineering_output import engineering_runtime, engineering_lease
from tests.test_execution_adapter import setup as native_setup


def unit(context):
    owner = context[0]; _, lease = engineering_lease(context)
    output = CandidateOutputService(owner)
    accept = output.accept_machine
    def advance_fixture_clock(*args, **kwargs):
        # Existing synthetic authority clock is frozen. Match the causal
        # microsecond advance that real UTC has between two actual commits.
        context[6][0] += timedelta(microseconds=1)
        context[7][0] += 1000
        return accept(*args, **kwargs)
    output.accept_machine = advance_fixture_clock
    return owner, lease, output, EngineeringExecutionUnit(owner, lease, output)


def candidate(owner, lease):
    observation = owner._issued(lease)['observation']
    slot, _ = owner.workspace.working._slot(observation)
    return slot['copy'].path / TARGET


def test_one_call_writer_CAS_original_effect_once_recovery_and_binding(engineering_runtime, monkeypatch):
    owner, lease, output, execution = unit(engineering_runtime)
    request = {'idempotency_key': 'one_call', 'expected_state_version': owner.store.version()}
    writes = []; pwrite = os.pwrite
    monkeypatch.setattr(os, 'pwrite', lambda fd, data, offset: (writes.append((data, offset)), pwrite(fd, data, offset))[1])
    start = owner.start
    with monkeypatch.context() as patch:
        def stale(actual_lease):
            # Actual competing durable event, not incoherent metadata damage.
            # Unit body is captured before HANDOFF obtains its real writer.
            owner.store.transact_objects('FIXTURE_PROGRESS', 'writer_wait', [], lambda state: None,
                expected=request['expected_state_version'])
            return start(actual_lease)
        patch.setattr(owner, 'start', stale)
        with pytest.raises(Conflict, match='initial HANDOFF writer CAS'): execution.run(engineering_runtime[2], **request)
    assert execution._request is None and not owner._issued(lease)['spawn_entered']
    assert owner.store.version() == request['expected_state_version'] + 1 and candidate(owner, lease).read_bytes() == BEFORE
    request['expected_state_version'] = owner.store.version()
    with pytest.raises(PermissionError): owner.start(lease)
    with pytest.raises(Conflict): EngineeringExecutionUnit(owner, lease, output)
    with pytest.raises(PermissionError): EngineeringExecutionUnit(owner, replace(lease), output)
    with pytest.raises(Conflict): FixtureRuntimeControlService(owner, owner.store._hybrid_auth_owner, origin='http://127.0.0.1:8765')
    result = execution.run(engineering_runtime[2], **request)
    assert result['status'] == 'MACHINE_ACCEPTED_PENDING_REVIEW'
    assert result['fact']['machine_verification']['derived']['passed_cases'] == 21
    assert writes == [(AFTER, 0)] and candidate(owner, lease).read_bytes() == AFTER
    assert owner.pool.snapshot()['occupied'] == 0
    source = owner.sources._issued(owner._issued(lease)['source'])
    assert source['producer'].poll() == 0 and all(fd is None for fd in source['fds'].values())
    version = owner.store.version()
    assert execution.run(engineering_runtime[2], **request) == result
    assert execution.resume() == result and owner.store.version() == version and len(writes) == 1
    with pytest.raises(Conflict, match='request changed'):
        execution.run(engineering_runtime[2], **{**request, 'idempotency_key': 'different'})
    state = owner.store.audit(); owner.store.snapshot(); assert owner.store.recover() == state
    assert not result['goal_completed'] and result['independent_review_status'] == 'NOT_PERFORMED'


@pytest.mark.parametrize('boundary', ['G', 'PWRITE', 'MACHINE_COMMIT'])
def test_cancel_latches_before_blocked_pool_final_effects_and_closes_original_scope(engineering_runtime, monkeypatch, boundary):
    owner, lease, output, execution = unit(engineering_runtime)
    results = []; threads = []; triggered = False
    release_identity = threading.Event(); identity_entered = threading.Event()
    if boundary == 'G':
        actual = owner._actual
        def blocked_identity():
            if threading.current_thread().name == 'unit_cancel':
                identity_entered.set()
                assert release_identity.wait(10)
            return actual()
        monkeypatch.setattr(owner, '_actual', blocked_identity)
    def cancel_at_boundary():
        nonlocal triggered
        if triggered: return
        triggered = True
        thread = threading.Thread(target=lambda: results.append(execution.cancel()), name='unit_cancel')
        threads.append(thread); thread.start()
        assert execution._cancelled.wait(1), 'cancel must latch while original writer owns Pool lock'
        if boundary == 'G': assert identity_entered.wait(1), 'latch precedes held procfs identity check'
        assert thread.is_alive(), 'physical cleanup waits for original effect transaction'
    if boundary == 'G':
        gate = owner._check_release_gate
        def gate_cancel(attempt): cancel_at_boundary(); return gate(attempt)
        monkeypatch.setattr(owner, '_check_release_gate', gate_cancel)
    elif boundary == 'PWRITE':
        gate = output._last_effect
        def gate_cancel(guard):
            if guard.row['material'].fd is not None and not guard.row['material'].write_entered:
                cancel_at_boundary()
            return gate(guard)
        monkeypatch.setattr(output, '_last_effect', gate_cancel)
    else:
        put = output._put
        def put_cancel(db, read, section, value, row, **kwargs):
            guard = put(db, read, section, value, row, **kwargs)
            if 'machine_verification' in value: cancel_at_boundary()
            return guard
        monkeypatch.setattr(output, '_put', put_cancel)
    try:
        with pytest.raises(Conflict, match='cancelled'):
            execution.run(engineering_runtime[2], idempotency_key='cancel', expected_state_version=owner.store.version())
    finally:
        release_identity.set()
        for thread in threads: thread.join(10); assert not thread.is_alive()
    assert triggered and results[0]['status'] == 'CANCELLED_SCOPE_STOPPED'
    attempt = owner._issued(lease); source = owner.sources._issued(attempt['source'])
    assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
    assert owner.pool.snapshot()['occupied'] == 0
    row = output._rows.get(id(lease))
    if boundary == 'G': assert not attempt['release_entered'] and row is None
    else: assert row['material'].fd is None and row['material'].closed
    if boundary != 'MACHINE_COMMIT': assert candidate(owner, lease).read_bytes() == BEFORE
    else:
        assert candidate(owner, lease).read_bytes() == AFTER
        assert all('machine_verification' not in v for k, v in owner.store.replay()[SECTIONS[1]].items() if k)
    with pytest.raises(Conflict, match='cancelled'): owner.start(lease)
    with pytest.raises(Conflict, match='cancelled'):
        output.apply(lease, engineering_runtime[2], idempotency_key='bypass', expected_state_version=owner.store.version())
    resumed = execution.resume()
    assert resumed['status'] == ('OUTPUT_CAPTURED_CANCELLED' if boundary == 'MACHINE_COMMIT' else 'CANCELLED_SCOPE_STOPPED')


@pytest.mark.parametrize('failure', ['HANDOFF', 'POPEN_UNKNOWN', 'G', 'WRITE', 'ACCEPTANCE'])
def test_lost_original_outcomes_resume_never_repeats_effect_or_invents_unknown_free(engineering_runtime, monkeypatch, failure):
    owner, lease, output, execution = unit(engineering_runtime)
    request = {'idempotency_key': 'lost', 'expected_state_version': owner.store.version()}
    writes = []; pwrite = os.pwrite
    def counted(fd, data, offset):
        writes.append((data, offset)); value = pwrite(fd, data, offset)
        if failure == 'WRITE': raise OSError('entered write lost result')
        return value
    monkeypatch.setattr(os, 'pwrite', counted)
    with monkeypatch.context() as patch:
        if failure == 'HANDOFF':
            phase = owner._write_phase
            def lost(attempt, name, **kwargs):
                value = phase(attempt, name, **kwargs)
                if name == 'HANDOFF_UNKNOWN': raise OSError('durable HANDOFF lost receipt')
                return value
            patch.setattr(owner, '_write_phase', lost)
        elif failure == 'POPEN_UNKNOWN':
            def unknown(*args, **kwargs): raise OSError('unknown Popen outcome')
            patch.setattr(subprocess, 'Popen', unknown)
        elif failure == 'G':
            release = owner.sources._runtime_release
            def lost(*args): release(*args); raise OSError('entered G lost receipt')
            patch.setattr(owner.sources, '_runtime_release', lost)
        elif failure == 'ACCEPTANCE':
            accept = output.accept_machine
            def lost(*args, **kwargs): accept(*args, **kwargs); raise OSError('durable acceptance lost receipt')
            patch.setattr(output, 'accept_machine', lost)
        with pytest.raises(OSError): execution.run(engineering_runtime[2], **request)
    assert execution._request == request
    with monkeypatch.context() as patch:
        for obj, name in ((owner, 'start'), (owner, 'run_engineering_patch'), (owner.sources, '_runtime_release'), (os, 'pwrite')):
            patch.setattr(obj, name, lambda *a, **k: pytest.fail('resume cannot restart/release/rewrite'))
        result = execution.resume()
        assert execution.run(engineering_runtime[2], **request)['status'] == result['status']
    if failure in ('WRITE', 'ACCEPTANCE'):
        assert result['status'] == 'MACHINE_ACCEPTED_PENDING_REVIEW' and writes == [(AFTER, 0)]
        assert candidate(owner, lease).read_bytes() == AFTER and owner.pool.snapshot()['occupied'] == 0
    else:
        assert result['status'] == 'UNKNOWN_RESULT_UNAVAILABLE' and writes == []
        assert candidate(owner, lease).read_bytes() == BEFORE
        if failure in ('HANDOFF', 'POPEN_UNKNOWN'):
            assert owner.pool.snapshot()['occupied'] == 1 and owner._issued(lease)['terminal'] is None
            assert execution.cleanup_error is not None and owner._current(owner._issued(lease))['status'] == 'UNKNOWN'
        else: assert owner.pool.snapshot()['occupied'] == 0
    with pytest.raises(Conflict, match='request changed'):
        execution.run(engineering_runtime[2], **{**request, 'idempotency_key': 'replacement'})
    if failure == 'HANDOFF':
        # Two actual cleanup callers. Second is held before its STOP and must
        # not erase the first caller's local UNKNOWN result.
        closing = threading.Event(); second_entered = threading.Event(); first_done = threading.Event()
        closed_input = owner._close_engineering_input; confirm = owner._confirm_entry
        results = []
        def close_input(row):
            value = closed_input(row)
            if threading.current_thread().name == 'cleanup_first':
                closing.set(); assert second_entered.wait(5)
            return value
        def confirm_entry(*args):
            if threading.current_thread().name == 'cleanup_second':
                second_entered.set(); assert first_done.wait(5)
            return confirm(*args)
        with monkeypatch.context() as patch:
            patch.setattr(owner, '_close_engineering_input', close_input)
            patch.setattr(owner, '_confirm_entry', confirm_entry)
            def first():
                try: results.append(execution.cancel())
                finally: first_done.set()
            first_thread = threading.Thread(target=first, name='cleanup_first')
            second_thread = threading.Thread(target=lambda: results.append(execution.cancel()), name='cleanup_second')
            first_thread.start(); assert closing.wait(5); second_thread.start()
            for thread in (first_thread, second_thread): thread.join(10); assert not thread.is_alive()
        assert len(results) == 2 and all(r['status'] == 'UNKNOWN_CLEANUP_REQUIRED' and r['cleanup_error'] for r in results)
        assert owner.pool.snapshot()['occupied'] == 1 and owner._issued(lease)['terminal'] is None
    if failure in ('HANDOFF', 'POPEN_UNKNOWN'):
        # Explicit original-owner physical shutdown for this private singleton
        # fixture only. No terminal/FREE/refund is inferred from cleanup.
        safety = owner.shutdown_safety()
        assert not safety['pool_slots_freed'] and owner.pool.snapshot()['occupied'] == 1


def test_existing_HTTP_binding_cannot_be_replaced(engineering_runtime):
    owner = engineering_runtime[0]; _, lease = engineering_lease(engineering_runtime)
    output = CandidateOutputService(owner)
    control = FixtureRuntimeControlService(owner, owner.store._hybrid_auth_owner, origin='http://127.0.0.1:8765')
    with pytest.raises(Conflict): EngineeringExecutionUnit(owner, lease, output)
    assert control.runtime is owner and owner._engineering_units == {}


def test_prestart_cancel_and_actual_fork_cannot_adopt_original_unit(engineering_runtime):
    owner, lease, output, execution = unit(engineering_runtime)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            for action in (execution.resume, execution.cancel, lambda: owner.start(lease)):
                try: action()
                except PermissionError: pass
                else: raise AssertionError('fork adopted original unit')
            os.write(write_fd, b'OK')
        finally: os._exit(0)
    os.close(write_fd)
    try:
        _, status = os.waitpid(pid, 0)
        assert status == 0 and os.read(read_fd, 16) == b'OK'
    finally: os.close(read_fd)
    assert execution.cancel()['status'] == 'CANCELLED_SCOPE_STOPPED'
    with pytest.raises(Conflict, match='cancelled'):
        execution.run(engineering_runtime[2], idempotency_key='too_late', expected_state_version=owner.store.version())
    assert not owner._issued(lease)['spawn_entered'] and owner.pool.snapshot()['occupied'] == 0
