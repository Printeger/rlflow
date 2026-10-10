"""Two actual independently approved projects, one shared original pool."""
from dataclasses import replace
import copy
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import select
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from rlflow.hybrid_candidate_output_service import CandidateOutputService
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from rlflow.hybrid_engineering_execution_unit import EngineeringExecutionUnit
from rlflow.hybrid_engineering_patch import BEFORE, AFTER, TARGET
from rlflow.hybrid_fixture_runtime import FixtureRuntimeOwner
from rlflow.hybrid_goals import digest
from rlflow.hybrid_host_execution import HostExecutionService
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict
from tests.test_execution_adapter import native_config, setup as native_setup
from tests.test_hybrid_fixture_runtime import _FIXED_CPU_POPEN
from tests.test_hybrid_registry import bound
from tests.test_hybrid_working_plan_service import plans


def profile(project, kind):
    from rlflow.hybrid_cpu_trial import registration as cpu_registration
    from rlflow.hybrid_engineering_patch import registration as engineering_registration
    root = Path(__file__).resolve().parents[1] / 'rlflow'
    names = ('hybrid_runtime_fixture.py', 'hybrid_cpu_trial.py') if kind == 'cpu_trial' else (
        'hybrid_engineering_fixture.py', 'hybrid_engineering_patch.py')
    pins = ['sha256:' + hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names]
    registered = (cpu_registration if kind == 'cpu_trial' else engineering_registration)(*pins)
    def config():
        value = native_config(); value['project_id'] = project
        value['tools'][kind] = registered['tool']; value['commands'][kind] = registered['command']
        value['evaluation_rules'][kind + '_rule'] = registered['rule']
        value['resource_profile'] = registered['resources']
        return value
    def proposal(configuration):
        registry, value = bound(configuration)
        value['project_id'] = project
        value['goal_kind'] = 'research' if kind == 'cpu_trial' else 'engineering'
        value['objective'] = 'Measure fixed seeded PI baseline.' if kind == 'cpu_trial' else 'Repair fixed add subtraction bug.'
        value['allowed_tools'] = [kind]; value['scope']['allowed_command_templates'] = [kind]
        value['evaluation_data'] = {'mode': 'EXPLICIT_NONE', 'datasets': [],
            'evaluation_rule': {'id': kind + '_rule', 'version_hash': digest(registered['rule'])}}
        for key in ('model_sessions', 'model_input_tokens', 'model_output_tokens', 'gpu_device_seconds',
                    'experiment_starts', 'experiment_retries'):
            value['budget'][key] = 3 if key == 'experiment_starts' and kind == 'cpu_trial' else 0
        return registry, value
    return {'project_id': project, 'config': config, 'bound': proposal,
            'source': BEFORE.decode() if kind == 'engineering_patch' else 'print(42)\n',
            'amount': {'wall_seconds': 10, 'experiment_starts': int(kind == 'cpu_trial')}}


