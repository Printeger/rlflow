"""Actual finite CPU arithmetic/source/STOP; zero native model/GPU execution."""
from dataclasses import replace
from copy import deepcopy
import hashlib
import os
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from rlflow.hybrid_cpu_trial import registration, KIND, inputs, validate_result
from rlflow.hybrid_budget_ledger import derived_heads
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_fixture_runtime_reads import FixtureTaskReader
from rlflow.hybrid_goals import digest
from rlflow.store import Conflict
from tests import test_hybrid_working_plan_service as plan_module
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_fixture_runtime import runtime, _FIXED_CPU_POPEN


@pytest.fixture
def trial_runtime(tmp_path, native_setup, request, monkeypatch):
    # All proposal/config changes precede this NEW isolated original approval.
    # The fake model catalog/version are nonexecuting preparation only.
    root = Path(__file__).resolve().parents[1]/'rlflow'
    pins = ['sha256:'+hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('hybrid_runtime_fixture.py','hybrid_cpu_trial.py')]
    registered = registration(*pins)
    native_config, bound = plan_module.native_config, plan_module.bound
    def config():
        value = native_config()
        value['tools']['cpu_trial'] = registered['tool']
        value['commands']['cpu_trial'] = registered['command']
        value['evaluation_rules']['cpu_trial_rule'] = registered['rule']
        value['resource_profile'] = registered['resources']
        return value
    def proposal(configuration):
        registry, value = bound(configuration)
        value.update(goal_kind='research', objective='Measure the fixed seeded PI estimator against baseline3; preserve negative results.')
        value['allowed_tools'] = ['cpu_trial']; value['scope']['allowed_command_templates'] = ['cpu_trial']
        value['evaluation_data'] = {'mode':'EXPLICIT_NONE','datasets':[],
            'evaluation_rule':{'id':'cpu_trial_rule','version_hash':digest(registered['rule'])}}
        value['budget']['experiment_starts'] = 3
        value['stop_rules'] = ['Only exact fixed CPU numerical trial; no model/GPU/network/candidate execution.']
        value['global_conditions'][0]['description'] = 'Pinned raw samples independently verified, including negative results.'
        value['global_conditions'][0]['verification']['rule'] = 'Exact CPU trial evaluator and complete original source required.'
        return registry, value
    monkeypatch.setattr(plan_module, 'native_config', config)
    monkeypatch.setattr(plan_module, 'bound', proposal)
    record = BudgetService.record
    def reserve_start(self, command, token):
        if command.get('action') == 'RESERVE': command['amount']['experiment_starts'] = 1
        return record(self, command, token)
    monkeypatch.setattr(BudgetService,'record',reserve_start)
    fixture = runtime.__wrapped__(tmp_path, native_setup, request, monkeypatch)
    context = next(fixture)
    def fixed_trial_only(argv, **kwargs):
        assert argv[:4] == [sys.executable,'-B','-I','-S']
        assert len(argv) == 8 and argv[4].startswith('/proc/self/fd/') and argv[7] == 'cpu_trial'
        assert kwargs['env'] == {'PATH':'/usr/bin:/bin'} and kwargs['close_fds'] is True
        return _FIXED_CPU_POPEN(argv, **kwargs)
    monkeypatch.setattr(subprocess,'Popen',fixed_trial_only)
    try: yield context
    finally: fixture.close()


def grant_and_lease(context):
    owner, bundle, token, observation, claim, *_ = context
    grant = owner.issue_cpu_trial_grant(bundle, token, observation)
    lease = owner.register(bundle, token, observation, claim, request_key='cpu_trial',
                           scenario='cpu_trial', cpu_grant=grant)
    return grant, lease


