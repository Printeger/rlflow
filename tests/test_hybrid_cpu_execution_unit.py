"""Actual once-only experiment SDK, raw machine evaluation and cancel gates."""
from dataclasses import replace
from datetime import timedelta
import json
import os
import subprocess
import threading

import pytest

from rlflow.hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.hybrid_cpu_assessment import SECTION, fact_key
from rlflow.hybrid_engineering_execution_unit import EngineeringExecutionUnit
from rlflow.hybrid_candidate_output_service import CandidateOutputService
from rlflow.hybrid_fixture_runtime_control import FixtureRuntimeControlService
from rlflow.hybrid_cpu_trial import inputs
from rlflow.store import Conflict, canonical
from tests.test_hybrid_cpu_trial_runtime import trial_runtime, grant_and_lease
from tests.test_execution_adapter import setup as native_setup


def unit(context):
    owner = context[0]; _, lease = grant_and_lease(context)
    service = CpuAssessmentService(owner)
    return owner, lease, service, CpuTrialExecutionUnit(owner, lease, service)


def test_one_call_actual384_raw_machine_scope_STOP_FREE_once_consumption_and_recovery(trial_runtime, monkeypatch):
    owner, lease, service, execution = unit(trial_runtime)
    request = {'idempotency_key': 'actual_experiment', 'expected_state_version': owner.store.version()}
    writes = []; spawn = subprocess.Popen; launches = []
    def original_spawn(*args, **kwargs): launches.append(args[0]); return spawn(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', original_spawn)
    monkeypatch.setattr(os, 'pwrite', lambda *args: pytest.fail('CPU unit has no candidate write authority'))
    start = owner.start
    with monkeypatch.context() as patch:
        def stale(actual_lease):
            owner.store.transact_objects('FIXTURE_PROGRESS', 'cpu_writer_wait', [], lambda state: None,
                expected=request['expected_state_version'])
            return start(actual_lease)
        patch.setattr(owner, 'start', stale)
        with pytest.raises(Conflict, match='initial HANDOFF writer CAS'): execution.run(trial_runtime[2], **request)
    assert execution._request is None and launches == []
    request['expected_state_version'] = owner.store.version()
    assert owner._execution_units is owner._engineering_units
    with pytest.raises(PermissionError): owner.start(lease)
    with pytest.raises(Conflict): CpuTrialExecutionUnit(owner, lease, service)
    with pytest.raises(PermissionError): CpuTrialExecutionUnit(owner, replace(lease), service)
    with pytest.raises(Conflict): FixtureRuntimeControlService(owner, owner.store._hybrid_auth_owner, origin='http://127.0.0.1:8765')
    result = execution.run(trial_runtime[2], **request)
    assert result['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW' and len(launches) == 1
    machine = result['fact']['machine_verification']
    assert machine['derived']['inside_counts'] == [96, 101, 104]
    assert machine['derived']['mean_absolute_error'] == 0.08821911547006896
    assert machine['next_action'] == 'REQUEST_INDEPENDENT_REVIEW' and machine['condition_coverage'] == []
    attempt = owner._issued(lease); raw = json.loads(owner._cpu_results[id(lease)].raw)
    assert raw['raw_samples'] == inputs() and sum(len(row['points']) for row in raw['raw_samples']) == 384
    source = owner.sources._issued(attempt['source'])
    assert source['producer'].poll() == 0 and all(fd is None for fd in source['fds'].values())
    assert owner.pool.snapshot()['occupied'] == 0 and attempt['entries']['FIXTURE_SCOPE_STOPPED']['prior_reservation']['amount']['experiment_starts'] == 1
    assert owner._current(attempt)['status'] == 'SETTLED'
    version = owner.store.version()
    trial_runtime[6][0] += timedelta(seconds=120); trial_runtime[7][0] += 120 * 10**9
    assert execution.run(trial_runtime[2], **request) == result and execution.resume() == result
    assert owner.store.version() == version and len(launches) == 1
    assert service.inspect(fact_key(result['fact']['request']))['current_activation'] == 'HISTORICAL_ONLY'
    state = owner.store.audit(); owner.store.snapshot(); assert owner.store.recover() == state
    assert not result['goal_completed'] and result['independent_review_status'] == 'NOT_PERFORMED'
    with pytest.raises(Conflict, match='request changed'):
        execution.run(trial_runtime[2], **{**request, 'idempotency_key': 'new_experiment'})


@pytest.mark.parametrize('boundary', ['G', 'ASSESSMENT', 'DECISION'])
def test_actual_cancel_last_G_and_appraisal_COMMIT_no_new_machine_facts(trial_runtime, monkeypatch, boundary):
    owner, lease, service, execution = unit(trial_runtime)
    threads = []; results = []; triggered = False
    def cancellation():
        nonlocal triggered
        if triggered: return
        triggered = True
        thread = threading.Thread(target=lambda: results.append(execution.cancel()))
        threads.append(thread); thread.start()
        assert execution._cancelled.wait(1) and thread.is_alive()
    if boundary == 'G':
        gate = owner._check_release_gate
        def cancel_gate(attempt): cancellation(); return gate(attempt)
        monkeypatch.setattr(owner, '_check_release_gate', cancel_gate)
    else:
        commit = owner.store._commit
        def cancel_commit(db, event, key, payload, *args, **kwargs):
            value = next((v for section, k, v in payload['put'] if section == SECTION and k), None)
            actual = None if value is None else 'DECISION' if 'machine_verification' in value else 'ASSESSMENT'
            result = commit(db, event, key, payload, *args, **kwargs)
            if actual == boundary: cancellation()
            return result
        monkeypatch.setattr(owner.store, '_commit', cancel_commit)
    try:
        with pytest.raises(Conflict, match='cancelled'):
            execution.run(trial_runtime[2], idempotency_key='cancel', expected_state_version=owner.store.version())
    finally:
        for thread in threads: thread.join(10); assert not thread.is_alive()
    assert triggered and results[0]['status'] == 'CANCELLED_SCOPE_STOPPED' and owner.pool.snapshot()['occupied'] == 0
    attempt = owner._issued(lease); source = owner.sources._issued(attempt['source'])
    assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
    facts = owner.store.replay().get(SECTION, {})
    assert sum(bool(key) for key in facts) == (1 if boundary == 'DECISION' else 0)
    assert all('machine_verification' not in value for key, value in facts.items() if key)
    if boundary == 'G': assert not attempt['release_entered']
    with pytest.raises(Conflict, match='cancelled'):
        service.assess(lease, trial_runtime[2], idempotency_key='bypass', expected_state_version=owner.store.version())
    result = execution.resume()
    assert result['status'] == ('EXPERIMENT_ASSESSED_CANCELLED' if boundary == 'DECISION' else 'CANCELLED_SCOPE_STOPPED')


@pytest.mark.parametrize('failure', ['COLLECT', 'STOP', 'ASSESSMENT', 'DECISION', 'ASSESSMENT_ROLLBACK', 'DECISION_ROLLBACK'])
def test_original_stage_lost_results_resume_without_restart_G_or_second_consumption(trial_runtime, monkeypatch, failure):
    owner, lease, service, execution = unit(trial_runtime)
    request = {'idempotency_key': 'lost_stage', 'expected_state_version': owner.store.version()}
    fired = False
    with monkeypatch.context() as patch:
        if failure in ('COLLECT', 'STOP', 'ASSESSMENT', 'DECISION'):
            obj, name = {'COLLECT': (owner, 'collect_cpu_trial'), 'STOP': (owner, 'stop_to_terminal'),
                         'ASSESSMENT': (service, 'assess'), 'DECISION': (service, 'decide')}[failure]
            method = getattr(obj, name)
            def lost(*args, **kwargs):
                nonlocal fired
                result = method(*args, **kwargs)
                if not fired: fired = True; raise OSError('original stage lost returned receipt')
                return result
            patch.setattr(obj, name, lost)
        else:
            commit = owner.store._commit
            def rollback(db, event, key, payload, *args, **kwargs):
                nonlocal fired
                value = next((v for section, k, v in payload['put'] if section == SECTION and k), None)
                stage = None if value is None else 'DECISION' if 'machine_verification' in value else 'ASSESSMENT'
                result = commit(db, event, key, payload, *args, **kwargs)
                if stage is not None and not fired and failure == stage + '_ROLLBACK':
                    fired = True; raise OSError('original appended phase rolled back before COMMIT')
                return result
            patch.setattr(owner.store, '_commit', rollback)
        with pytest.raises(OSError): execution.run(trial_runtime[2], **request)
    assert fired and owner.pool.snapshot()['occupied'] == 0
    account = owner.store.objects('hybrid_budget_goal_heads')[0][1]
    assert account['balance']['experiment_starts']['consumed'] == 1
    # Unknown rollback retry must keep the exact original accepted-attempt fact,
    # not silently rebase its UTC/monotonic sample to a new activation.
    attempts = dict(execution._phase_attempts)
    trial_runtime[6][0] += timedelta(microseconds=1); trial_runtime[7][0] += 1000
    with monkeypatch.context() as patch:
        for obj, name in ((owner, 'start'), (owner, 'run_cpu_trial'), (owner, 'collect_cpu_trial'),
                          (owner.sources, '_runtime_release'), (subprocess, 'Popen'), (os, 'pwrite')):
            patch.setattr(obj, name, lambda *a, **k: pytest.fail('resume cannot restart/G/recollect/write'))
        result = execution.resume()
        assert execution.run(trial_runtime[2], **request) == result
    assert result['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    for phase, original in attempts.items(): assert canonical(execution._phase_facts[phase]) == original
    assert owner.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']['consumed'] == 1
    assert sum(bool(key) for key in owner.store.replay()[SECTION]) == 2
    with pytest.raises(Conflict, match='request changed'):
        execution.run(trial_runtime[2], **{**request, 'idempotency_key': 'restart'})


@pytest.mark.parametrize('change', ['EXPIRED', 'CONTROLLER_REVISION'])
def test_postSTOP_current_authority_unavailable_cannot_create_new_appraisal(trial_runtime, monkeypatch, change):
    owner, lease, service, execution = unit(trial_runtime)
    stop = owner.stop_to_terminal; changed = False
    def revoke_after_STOP(actual_lease):
        nonlocal changed
        result = stop(actual_lease)
        if not changed:
            changed = True
            if change == 'EXPIRED':
                trial_runtime[6][0] += timedelta(seconds=120); trial_runtime[7][0] += 120 * 10**9
            else:
                trial_runtime[6][0] += timedelta(seconds=1); trial_runtime[7][0] += 10**9
                # Explicit private fixture intervention, not a Unit renewal.
                owner.controller.renew(trial_runtime[2], 'external_fixture_revision',
                    expected_version=owner.store.version(), ttl_seconds=60)
        return result
    monkeypatch.setattr(owner, 'stop_to_terminal', revoke_after_STOP)
    with pytest.raises(Conflict):
        execution.run(trial_runtime[2], idempotency_key='current_guard', expected_state_version=owner.store.version())
    assert changed and owner.pool.snapshot()['occupied'] == 0 and execution._phase_attempts == {}
    assert not owner.store.replay().get(SECTION)
    with monkeypatch.context() as patch:
        for obj, name in ((owner, 'start'), (owner, 'run_cpu_trial'), (owner.controller, 'renew')):
            patch.setattr(obj, name, lambda *a, **k: pytest.fail('no restart/automatic renewal'))
        with pytest.raises(Conflict): execution.resume()
    assert not owner.store.replay().get(SECTION)
    assert owner.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']['consumed'] == 1


def test_typed_original_CPU_unit_and_actual_fork_no_capability_or_HTTP_adoption(trial_runtime):
    owner = trial_runtime[0]; _, lease = grant_and_lease(trial_runtime)
    service = CpuAssessmentService(owner); output = CandidateOutputService(owner)
    with pytest.raises(Conflict): EngineeringExecutionUnit(owner, lease, output)
    with pytest.raises(TypeError): CpuTrialExecutionUnit(owner, lease, output)
    execution = CpuTrialExecutionUnit(owner, lease, service)
    with pytest.raises(PermissionError): owner.collect_cpu_trial(lease)
    read_fd, write_fd = os.pipe(); pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            for call in (execution.cancel, execution.resume, lambda: owner.start(lease)):
                try: call()
                except PermissionError: pass
                else: raise AssertionError('fork adopted original CPU unit')
            os.write(write_fd, b'OK')
        finally: os._exit(0)
    os.close(write_fd)
    try:
        _, status = os.waitpid(pid, 0)
        assert status == 0 and os.read(read_fd, 16) == b'OK'
    finally: os.close(read_fd)
    assert execution.cancel()['status'] == 'CANCELLED_SCOPE_STOPPED'
    assert owner.pool.snapshot()['occupied'] == 0 and not owner._issued(lease)['spawn_entered']


def test_existing_HTTP_cannot_be_rebound_to_CPU_unit(trial_runtime):
    owner = trial_runtime[0]; _, lease = grant_and_lease(trial_runtime)
    service = CpuAssessmentService(owner)
    FixtureRuntimeControlService(owner, owner.store._hybrid_auth_owner, origin='http://127.0.0.1:8765')
    with pytest.raises(Conflict): CpuTrialExecutionUnit(owner, lease, service)
    assert owner._execution_units == {}


@pytest.mark.parametrize('phase', ['ASSESSMENT', 'DECISION'])
def test_rejected_internal_writer_CAS_does_not_poison_unaccepted_phase(trial_runtime, monkeypatch, phase):
    owner, lease, service, execution = unit(trial_runtime)
    method_name = 'assess' if phase == 'ASSESSMENT' else 'decide'; method = getattr(service, method_name)
    with monkeypatch.context() as patch:
        def stale(*args, **kwargs):
            owner.store.transact_objects('FIXTURE_PROGRESS', 'internal_writer_wait', [], lambda state: None,
                expected=kwargs['expected_state_version'])
            return method(*args, **kwargs)
        patch.setattr(service, method_name, stale)
        with pytest.raises(Conflict, match='stale expected version'):
            execution.run(trial_runtime[2], idempotency_key='internal_cas', expected_state_version=owner.store.version())
    slot = 'assessment' if phase == 'ASSESSMENT' else 'decision'
    assert slot not in execution._phase_requests and slot not in execution._phase_attempts
    assert owner.pool.snapshot()['occupied'] == 0
    with monkeypatch.context() as patch:
        for obj, name in ((owner, 'start'), (owner, 'run_cpu_trial'), (owner.sources, '_runtime_release'), (subprocess, 'Popen')):
            patch.setattr(obj, name, lambda *a, **k: pytest.fail('phase repair cannot restart original experiment'))
        assert execution.resume()['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    assert owner.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']['consumed'] == 1


def test_unknown_CPU_start_partial_parent_FD_cleanup_retains_exposure_no_fake_terminal(trial_runtime, monkeypatch):
    owner, lease, service, execution = unit(trial_runtime)
    attempt = owner._issued(lease); source = owner.sources._issued(attempt['source'])
    retained = source['fds']['program']; close = os.close
    with monkeypatch.context() as patch:
        def unknown(*args, **kwargs): raise OSError('unknown original CPU Popen outcome')
        def fail_close(fd):
            if fd == retained: raise OSError('original program FD close temporarily unavailable')
            return close(fd)
        patch.setattr(subprocess, 'Popen', unknown); patch.setattr(os, 'close', fail_close)
        with pytest.raises(OSError):
            execution.run(trial_runtime[2], idempotency_key='unknown', expected_state_version=owner.store.version())
    assert owner.pool.snapshot()['occupied'] == 1 and attempt['terminal'] is None
    assert source['fds']['program'] == retained and os.fstat(retained) and execution.cleanup_error
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('unknown cannot retry Popen'))
        result = execution.resume()
    assert result['status'] == 'UNKNOWN_RESULT_UNAVAILABLE' and result['cleanup_error']
    assert all(fd is None for fd in source['fds'].values()) and source['status'] == 'UNKNOWN'
    assert owner.pool.snapshot()['occupied'] == 1 and attempt['terminal'] is None
    account = owner.store.objects('hybrid_budget_goal_heads')[0][1]
    assert account['balance']['experiment_starts']['consumed'] == 0
    assert account['balance']['experiment_starts']['unknown_exposure'] == 1
    assert not owner.store.replay().get(SECTION)
    assert not owner.shutdown_safety()['pool_slots_freed'] and owner.pool.snapshot()['occupied'] == 1