@pytest.fixture
def shared(tmp_path, native_setup, monkeypatch):
    tmp_path.chmod(0o700); pool = HostPoolOwner.create_fixture(tmp_path)
    fixtures = []; contexts = []; units = []
    try:
        for index, kind in enumerate(('cpu_trial', 'engineering_patch')):
            parent = pool.projects_root / ('project_' + str(index)); parent.mkdir(mode=0o700)
            fixture = plans.__wrapped__(parent, native_setup,
                SimpleNamespace(param=profile('shared_project_' + str(index), kind)), monkeypatch)
            fixtures.append(fixture)
            owner, token, observation, _, reserve, utc, mono = next(fixture)
            member = pool.register_project(owner.installation, owner.material,
                                           expected_version=pool.snapshot()['version'])
            runtime = FixtureRuntimeOwner(pool, member, owner)
            bundle = owner.prepare_plan(token, observation, 'shared_plan')
            owner.persist_intent(bundle, token, observation, expected_version=owner.store.version())
            owner.publish(bundle, token, observation, expected_version=owner.store.version())
            contexts.append((runtime, bundle, token, observation, reserve, utc, mono, kind))
        host = HostExecutionService(pool)
        for context in contexts:
            runtime, bundle, token, observation, reserve, utc, mono, kind = context
            claim = pool.claim(runtime.membership, expected_version=pool.snapshot()['version'],
                               request_key='shared_claim', seconds=60)
            if kind == 'cpu_trial':
                grant = runtime.issue_cpu_trial_grant(bundle, token, observation)
                lease = runtime.register(bundle, token, observation, claim, request_key='cpu',
                                         scenario=kind, cpu_grant=grant)
                unit = CpuTrialExecutionUnit(runtime, lease, CpuAssessmentService(runtime))
            else:
                grant = runtime.issue_engineering_patch_grant(bundle, token, observation)
                lease = runtime.register(bundle, token, observation, claim, request_key='engineering',
                                         scenario=kind, engineering_grant=grant)
                output = CandidateOutputService(runtime); accept = output.accept_machine
                def advance(*args, _accept=accept, _utc=utc, _mono=mono, **kwargs):
                    _utc[0] += timedelta(microseconds=1); _mono[0] += 1000
                    return _accept(*args, **kwargs)
                output.accept_machine = advance
                unit = EngineeringExecutionUnit(runtime, lease, output)
            host.bind_unit(unit); units.append(unit)
        def fixed_only(argv, **kwargs):
            assert argv[:4] == [sys.executable, '-B', '-I', '-S']
            assert argv[4].startswith('/proc/self/fd/') and argv[7] in ('cpu_trial', 'engineering_patch')
            assert len(argv) == (8 if argv[7] == 'cpu_trial' else 9)
            assert kwargs['env'] == {'PATH': '/usr/bin:/bin'} and kwargs['close_fds'] is True
            return _FIXED_CPU_POPEN(argv, **kwargs)
        monkeypatch.setattr(subprocess, 'Popen', fixed_only)
        yield host, units
    finally:
        for context in contexts:
            runtime = context[0]
            if runtime._live:
                try: runtime.shutdown()
                finally:
                    if runtime._live: runtime.shutdown_safety()
        for fixture in reversed(fixtures): fixture.close()
        if pool._live: pool.shutdown()


def requests(units):
    return [(unit.lease, unit.runtime._issued(unit.lease)['token'],
             {'idempotency_key': 'shared_execution', 'expected_state_version': unit.runtime.store.version()})
            for unit in units]


def test_one_pool_transaction_memo_rereads_whole_source_and_never_crosses_transaction(shared, monkeypatch):
    from rlflow import hybrid_budget_ledger as ledger
    from rlflow.store import Store
    host, units = shared; pool = host.pool
    validations = []; validate = ledger.validate_record
    def counted(*args, **kwargs):
        # Count only the expansion this memo owns. Whole-event verification
        # deliberately still invokes its independent validators every read.
        if sys._getframe(1).f_code.co_name == '_verify_runtime_source':
            validations.append(args[1])
        return validate(*args, **kwargs)
    monkeypatch.setattr(ledger, 'validate_record', counted)
    began = time.monotonic()
    with pool._transaction() as db:
        pool._state(db); first = len(validations)
        pool._state(db)
        assert first == 2 and len(validations) == first
        assert len(pool._runtime_source_proofs[id(db)][2]) == 2
    assert pool._runtime_source_proofs == {}
    print('actual_two_project_pool_source_proof_seconds', time.monotonic() - began, flush=True)
    with pool._transaction() as db: pool._state(db)
    assert len(validations) == 2 * first and pool._runtime_source_proofs == {}
    whole_event = Store._budget_event
    with pytest.raises(Conflict, match='original Project event differs'):
        with pool._transaction() as db:
            pool._state(db)
            def changed(*args, **kwargs):
                proof = whole_event(*args, **kwargs)
                return (proof[0], [])
            with monkeypatch.context() as patch:
                patch.setattr(Store, '_budget_event', changed)
                pool._state(db)
    assert pool._runtime_source_proofs == {}
    assert all(not unit.runtime._issued(unit.lease)['spawn_entered'] for unit in units)