def test_actual_cpu_trial_raw_evaluation_durable_result_stop_and_duplicate(trial_runtime, monkeypatch):
    owner = trial_runtime[0]; grant, lease = grant_and_lease(trial_runtime)
    batch = owner._register_release
    def timed(attempt):
        before = time.monotonic()
        try: return batch(attempt)
        finally: print('actual_cpu_trial_identity_release_batch_seconds',time.monotonic()-before)
    monkeypatch.setattr(owner,'_register_release',timed)
    release = owner._check_release_gate
    def timed_release(attempt):
        before = time.monotonic()
        print('actual_cpu_trial_before_G_elapsed',before-attempt['spawn_monotonic'])
        try: return release(attempt)
        finally: print('actual_cpu_trial_release_gate_seconds',time.monotonic()-before)
    monkeypatch.setattr(owner,'_check_release_gate',timed_release)
    try: result = owner.run_cpu_trial(lease)
    except BaseException:
        attempt = owner._issued(lease); source = owner.sources._issued(attempt['source'])
        print('actual_cpu_trial_failure_diagnostic', {'returncode':source['producer'].returncode,
            'spawn_elapsed':time.monotonic()-attempt['spawn_monotonic'],
            'stderr':(source['path']/'stderr.log').read_text(),
            'source_bytes':(source['path']/'events.jsonl').stat().st_size})
        raise
    value = json.loads(result.raw)
    attempt = owner._issued(lease); source = owner.sources._issued(attempt['source'])
    print('actual_cpu_trial_metrics',json.dumps({k:value[k] for k in
        ('inside_counts','estimates','mean_absolute_error','baseline_absolute_error','hypothesis_supported','cpu_ns','worker_wall_ns')}))
    assert value['raw_samples'] == inputs() and value['grant_id'] == grant.id
    assert value['verification'] == 'RAW_VALUES_VERIFIED' and value['evidence_activation'] == 'AUDIT_ONLY'
    assert not value['goal_completed'] and value['resource_enforcement'] == 'partial'
    assert value['source_sha256'] == 'sha256:'+hashlib.sha256((source['path']/'events.jsonl').read_bytes()).hexdigest()
    assert source['producer'].returncode == 0 and all(fd is None for fd in source['fds'].values())
    assert owner.pool.snapshot()['occupied'] == 0
    current = owner._current(attempt)
    assert current['status'] == 'SETTLED' and current['fixture_runtime']['origin']['kind'] == KIND
    assert current['fixture_runtime']['cpu_trial_result'] == value
    account = owner.store.objects('hybrid_budget_goal_heads')[0][1]
    assert account['balance']['experiment_starts']['consumed'] == 1
    before = owner.store.version()
    assert owner.run_cpu_trial(lease) is result and owner.collect_cpu_trial(lease) is result
    assert owner.store.version() == before
    reader = FixtureTaskReader(owner.store,project_id=owner.workspace.project_id,store_epoch=owner.workspace.store_epoch)
    assert reader.tasks()['items'] == []  # never falsely labeled protocol Task
    state = owner.store.audit(); assert owner.store.replay() == state
    owner.store.snapshot(); assert owner.store.recover() == state
    for field in ('cpu_ns','source_sha256','raw_samples'):
        bad = deepcopy(value)
        if field == 'cpu_ns': bad[field] += 1
        elif field == 'source_sha256': bad[field] = 'sha256:'+'0'*64
        else: bad[field][0]['points'][0][0] ^= 1
        with pytest.raises(Conflict): validate_result(bad,attempt['origin'],attempt['producer_identity'])
    started = deepcopy(attempt['entries']['STARTED_AS_OBSERVED'])
    started['request']['fixture_runtime']['cpu_trial_release_attempted'] = False
    started['request_hash'] = digest(started['request'])
    with pytest.raises(Conflict,match='release/result phase'): derived_heads(started)


def test_actual_grant_identity_and_no_G_stop_consume_zero(trial_runtime):
    owner, bundle, token, observation, claim, *_ = trial_runtime
    grant = owner.issue_cpu_trial_grant(bundle,token,observation); before=owner.store.version()
    for bad in (replace(grant), json.loads(grant.raw), None):
        with pytest.raises(PermissionError):
            owner.register(bundle,token,observation,claim,request_key='bad',scenario='cpu_trial',cpu_grant=bad)
    with pytest.raises(PermissionError):
        owner.register(bundle,token,observation,claim,request_key='upgrade',cpu_grant=grant)
    assert owner.store.version() == before
    lease = owner.register(bundle,token,observation,claim,request_key='original',scenario='cpu_trial',cpu_grant=grant)
    with pytest.raises(Conflict,match='complete original CPU trial source'):
        owner.collect_cpu_trial(lease)
    assert not owner._cpu_results
    with pytest.raises(Conflict,match='another attempt'):
        owner.register(bundle,token,observation,claim,request_key='second',scenario='cpu_trial',cpu_grant=grant)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0
    account = owner.store.objects('hybrid_budget_goal_heads')[0][1]
    assert account['balance']['experiment_starts']['consumed'] == 0
    assert not owner._issued(lease)['spawn_entered']


def test_real_trial_result_FD_close_failure_retains_exposure_then_original_cap_retry(trial_runtime,monkeypatch):
    owner=trial_runtime[0]; _,lease=grant_and_lease(trial_runtime)
    source=owner.sources._issued(owner._issued(lease)['source']); target=source['fds']['read']
    close=os.close; failed=[]
    def partial(fd):
        if fd == target and not failed: failed.append(True); raise OSError('original CPU trial result FD close fault')
        return close(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os,'close',partial)
        with pytest.raises(Conflict,match='partial cleanup retained'): owner.run_cpu_trial(lease)
    assert failed and source['producer'].returncode == 0 and source['fds']['read'] == target
    assert owner.pool.snapshot()['occupied'] == 1
    current=owner._current(owner._issued(lease))
    assert current['status'] == 'UNKNOWN' and current['fixture_runtime']['phase'] == 'STOP_REQUESTED'
    original=owner._cpu_results[id(lease)]; size=(source['path']/'events.jsonl').stat().st_size
    assert owner.run_cpu_trial(lease) is original
    assert all(fd is None for fd in source['fds'].values()) and owner.pool.snapshot()['occupied'] == 0
    assert (source['path']/'events.jsonl').stat().st_size == size


def test_original_protocol_approval_cannot_issue_cpu_trial_grant(runtime):
    owner, bundle, token, observation, *_ = runtime; before = owner.store.version()
    with pytest.raises(Conflict,match='exact approved fixed CPU trial'):
        owner.issue_cpu_trial_grant(bundle,token,observation)
    assert owner.store.version() == before and not owner._cpu_grants


def test_cpu_trial_registration_closure_readonly_diagnostic(trial_runtime):
    # Nonexecution diagnosis after two actual unreleased-child failures. This
    # runs the original historical closure before Popen, not a slower child run.
    import cProfile
    import pstats
    owner = trial_runtime[0]; _, lease = grant_and_lease(trial_runtime)
    attempt = owner._issued(lease); value = attempt['entries']['REGISTER_NO_HANDOFF']
    profile = cProfile.Profile(); profile.runcall(owner._confirm_entry,attempt,value)
    pstats.Stats(profile).sort_stats('cumtime').print_stats(18)
    assert not attempt['spawn_entered'] and not attempt['release_entered']
