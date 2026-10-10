"""Real fixed local CPU participant; no native CLI/model/candidate execution."""
from dataclasses import replace
from contextlib import contextmanager, closing
from datetime import timedelta
import json
import hashlib
import errno
import os
import select
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from rlflow.hybrid_budget_ledger import reservation_key, entry_key, SECTIONS as BUDGET
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_fixture_runtime import FixtureRuntimeOwner
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.store import Conflict, canonical
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_working_plan_service import plans as plan_fixture

_FIXED_CPU_POPEN = subprocess.Popen


@pytest.fixture
def runtime(tmp_path, native_setup, request, monkeypatch):
    tmp_path.chmod(0o700)
    pool = HostPoolOwner.create_fixture(tmp_path)
    record = BudgetService.record
    def reserve_wall(self, command, token):
        if command.get('action') == 'RESERVE':
            command['amount']['wall_seconds'] = 10
        return record(self, command, token)
    monkeypatch.setattr(BudgetService, 'record', reserve_wall)
    def fixed_cpu_only(argv, **kwargs):
        assert argv[:4] == [sys.executable, '-B', '-I', '-S']
        assert len(argv) == 8 and argv[4].startswith('/proc/self/fd/')
        assert argv[7] in ('complete', 'missing', 'running', 'bad_ack')
        return _FIXED_CPU_POPEN(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', fixed_cpu_only)
    fixture = plan_fixture.__wrapped__(pool.projects_root, native_setup, request, monkeypatch)
    plans, token, observation, workspace, reserve, utc, mono = next(fixture)
    member = pool.register_project(plans.installation, plans.material, expected_version=0)
    claim = pool.claim(member, expected_version=1, request_key='fixture_claim', seconds=60)
    owner = FixtureRuntimeOwner(pool, member, plans)
    bundle = plans.prepare_plan(token, observation, 'runtime_plan')
    plans.persist_intent(bundle, token, observation, expected_version=plans.store.version())
    plans.publish(bundle, token, observation, expected_version=plans.store.version())
    try:
        yield owner, bundle, token, observation, claim, reserve, utc, mono
    finally:
        if owner._live:
            try: owner.shutdown()
            finally:
                if owner._live: owner.shutdown_safety()
        fixture.close()
        if pool._live: pool.shutdown()


def register(context, scenario='complete'):
    owner, bundle, token, observation, claim, *_ = context
    return owner.register(bundle, token, observation, claim, request_key='runtime', scenario=scenario)


def observed(owner, lease):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = owner.poll(lease)
        if value['phase'] == 'STARTED_AS_OBSERVED': return value
        time.sleep(.01)
    pytest.fail('original real child ACK not observed within finite deadline')


def test_actual_started_readonly_poll_completes_while_other_thread_holds_pool(runtime):
    owner, *_ = runtime
    lease = register(runtime); owner.start(lease); observed(owner, lease)
    attempt = owner._issued(lease)
    versions = (owner.store.version(), owner.pool.snapshot()['version'])
    entries = dict(attempt['entries'])
    with ThreadPoolExecutor(max_workers=1) as executor:
        with owner.pool._lock:
            future = executor.submit(owner.poll, lease, seal=True)
            value = future.result(timeout=2)
    assert value['phase'] == 'STARTED_AS_OBSERVED'
    assert versions == (owner.store.version(), owner.pool.snapshot()['version'])
    assert attempt['entries'] == entries
    owner.stop_to_terminal(lease)


def test_actual_stop_in_readonly_poll_gap_prevents_late_ACK_fact(runtime, monkeypatch):
    owner, *_ = runtime
    lease = register(runtime); attempt = owner._issued(lease)
    # Suppress only start's initial observation, not original spawn/G/ACK.
    with monkeypatch.context() as patch:
        patch.setattr(owner, 'poll', lambda *args, **kwargs: None)
        owner.start(lease)
    deadline = time.monotonic() + 3
    while owner.sources._runtime_started(owner, lease) is None:
        owner.sources.poll(attempt['source'])
        if time.monotonic() >= deadline:pytest.fail('actual original ACK unavailable')
        time.sleep(.01)
    current = owner._current; intervened = []
    def stop_after_read(original):
        value = current(original)
        if not intervened and value['fixture_runtime']['phase'] == 'RELEASE_INTENT':
            intervened.append(True)
            owner.request_stop(lease)
        return value
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_current', stop_after_read)
        value = owner.poll(lease)
    assert intervened and value['phase'] == 'STOP_REQUESTED'
    assert attempt['started_ack'] is None
    assert 'STARTED_AS_OBSERVED' not in attempt['entries']
    assert current(attempt)['fixture_runtime']['phase'] == 'STOP_REQUESTED'
    owner.stop_to_terminal(lease)


def test_real_gated_child_ack_stop_reap_and_slot_reuse(runtime, monkeypatch):
    owner, bundle, token, observation, claim, *_ = runtime
    lease = register(runtime)
    attempt = owner._issued(lease)
    assert owner._current(attempt)['fixture_runtime']['phase'] == 'REGISTER_NO_HANDOFF'
    assert owner.pool.check(claim)['state'] == 'FIXTURE_LINKED'
    assert not attempt['spawn_entered']
    phase_write = owner._write_phase
    def timed(*args, **kwargs):
        started = time.monotonic()
        try: return phase_write(*args, **kwargs)
        finally: print('fixed_cpu_phase_seconds', args[1], round(time.monotonic()-started, 6))
    monkeypatch.setattr(owner, '_write_phase', timed)
    register_release = owner._register_release
    def timed_batch(*args):
        started = time.monotonic()
        try: return register_release(*args)
        finally: print('fixed_cpu_batch_seconds', round(time.monotonic()-started, 6))
    monkeypatch.setattr(owner, '_register_release', timed_batch)
    owner.start(lease)
    value = observed(owner, lease)
    source = owner.sources._issued(attempt['source']); process = source['producer']
    assert process.pid == attempt['producer_identity']['pid']
    assert value['actual_cost_status'] == 'UNKNOWN' and not value['synthetic_tokens_settled']
    owner.start(lease)
    assert source['producer'] is process
    stopped = owner.stop_to_terminal(lease)
    assert stopped['phase'] == 'FIXTURE_SCOPE_STOPPED' and not stopped['arbitrary_tree_stop']
    assert process.poll() is not None and all(fd is None for fd in source['fds'].values())
    assert owner.pool.snapshot()['occupied'] == 0
    assert owner._current(attempt)['status'] == 'SETTLED'
    newer = owner.pool.claim(owner.membership, expected_version=owner.pool.snapshot()['version'], request_key='newer')
    owner.stop_to_terminal(lease)
    assert owner.pool.check(newer)['state'] == 'CLAIM'
    assert owner.store.audit()['version'] == owner.store.version()


def test_durable_stop_before_spawn_is_zero_wall_and_never_releases(runtime):
    owner = runtime[0]; lease = register(runtime)
    owner.request_stop(lease)
    with pytest.raises(Conflict): owner.start(lease)
    value = owner.stop_to_terminal(lease)
    assert value['wall_seconds'] == 0 and owner.pool.snapshot()['occupied'] == 0
    assert not owner._issued(lease)['spawn_entered']


def test_registered_reservation_cannot_cancel_or_close_as_no_handoff(runtime):
    owner, _, token, _, claim, reserve, *_ = runtime
    lease = register(runtime)
    command = {n: reserve[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    command.update(action='CANCEL_BEFORE_RUNTIME', idempotency_key='cancel',
                   expected_state_version=owner.store.version(), reservation_id=reservation_key(reserve))
    with pytest.raises(Conflict): owner.budget.record(command, token)
    with pytest.raises(Conflict):
        owner.pool.request_close_no_handoff(claim, expected_version=owner.pool.snapshot()['version'])
    for bad in (replace(lease), json.loads(lease.raw)):
        with pytest.raises(PermissionError): owner.start(bad)


def test_real_running_participant_stopped_after_authority_expiry(runtime):
    owner, _, _, _, _, _, utc, mono = runtime
    lease = register(runtime, 'running'); owner.start(lease); observed(owner, lease)
    process = owner.sources._issued(owner._issued(lease)['source'])['producer']
    assert process.poll() is None
    utc[0] += timedelta(seconds=120); mono[0] += 120 * 10**9
    value = owner.stop_to_terminal(lease)
    assert value['phase'] == 'FIXTURE_SCOPE_STOPPED' and process.poll() is not None
    assert owner.pool.snapshot()['occupied'] == 0


@pytest.mark.parametrize('clock', ['utc', 'mono'])
def test_final_actual_spawn_boundary_expiry_denies_popen(runtime, monkeypatch, clock):
    owner, _, _, _, _, _, utc, mono = runtime
    lease = register(runtime); original = owner._final_effect_gate; boundaries = []
    def expire(guard):
        boundaries.append(True)
        if clock == 'utc': utc[0] += timedelta(seconds=30)
        else: mono[0] += 30 * 10**9
        original(guard)
    monkeypatch.setattr(owner, '_final_effect_gate', expire)
    with pytest.raises(Conflict): owner.start(lease)
    attempt = owner._issued(lease)
    assert boundaries and not attempt['spawn_entered']
    assert owner.sources._issued(attempt['source'])['producer'] is None
    # HANDOFF_UNKNOWN without original process identity is intentionally not
    # refundable. This denial occurred BEFORE spawn_entered, so original
    # no-process evidence must still obey the recorded phase contract.
    result = owner.shutdown_safety()
    assert result['state'] == 'PHYSICAL_CLOSED_EXPOSURE_UNKNOWN'
    assert not result['refund_enabled'] and owner.pool.snapshot()['occupied'] == 1


@pytest.mark.parametrize('failure', ['insert_before', 'insert_after', 'final_expiry'])
def test_atomic_identity_release_failure_rolls_back_both_and_never_sends_g(runtime, monkeypatch, failure):
    owner, _, _, _, _, _, utc, mono = runtime
    lease = register(runtime); attempt = owner._issued(lease)
    commit = owner.store._commit; final = owner._final_deadlines; injected = []
    def fail_second(db, *args, **kwargs):
        guard = kwargs.get('_authorization')
        if guard is not None and guard.owner is owner and json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'RELEASE_INTENT':
            if failure != 'final_expiry':
                injected.append(failure)
                if failure == 'insert_after': commit(db, *args, **kwargs)
                raise OSError('fixed batch second event failure')
        return commit(db, *args, **kwargs)
    def expire_final(guard, now, sampled_mono):
        if json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'RELEASE_INTENT':
            injected.append(failure); mono[0] += 30 * 10**9
        return final(guard, now, sampled_mono)
    with monkeypatch.context() as patch:
        patch.setattr(owner.store, '_commit', fail_second)
        if failure == 'final_expiry': patch.setattr(owner, '_final_deadlines', expire_final)
        with pytest.raises(Conflict if failure == 'final_expiry' else OSError): owner.start(lease)
    assert injected and not attempt['release_entered']
    assert owner.store.version() == attempt['entries']['HANDOFF_UNKNOWN']['accepted_state_version']
    with owner.store.read_connection() as db:
        for phase in ('PROCESS_REGISTERED', 'RELEASE_INTENT'):
            key = entry_key(attempt['entries'][phase]['request'])
            assert db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?', (BUDGET[0],key)).fetchone() is None
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0


def test_actual_atomic_commit_lost_return_confirms_both_without_relaunch(runtime, monkeypatch):
    owner = runtime[0]; lease = register(runtime); attempt = owner._issued(lease)
    transaction = owner.controller.token_transaction; injected = []
    @contextmanager
    def lost_return(*args, **kwargs):
        with transaction(*args, **kwargs) as context: yield context
        guard = owner._active
        if guard is not None and json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'RELEASE_INTENT' and not injected:
            injected.append(True); raise OSError('actual owned COMMIT lost return')
    with monkeypatch.context() as patch:
        patch.setattr(owner.controller, 'token_transaction', lost_return)
        with pytest.raises(OSError, match='COMMIT lost return'): owner.start(lease)
    assert injected and not attempt['release_entered']
    process = owner.sources._issued(attempt['source'])['producer']
    before = owner.store.version()
    value = owner._register_release(attempt)
    assert value == attempt['entries']['RELEASE_INTENT']
    assert owner.store.version() == before and owner.sources._issued(attempt['source'])['producer'] is process
    assert not attempt['release_entered']
    owner.stop_to_terminal(lease)


def test_cancel_wins_registration_cas_and_no_runtime_is_created(runtime):
    owner, bundle, token, observation, claim, reserve, *_ = runtime
    command = {n:reserve[n] for n in ('project_id','data_mode','goal_ref','store_epoch')}
    command.update(action='CANCEL_BEFORE_RUNTIME',idempotency_key='cancel_first',
        expected_state_version=owner.store.version(),reservation_id=reservation_key(reserve))
    owner.budget.record(command, token)
    with pytest.raises(Conflict): register(runtime)
    assert not any(attempt['spawn_entered'] for attempt in owner._attempts.values())
    assert owner.pool.check(claim)['state'] == 'CLAIM'


@pytest.mark.parametrize('scenario', ['missing', 'bad_ack'])
def test_actual_missing_usage_or_wrong_ack_never_settles_model_tokens(runtime, scenario):
    owner = runtime[0]; lease = register(runtime, scenario); attempt = owner._issued(lease)
    if scenario == 'bad_ack':
        try: owner.start(lease)
        except Conflict: pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try: value = owner.poll(lease)
            except Conflict: continue
            if value['source']['source_status'] == 'QUARANTINED': break
            time.sleep(.01)
        assert owner._current(attempt)['fixture_runtime']['phase'] == 'RELEASE_INTENT'
        assert attempt['started_ack'] is None
    else:
        owner.start(lease); observed(owner, lease)
        value = owner.poll(lease, seal=True)
        assert value['source']['usage']['output_tokens'] is None
        assert not value['source']['settlement_enabled']
    result = owner.stop_to_terminal(lease)
    assert not result['synthetic_tokens_settled'] and owner._current(attempt)['status'] == 'SETTLED'


@pytest.mark.parametrize('boundary', ['HANDOFF_UNKNOWN', 'RELEASE_INTENT'])
@pytest.mark.parametrize('late', ['utc', 'mono', 'STOP'])
def test_last_effect_proof_expiry_or_stop_never_enters_popen_or_g(runtime, monkeypatch, boundary, late):
    owner, _, _, _, _, _, utc, mono = runtime
    lease = register(runtime); attempt = owner._issued(lease); final = owner._final_effect_gate; reached = []
    def changed(guard):
        if json.loads(guard.raw)['request']['fixture_runtime']['phase'] == boundary:
            reached.append(True)
            if late == 'utc': utc[0] += timedelta(seconds=30)
            elif late == 'mono': mono[0] += 30 * 10**9
            else: (owner.store.root / 'STOP').touch()
        return final(guard)
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_final_effect_gate', changed)
        with pytest.raises(Conflict): owner.start(lease)
    assert reached and not attempt['release_entered']
    if boundary == 'HANDOFF_UNKNOWN':
        assert not attempt['spawn_entered']
        owner.shutdown_safety()
        assert owner.pool.snapshot()['occupied'] == 1
    else:
        assert attempt['spawn_entered']
        owner.stop_to_terminal(lease)
        assert owner.pool.snapshot()['occupied'] == 0


@pytest.mark.parametrize('witness', ['bootstrap', 'plan'])
def test_original_borrowed_deadline_at_final_spawn_boundary(runtime, monkeypatch, witness):
    owner = runtime[0]; lease = register(runtime); final = owner._final_effect_gate; reached = []
    def expired(guard):
        reached.append(True)
        original = guard.bootstrap.inventory if witness == 'bootstrap' else guard.plan_witness
        with monkeypatch.context() as clock_patch:
            clock_patch.setattr(time, 'monotonic', lambda: original.deadline + .000001)
            return final(guard)
    with monkeypatch.context() as patch:
        patch.setattr(owner, '_final_effect_gate', expired)
        with pytest.raises(Conflict): owner.start(lease)
    assert reached and not owner._issued(lease)['spawn_entered']
    owner.shutdown_safety()


def test_original_terminal_snapshot_replay_recover_and_pool_cold_join(runtime):
    owner = runtime[0]; lease = register(runtime); owner.stop_to_terminal(lease)
    state = owner.store.audit()
    assert owner.store.replay() == state
    assert owner.store.snapshot()['version'] == state['version']
    assert owner.store.recover() == state
    assert owner.pool.audit()['verified']
    pool = owner.pool; root, checksum, inode = pool.application_root, pool.descriptor_sha256, pool.descriptor_identity
    owner.shutdown(); pool.shutdown()
    joined = HostPoolOwner.trusted_attach(root, checksum, inode)
    try:
        assert joined.snapshot()['occupied'] == 0 and joined.audit()['verified']
        with pytest.raises(PermissionError): joined.check(runtime[4])
    finally: joined.shutdown()


def test_pool_free_tampered_project_source_is_rejected_by_current_and_cold_audit(runtime):
    owner = runtime[0]; lease = register(runtime); owner.stop_to_terminal(lease)
    pool = owner.pool
    value = next(v for v in pool._attempts.values() if type(v) is dict and v['action'] == 'FIXTURE_FREE')
    raw = canonical(value).decode(); changed = json.loads(raw)
    changed['payload']['project_fact_hash'] = 'sha256:' + '0'*64
    bad = canonical(changed).decode()
    # Fault injection ONLY in this new isolated fixture. Restore exact original
    # trigger/fact afterwards; neither historical delivery nor production moves.
    path = pool.root / 'pool.db'
    def replace_raw(text):
        with closing(sqlite3.connect(path)) as db, db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='immutable_update'").fetchone()[0]
            db.execute('DROP TRIGGER immutable_update')
            db.execute('UPDATE ledger SET raw=?,hash=? WHERE key=?',
                       (text,hashlib.sha256(text.encode()).hexdigest(),value['key']))
            db.execute(trigger)
    try:
        replace_raw(bad)
        with pytest.raises(Conflict, match='Project phase source'): pool.snapshot()
        with pytest.raises(Conflict, match='Project phase source'): pool.audit()
    finally: replace_raw(raw)
    assert pool.audit()['verified']


def test_partial_original_pool_close_retry_never_frees_early(runtime, monkeypatch):
    owner = runtime[0]; lease = register(runtime); claim = runtime[4]
    slot = owner.pool._claim_slots[id(claim)]; target = slot.fds[0]; close = os.close; injected = []
    def partial(fd):
        if fd == target and not injected:
            injected.append(True); raise OSError('original fixture partial close')
        return close(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'close', partial)
        with pytest.raises(Conflict): owner.stop_to_terminal(lease)
    assert injected and owner.pool.snapshot()['occupied'] == 1
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0 and all(fd is None for fd in slot.fds)


def test_partial_original_source_close_retains_exposure_until_retry(runtime, monkeypatch):
    owner = runtime[0]; lease = register(runtime); attempt = owner._issued(lease)
    source = owner.sources._issued(attempt['source']); target = source['fds']['read']; close = os.close; injected = []
    def partial(fd):
        if fd == target and not injected:
            injected.append(True); raise OSError('original source partial close')
        return close(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'close', partial)
        with pytest.raises(Conflict): owner.stop_to_terminal(lease)
    assert injected and owner.pool.snapshot()['occupied'] == 1
    assert owner._current(attempt)['fixture_runtime']['phase'] == 'STOP_REQUESTED'
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0 and all(fd is None for fd in source['fds'].values())


def test_actual_fork_denies_inherited_runtime_cap_and_closes_child_source_fds(runtime):
    owner = runtime[0]; lease = register(runtime); attempt = owner._issued(lease)
    source = owner.sources._issued(attempt['source'])
    before = dict(source['fds']); read_fd, write_fd = os.pipe(); reaped = False
    child = os.fork()
    if child == 0:
        try:
            os.close(read_fd)
            try: owner.start(lease)
            except PermissionError: denied = True
            else: denied = False
            closed = True
            for fd in before.values():
                if fd is None: continue
                try: os.fstat(fd)
                except OSError as error: closed = closed and error.errno == errno.EBADF
                else: closed = False
            os.write(write_fd, b'OK' if denied and closed else b'BAD')
        finally: os._exit(0)
    try:
        os.close(write_fd)
        assert select.select([read_fd], [], [], 5)[0]
        assert os.read(read_fd, 8) == b'OK'
        _, status = os.waitpid(child, 0); reaped = True
        assert status == 0 and source['fds'] == before
        owner.stop_to_terminal(lease)
        assert owner.pool.snapshot()['occupied'] == 0
    finally:
        os.close(read_fd)
        if not reaped:
            try: os.kill(child, signal.SIGKILL)
            except ProcessLookupError: pass
            os.waitpid(child, 0)


def test_real_stop_prevents_further_original_usage_file_growth(runtime):
    owner = runtime[0]; lease = register(runtime, 'running'); attempt = owner._issued(lease)
    owner.start(lease); observed(owner, lease)
    source = owner.sources._issued(attempt['source']); path = source['path'] / 'events.jsonl'
    owner.stop_to_terminal(lease)
    size = path.stat().st_size; time.sleep(.06)
    assert path.stat().st_size == size
    assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