def test_no_worker_original_HANDOFF_writer_diagnostic_and_unknown_parent_retirement(shared, monkeypatch):
    import cProfile
    import pstats
    host, units = shared; cpu = units[0]; owner = cpu.runtime
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('nonexecuting writer diagnostic'))
    profiler = cProfile.Profile()
    try:
        with owner.pool._lock, cpu._operation():
            cpu._request = {'idempotency_key': 'diagnostic_handoff', 'expected_state_version': owner.store.version()}
            profiler.enable()
            try: owner._write_phase(owner._issued(cpu.lease), 'HANDOFF_UNKNOWN')
            finally: profiler.disable()
        pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(25)
        assert not owner._issued(cpu.lease)['spawn_entered']
        assert 'HANDOFF_UNKNOWN' in owner._issued(cpu.lease)['entries']
    finally:
        # Durable HANDOFF cannot be turned into a fake NO_HANDOFF refund.
        if owner._live: owner.shutdown_safety()
    assert host.pool.snapshot()['occupied'] == 2


def test_readonly_pool_check_full_fresh_global_closure_once_and_last_deadline(shared, monkeypatch):
    host, units = shared; pool = host.pool
    states = []; state = pool._state
    def counted(db):
        result = state(db); states.append(result); return result
    monkeypatch.setattr(pool, '_state', counted)
    claim = units[0].runtime._issued(units[0].lease)['claim']
    result = pool.check(claim)
    assert result['state'] == 'FIXTURE_LINKED' and len(states) == 1
    clocks = []; clock = pool._claim_clocks
    def expiry(value):
        clocks.append(value)
        if len(clocks) == 2: raise Conflict('original final claim deadline expired')
        return clock(value)
    monkeypatch.setattr(pool, '_claim_clocks', expiry)
    with pytest.raises(Conflict, match='final claim deadline'): pool.check(claim)
    assert len(states) == 2 and len(clocks) == 2
    assert pool._sql_active == {} and pool._runtime_source_proofs == {}


def test_actual_two_projects_cpu384_engineering_one_write_same_pool_STOP_FREE(shared, monkeypatch):
    host, units = shared; cpu, engineering = units
    assert cpu.runtime.store.root != engineering.runtime.store.root
    assert cpu.runtime.workspace.project_id != engineering.runtime.workspace.project_id
    assert cpu.runtime.pool is engineering.runtime.pool is host.pool
    timings = []; returned = {}
    def timed_call(obj, name, project, detail=None):
        original_method = getattr(obj, name)
        def measured(*args, **kwargs):
            began = time.monotonic()
            try:return original_method(*args, **kwargs)
            finally:
                ended = time.monotonic()
                row = {'project': project, 'method': name, 'begin': began,
                       'end': ended, 'duration': ended - began}
                if detail is not None:row.update(detail())
                timings.append(row)
                if name == 'start':returned[project] = ended
        monkeypatch.setattr(obj, name, measured)
    for unit in units:
        owner = unit.runtime; project = owner.workspace.project_id
        attempt = owner._leases[id(unit.lease)]
        def source_state(_attempt=attempt, _owner=owner):
            source = _owner.sources._sources.get(id(_attempt['source']))
            return {} if source is None else {'source_' + key: source[key]
                                             for key in ('status', 'offset', 'end')}
        for name in ('start', 'poll', '_current', '_write_phase'):
            timed_call(owner, name, project, source_state)
        timed_call(owner.sources, 'seal', project, source_state)
    for name in ('apply', 'reconcile', 'accept_machine'):
        timed_call(engineering.output, name, engineering.runtime.workspace.project_id)
    writes = []; original = os.pwrite
    monkeypatch.setattr(os, 'pwrite', lambda fd, data, offset: (writes.append((data, offset)), original(fd, data, offset))[1])
    for unit in units:
        owner = unit.runtime
        witness_calls = []; witness = owner.workspace.preparation.issue_material_witness
        def issued(*args, _witness=witness, _calls=witness_calls, **kwargs):
            result = _witness(*args, **kwargs); _calls.append(result); return result
        monkeypatch.setattr(owner.workspace.preparation, 'issue_material_witness', issued)
        gate = owner._gate; borrowed = []
        @contextmanager
        def retained(attempt, phase, _gate=gate, _owner=owner, _borrowed=borrowed):
            material = _owner._start_materials
            assert material[0] is attempt and material[1] == threading.get_ident()
            _borrowed.append((material[2], material[2][1].deadline, material[2][2].inventory.deadline))
            with _gate(attempt, phase): yield
        monkeypatch.setattr(owner, '_gate', retained)
        owner._test_material_calls = witness_calls, borrowed
        for name in ('_register_release', '_check_release_gate'):
            method = getattr(owner, name)
            def timed(attempt, _method=method, _name=name, _owner=owner):
                began = time.monotonic()
                try: return _method(attempt)
                finally:
                    print('shared_original_gate_timing', _owner.workspace.project_id, _name,
                          'duration', time.monotonic() - began,
                          'since_spawn', time.monotonic() - attempt['spawn_monotonic'], flush=True)
            monkeypatch.setattr(owner, name, timed)
    try:results = host.run_many(requests(units))
    finally:
        for row in timings:
            row['since_start_return'] = row['begin'] - returned[row['project']] if row['project'] in returned else None
        print('shared_result_window_diagnostic', json.dumps(sorted(timings, key=lambda row: row['begin'])), flush=True)
    assert all(row['error'] is None for row in results), results
    assert [row['result']['status'] for row in results] == [
        'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW', 'MACHINE_ACCEPTED_PENDING_REVIEW']
    assert writes == [(AFTER, 0)]
    raw = json.loads(cpu.runtime._cpu_results[id(cpu.lease)].raw)
    assert sum(len(row['points']) for row in raw['raw_samples']) == 384
    assert raw['inside_counts'] == [96, 101, 104]
    assert cpu.runtime.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']['consumed'] == 1
    assert host.pool.snapshot()['occupied'] == 0
    nonces = []
    for unit in units:
        attempt = unit.runtime._issued(unit.lease); source = unit.runtime.sources._issued(attempt['source'])
        assert source['producer'].poll() == 0 and all(fd is None for fd in source['fds'].values())
        nonces.append(attempt['origin']['nonce'])
        assert attempt['origin']['pool_id'] == host.pool.binding['pool_id']
        calls, borrowed = unit.runtime._test_material_calls
        assert len(calls) == 1 and len(borrowed) == 2
        assert borrowed[0][0] is borrowed[1][0] and borrowed[0][1:] == borrowed[1][1:]
        assert unit.runtime._start_materials is None and unit.runtime.plans.builder._witnesses == {}
        assert unit.runtime.plans.installation._bootstrap_contexts == {}
        state = unit.runtime.store.audit(); unit.runtime.store.snapshot(); assert unit.runtime.store.recover() == state
    assert len(set(nonces)) == 2 and all(not row['result']['goal_completed'] for row in results)
    from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
    from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
    from rlflow.hybrid_cpu_assessment import fact_key as assessment_key
    from rlflow.store import Store
    versions = [unit.runtime.store.version() for unit in units]
    readers = []
    for unit, cls in ((cpu, CpuAssessmentReader), (engineering, CandidateOutputReader)):
        runtime = unit.runtime
        cold = Store.attach_existing(runtime.store.root, project_id=runtime.workspace.project_id, data_mode='fixture')
        readers.append(cls(cold, runtime.plans.registry, project_id=runtime.workspace.project_id,
                           store_epoch=runtime.workspace.store_epoch, clock=runtime.controller.clock))
    with monkeypatch.context() as patch:
        for obj, name in ((subprocess, 'Popen'), (os, 'pwrite'), (host.pool, 'check')):
            patch.setattr(obj, name, lambda *a, **k: pytest.fail('cold project facts cannot execute or inspect current pool'))
        cpu_key = assessment_key(cpu._phase_facts['assessment']['request'])
        engineering_key = engineering._accept_request['output_key']
        research = readers[0].assessment(cpu_key)['experiment']
        candidate = readers[1].output_detail(engineering_key)['candidate']
        assert readers[0].assessment(engineering_key) is None
        assert readers[1].output_detail(cpu_key) is None
        for dto in (research, candidate):
            assert not dto['controls_available'] and not dto['goal_completed']
            assert dto['current_execution_status'] == 'UNKNOWN' and dto['resource_release_status'] == 'NOT_OBSERVED'
    assert [unit.runtime.store.version() for unit in units] == versions
    print('actual_shared_results', json.dumps({'pool_id': host.pool.binding['pool_id'], 'nonces': nonces,
        'cpu_source_sha256': raw['source_sha256'], 'samples': 384, 'pwrite_count': len(writes),
        'occupied': 0, 'independent_review': 'NOT_PERFORMED'}))


def test_cancel_all_latches_every_original_before_pool_cleanup_and_invalid_batch_zero_submit(shared, monkeypatch):
    host, units = shared; batch = requests(units)
    with pytest.raises(Conflict): HostExecutionService(host.pool)
    monkeypatch.setattr('rlflow.hybrid_host_execution.ThreadPoolExecutor', lambda **k: pytest.fail('invalid batch must not submit'))
    invalid = [batch + [batch[0]], [batch[0], (replace(batch[1][0]), batch[1][1], batch[1][2])],
               [batch[0], (batch[1][0], batch[0][1], batch[1][2])],
               [batch[0], (batch[1][0], batch[1][1], {**batch[1][2], 'extra': True})]]
    from rlflow.hybrid_budget import MAXIMUM
    invalid.append([batch[0], (batch[1][0], batch[1][1],
                              {**batch[1][2], 'expected_state_version': MAXIMUM + 1})])
    for value in invalid:
        with pytest.raises((Conflict, PermissionError, ProtocolError)): host.run_many(value)
    assert all(not unit.runtime._issued(unit.lease)['spawn_entered'] for unit in units)
    results = []; thread = threading.Thread(target=lambda: results.extend(host.cancel_all()))
    with host.pool._lock:
        thread.start()
        assert all(unit._cancelled.wait(1) for unit in units)
        assert thread.is_alive()
    thread.join(20); assert not thread.is_alive()
    assert all(row['error'] is None and row['result']['status'] == 'CANCELLED_SCOPE_STOPPED' for row in results)
    assert host.pool.snapshot()['occupied'] == 0


def test_cancel_one_before_G_does_not_touch_other_original_scope_which_finishes(shared, monkeypatch):
    host, units = shared; cpu, engineering = units
    ready = threading.Event(); cancelled = []; threads = []; errors = []
    engineering_attempt = engineering.runtime._issued(engineering.lease)
    other_source = engineering.runtime.sources._issued(engineering_attempt['source'])
    other_fds = dict(other_source['fds']); other_version = engineering.runtime.store.version()
    other_input = engineering.runtime._engineering_grants[id(engineering_attempt['engineering_grant'])]['fd']
    start = engineering.runtime.start
    def wait_other(lease):
        assert ready.wait(15); return start(lease)
    monkeypatch.setattr(engineering.runtime, 'start', wait_other)
    gate = cpu.runtime._check_release_gate
    def cancel_cpu(attempt):
        def cancel():
            try:
                cancelled.append(host.cancel(cpu.lease))
                assert engineering.runtime.store.version() == other_version
                assert other_source['fds'] == other_fds
                assert engineering.runtime._engineering_grants[id(engineering_attempt['engineering_grant'])]['fd'] == other_input
                assert not engineering_attempt['spawn_entered']
            except BaseException as exc: errors.append(exc)
            finally: ready.set()
        thread = threading.Thread(target=cancel); threads.append(thread); thread.start()
        assert cpu._cancelled.wait(1) and thread.is_alive()
        return gate(attempt)
    monkeypatch.setattr(cpu.runtime, '_check_release_gate', cancel_cpu)
    try: results = host.run_many(requests(units))
    finally:
        ready.set()
        for thread in threads: thread.join(20); assert not thread.is_alive()
    assert len(cancelled) == 1 and cancelled[0]['status'] == 'CANCELLED_SCOPE_STOPPED'
    assert errors == []
    assert 'cancelled' in results[0]['error'] and results[0]['result'] is None
    assert results[1]['error'] is None and results[1]['result']['status'] == 'MACHINE_ACCEPTED_PENDING_REVIEW'
    assert not cpu.runtime._issued(cpu.lease)['release_entered'] and host.pool.snapshot()['occupied'] == 0


def test_actual_fourth_claim_foreign_copied_fork_capabilities_have_no_submission(shared, monkeypatch, tmp_path):
    host, units = shared; pool = host.pool
    extra = pool.claim(units[0].runtime.membership, expected_version=pool.snapshot()['version'], request_key='third', seconds=60)
    assert pool.snapshot()['occupied'] == 3
    with pytest.raises(Conflict, match='exhausted'):
        pool.claim(units[1].runtime.membership, expected_version=pool.snapshot()['version'], request_key='fourth')
    closing = pool.request_close_no_handoff(extra, expected_version=pool.snapshot()['version'])
    witness = pool.close_original(closing)
    pool.complete_close(witness, expected_version=pool.snapshot()['version'])
    foreign = HostPoolOwner.create_fixture(tmp_path)
    try:
        foreign_host = HostExecutionService(foreign)
        with pytest.raises(PermissionError): foreign_host.bind_unit(units[0])
        with pytest.raises(PermissionError): foreign_host.cancel(units[0].lease)
    finally: foreign.shutdown()
    with pytest.raises(PermissionError): copy.copy(host).cancel_all()
    with pytest.raises(PermissionError): host.bind_unit(copy.copy(units[0]))
    batch = requests(units)
    reader, writer = os.pipe(); pid = os.fork()
    if pid == 0:
        os.close(reader)
        try:
            for operation in (lambda: host.cancel_all(), lambda: host.run_many(batch)):
                try: operation()
                except PermissionError: continue
                os._exit(2)
            os.write(writer, b'DENIED'); os._exit(0)
        except BaseException: os._exit(3)
    os.close(writer)
    reaped = False
    try:
        assert select.select([reader], [], [], 5)[0]
        assert os.read(reader, 32) == b'DENIED'
        _, status = os.waitpid(pid, 0); reaped = True
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.close(reader)
        if not reaped:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
            os.waitpid(pid, 0)
    assert all(not unit.runtime._issued(unit.lease)['spawn_entered'] for unit in units)


def test_unknown_start_only_original_scope_retains_exposure_other_scope_completes(shared, monkeypatch):
    host, units = shared; cpu, engineering = units
    spawn = subprocess.Popen
    def unknown(argv, **kwargs):
        if argv[7] == 'cpu_trial': raise OSError('original CPU Popen outcome unknown')
        return spawn(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', unknown)
    try:
        results = host.run_many(requests(units))
        assert 'outcome unknown' in results[0]['error'] and results[0]['result'] is None
        assert results[1]['error'] is None and results[1]['result']['status'] == 'MACHINE_ACCEPTED_PENDING_REVIEW'
        balance = cpu.runtime.store.objects('hybrid_budget_goal_heads')[0][1]['balance']['experiment_starts']
        assert balance['consumed'] == 0 and balance['unknown_exposure'] == 1
        assert host.pool.snapshot()['occupied'] == 1
        version = engineering.runtime.store.version()
        cancelled = host.cancel_all()
        assert cancelled[0]['result']['status'] == 'UNKNOWN_CLEANUP_REQUIRED'
        assert cancelled[1]['result']['status'] == 'CANCELLED_SCOPE_STOPPED'
        assert engineering.runtime.store.version() == version and host.pool.snapshot()['occupied'] == 1
        assert cpu.runtime._start_materials is None and cpu.runtime.plans.builder._witnesses == {}
    finally:
        # Private original parent-FD retirement only, not a Host FREE/STOP claim.
        if cpu.runtime._live: cpu.runtime.shutdown_safety()
    assert host.pool.snapshot()['occupied'] == 1


def test_borrowed_original_candidate_graph_change_rejected_before_G_and_context_released(shared, monkeypatch):
    host, units = shared; cpu = units[0]; owner = cpu.runtime
    release = owner._register_release
    def changed(attempt):
        original = owner._start_materials[2]
        slot, _ = owner.workspace.working._slot(attempt['observation'])
        (slot['copy'].path / TARGET).write_bytes(b'print(43)\n')
        assert owner._start_materials[2] is original
        return release(attempt)
    monkeypatch.setattr(owner, '_register_release', changed)
    with pytest.raises(Conflict): host.run(*requests([cpu])[0][:2], **requests([cpu])[0][2])
    attempt = owner._issued(cpu.lease)
    assert not attempt['release_entered'] and owner._start_materials is None
    assert owner.plans.builder._witnesses == {} and owner.plans.installation._bootstrap_contexts == {}
    assert owner.sources._issued(attempt['source'])['producer'].poll() is not None
    assert host.pool.snapshot()['occupied'] == 1  # Other project's untouched original claim.


def test_body_validation_uses_its_captured_snapshot_not_caller_mutation(shared, monkeypatch):
    from rlflow import hybrid_host_execution as module
    host, units = shared; lease, token, body = requests(units)[0]
    original = dict(body); validate = module.validate_schema
    def mutate(schema, value):
        result = validate(schema, value)
        if schema is module.ID:
            body['idempotency_key'] = ''
            body['extra'] = True
        return result
    monkeypatch.setattr(module, 'validate_schema', mutate)
    _, captured = host._preflight(lease, token, body)
    assert captured == original and captured is not body
    assert body['idempotency_key'] == '' and body['extra'] is True
    assert all(not unit.runtime._issued(unit.lease)['spawn_entered'] for unit in units)


def test_batch_snapshot_ignores_later_mutation_and_captured_four_rejects_without_executor(shared, monkeypatch):
    from rlflow import hybrid_host_execution as module
    host, units = shared; batch = requests(units); validate = module.validate_schema
    versions = [unit.runtime.store.version() for unit in units]; calls = []
    def mutate(schema, value):
        result = validate(schema, value)
        if schema is module.ID: batch.append(batch[0])
        return result
    monkeypatch.setattr(module, 'validate_schema', mutate)
    # Nonexecuting routing assertion, NOT evidence of actual worker success.
    for unit in units:
        def captured(token, _unit=unit, **body):
            calls.append((_unit.lease, token, body)); return {'state': 'NONEXECUTING_ROUTING_DIAGNOSTIC'}
        monkeypatch.setattr(unit, 'run', captured)
    results = host.run_many(batch)
    assert len(batch) == 4 and len(results) == len(calls) == 2
    assert all(row['error'] is None for row in results)
    monkeypatch.setattr(module, 'ThreadPoolExecutor', lambda **k: pytest.fail('captured four must not submit'))
    with pytest.raises(Conflict): host.run_many(batch)
    assert [unit.runtime.store.version() for unit in units] == versions
    assert all(not unit.runtime._issued(unit.lease)['spawn_entered'] for unit in units)
