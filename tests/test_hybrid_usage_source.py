"""Actual finite CPU producers/owned source FDs; synthetic usage, no models."""
import copy
import json
import os
from pathlib import Path
import select
import signal
import time

import pytest

from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.hybrid_usage_source import FixtureUsageSourceOwner, FixtureUsageSource
from rlflow.hybrid_usage_stream import Accumulator, parse_line
from rlflow import hybrid_usage_source as source_module
from rlflow import hybrid_usage_stream as stream_module
from rlflow.store import Conflict, canonical


@pytest.fixture
def source_owner(tmp_path):
    tmp_path.chmod(0o700); pool = HostPoolOwner.create_fixture(tmp_path)
    project = pool.projects_root / 'project'; project.mkdir(mode=0o700)
    builder = FixtureMaterialBuilder(project, project_id='usage_project')
    installation = FixtureInstallationService(builder); material = builder.prepare()
    installation.persist_intent(material); installation.publish(material)
    member = pool.register_project(installation, material, expected_version=0)
    claim = pool.claim(member, expected_version=1, request_key='usage_origin')
    owner = FixtureUsageSourceOwner(pool)
    try: yield owner, member, claim
    finally:
        if owner._live: owner.shutdown()
        if pool._live: pool.shutdown()


def until(owner, source, predicate, *, sealing=False):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        receipt = owner.seal(source) if sealing else owner.poll(source)
        value = json.loads(receipt.raw)
        if predicate(value): return receipt, value
        time.sleep(.005)
    raise AssertionError('finite original fixture source observation timed out')


@pytest.mark.parametrize('scenario, expected', [('cumulative', 300), ('per_turn', 200), ('parent_inclusive', 300)])
def test_actual_producer_incremental_semantics_and_original_sealed_receipt(source_owner, scenario, expected):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, scenario)
    assert owner.start_fixture(member, claim, scenario) is source
    receipt, value = until(owner, source, lambda v: v['source_status'] == 'SEALED', sealing=True)
    assert value['usage']['input_tokens'] == expected and value['usage']['complete'] is True
    assert value['source_only'] and value['data_mode'] == 'fixture'
    assert value['actual_cost_status'] == 'UNKNOWN' and value['actual_cost'] is None
    assert value['execution_enabled'] is False and value['settlement_enabled'] is False
    assert owner.poll(source) is receipt
    with pytest.raises(Conflict): owner.start_fixture(member, claim, 'missing')
    owner.stop_fixture(source)
    assert owner.poll(source) is receipt  # Retain immutable historical as-of proof.


def test_actual_partial_tail_does_not_advance_then_original_producer_finishes(source_owner):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'partial')
    attempt = owner._issued(source)
    receipt, value = until(owner, source, lambda v: bool(attempt['tail']))
    offset = value['offset']; assert value['usage']['input_tokens'] == 100 and not value['usage']['complete']
    assert owner.poll(source) is receipt and owner._issued(source)['offset'] == offset
    owner.finish_partial_fixture(source)
    owner.finish_partial_fixture(source)  # No duplicate pipe release.
    _, final = until(owner, source, lambda v: v['source_status'] == 'SEALED', sealing=True)
    assert final['usage']['input_tokens'] == 200 and final['usage']['complete']


@pytest.mark.parametrize('scenario', ['missing', 'failed'])
def test_missing_or_failed_usage_is_unknown_not_zero_or_invoice(source_owner, scenario):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, scenario)
    _, value = until(owner, source, lambda v: v['source_status'] in ('SEALED', 'UNKNOWN'), sealing=True)
    assert not value['usage']['complete'] and value['actual_cost_status'] == 'UNKNOWN'
    if scenario == 'missing': assert value['usage']['output_tokens'] is None
    assert value['usage']['input_tokens'] == 100  # Real observed synthetic lower bound, not a refund.


def test_original_source_only_capabilities_copy_path_json_never_adopt(source_owner):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim)
    for bad in (copy.copy(source), FixtureUsageSource(source.id, source.raw), json.loads(source.raw), Path('/tmp')):
        with pytest.raises(PermissionError): owner.poll(bad)
        with pytest.raises(PermissionError): owner.seal(bad)
        with pytest.raises(PermissionError): owner.stop_fixture(bad)
    with pytest.raises(PermissionError): owner.start_fixture(copy.copy(member), claim)
    with pytest.raises(PermissionError): owner.start_fixture(member, copy.copy(claim))


@pytest.mark.parametrize('damage', ['replace', 'truncate', 'same_size'])
def test_actual_source_replacement_truncation_and_same_size_rewrite_quarantine(source_owner, damage):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim)
    until(owner, source, lambda v: v['source_status'] == 'AUDITING')
    attempt = owner._issued(source); path = attempt['path'] / 'events.jsonl'
    if damage == 'replace':
        path.rename(attempt['path'] / 'old.jsonl'); path.touch(mode=0o600)
    else:
        fd = os.open(path, os.O_WRONLY)
        try:
            if damage == 'truncate': os.ftruncate(fd, 0)
            else: os.pwrite(fd, b'X', 0)
        finally: os.close(fd)
    with pytest.raises(Conflict): owner.poll(source)
    value = json.loads(owner.poll(source).raw)
    assert value['source_status'] == 'QUARANTINED' and not value['usage']['complete']


def test_old_prefix_rewrite_plus_append_cannot_be_sealed_and_reads_are_bounded(source_owner, monkeypatch):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'history')
    attempt = owner._issued(source); fd = attempt['fds']['read']; original = os.pread; calls = []
    def pread(number, amount, offset):
        raw = original(number, amount, offset)
        if number == fd: calls.append(len(raw))
        return raw
    with monkeypatch.context() as patch:
        patch.setattr(os, 'pread', pread)
        deadline = time.monotonic() + 5
        while attempt['status'] != 'AUDITING':
            assert time.monotonic() < deadline
            calls.clear(); owner.poll(source); assert sum(calls) <= source_module.POLL_BYTES
            time.sleep(.005)
        assert attempt['offset'] > 3 * source_module.POLL_BYTES
        write = os.open(attempt['path'] / 'events.jsonl', os.O_WRONLY)
        try:
            os.pwrite(write, b'X', 100)  # Outside retained tip; no trusted current prefix claim.
            os.lseek(write, 0, os.SEEK_END); os.write(write, b'\n')
        finally: os.close(write)
        with pytest.raises(Conflict, match='earlier usage prefix'):
            for _ in range(8):
                calls.clear(); owner.seal(source); assert sum(calls) <= source_module.POLL_BYTES
        assert attempt['status'] == 'QUARANTINED'


def test_real_overlong_producer_line_is_quarantined_not_skipped(source_owner):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'overlong')
    with pytest.raises(Conflict): until(owner, source, lambda _: False)
    assert owner._issued(source)['status'] == 'QUARANTINED'


def test_actual_fixture_stop_reaps_original_producer_but_never_refunds_pool(source_owner):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'linger')
    until(owner, source, lambda v: v['usage']['input_tokens'] == 100)
    attempt = owner._issued(source); producer = attempt['producer']
    assert producer.poll() is None
    result = owner.stop_fixture(source)
    assert result == {'closed': True, 'runtime_stopped': False, 'settlement_enabled': False}
    assert producer.returncode == -signal.SIGKILL and all(fd is None for fd in attempt['fds'].values())
    assert owner.pool.snapshot()['occupied'] == 1


def test_original_exit_during_identity_check_reaps_without_signaling_foreign(source_owner,monkeypatch):
    owner,member,claim=source_owner;source=owner.start_fixture(member,claim,'linger')
    until(owner,source,lambda value:value['usage']['input_tokens']==100)
    attempt=owner._issued(source);producer=attempt['producer'];checks=[];original_identity=source_module.identity
    with monkeypatch.context() as patch:
        patch.setattr(source_module,'identity',lambda pid:None if pid==producer.pid else original_identity(pid))
        patch.setattr(source_module.signal,'pidfd_send_signal',lambda *args:pytest.fail('must not signal mismatched identity'))
        with pytest.raises(Conflict,match='identity uncertain'):owner._signal_original(attempt,signal.SIGKILL)
        assert producer.poll() is None
        def exited(pid):
            if pid!=producer.pid:return original_identity(pid)
            assert pid==producer.pid;checks.append(pid)
            producer.kill();assert producer.wait(timeout=2)==-signal.SIGKILL
            return None
        patch.setattr(source_module,'identity',exited)
        assert owner.stop_fixture(source)['closed']
    assert checks==[producer.pid] and producer.returncode==-signal.SIGKILL
    assert all(fd is None for fd in attempt['fds'].values())
    assert owner.pool.snapshot()['occupied']==1  # Source is not a terminal/refund authority.


def test_actual_fork_child_closes_source_and_pipe_but_preserves_parent_source(source_owner, monkeypatch):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'partial')
    until(owner, source, lambda _: bool(owner._issued(source)['tail']))
    attempt = owner._issued(source); fds = list(attempt['fds'].values()) + [attempt['producer'].stdin.fileno()]
    prepare, parent, child = source_module.pool_module._fork_extensions['fixture_usage']
    order = []
    def ordered_prepare():
        assert owner.pool._lock._is_owned()  # Pool precedes ALL Source locks.
        assert source_module.pool_module._registry_lock._is_owned()
        order.append('pool_before_source'); prepare()
    monkeypatch.setitem(source_module.pool_module._fork_extensions, 'fixture_usage', (ordered_prepare, parent, child))
    read, write = os.pipe2(os.O_CLOEXEC); pid = os.fork()
    if pid == 0:
        try:
            closed = []
            for fd in fds:
                try: os.fstat(fd)
                except OSError: closed.append(fd)
            try: owner.poll(source)
            except PermissionError: denied = True
            else: denied = False
            os.write(write, canonical([closed == fds, denied]))
        finally: os._exit(0)
    os.close(write)
    reaped = False
    try:
        assert order == ['pool_before_source']
        assert select.select([read], [], [], 4)[0]
        assert json.loads(os.read(read, 1024)) == [True, True]
        _, status = os.waitpid(pid, 0); reaped = True
        assert status == 0
        owner.finish_partial_fixture(source)
        _, result = until(owner, source, lambda v: v['source_status'] == 'SEALED', sealing=True)
        assert result['usage']['complete']
    finally:
        os.close(read)
        if not reaped:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
            os.waitpid(pid, 0)


def test_real_invalid_unicode_id_rolls_back_entire_poll_and_quarantines(source_owner):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim, 'invalid_id')
    attempt = owner._issued(source)
    attempt['producer'].wait(timeout=4)
    with pytest.raises(Conflict): owner.poll(source)
    assert attempt['status'] == 'QUARANTINED' and attempt['offset'] == 0
    assert not attempt['accumulator'].rows and not attempt['accumulator'].active
    assert not attempt['accumulator'].sources
    assert json.loads(owner.poll(source).raw)['usage']['input_tokens'] is None


def test_actual_popen_identity_failure_keeps_one_attempt_no_relaunch(source_owner, monkeypatch):
    owner, member, claim = source_owner
    original = source_module.identity; calls = []
    def failed_capture(pid):
        if pid != os.getpid(): calls.append(pid); return None
        return original(pid)
    with monkeypatch.context() as patch:
        patch.setattr(source_module, 'identity', failed_capture)
        with pytest.raises(Conflict, match='producer identity unavailable'):
            owner.start_fixture(member, claim)
    attempt = owner._attempts[id(claim)]; process = attempt['producer']
    assert process is not None and calls == [process.pid]
    assert owner.start_fixture(member, claim) is attempt['source']
    assert len(owner._attempts) == 1 and owner.pool.snapshot()['occupied'] == 1
    assert json.loads(owner.poll(attempt['source']).raw)['source_status'] == 'UNKNOWN'
    process.wait(timeout=4)  # Unreleased fixed producer's own finite watchdog.
    assert owner.stop_fixture(attempt['source'])['closed']


def test_partial_descriptor_cleanup_retains_and_retries_original_remaining_fd(source_owner, monkeypatch):
    owner, member, claim = source_owner; source = owner.start_fixture(member, claim)
    until(owner, source, lambda v: v['source_status'] == 'SEALED', sealing=True)
    attempt = owner._issued(source); retained = attempt['fds']['read']; original = os.close
    def fail_close(fd):
        if fd == retained: raise OSError('fixed one-shot close failure')
        return original(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'close', fail_close)
        with pytest.raises(Conflict, match='partial cleanup retained'): owner.stop_fixture(source)
    assert attempt['fds']['read'] == retained and os.fstat(retained)
    assert all(fd is None for name, fd in attempt['fds'].items() if name != 'read')
    assert owner.pool.snapshot()['occupied'] == 1
    assert owner.stop_fixture(source)['closed'] and attempt['fds']['read'] is None


def feed(accumulator, *events):
    source = 'source'; offset = accumulator.sources.get(source, {}).get('offset', -1) + 1
    for event in events:
        raw = canonical(event) + b'\n'; accumulator.accept(source, offset, raw); offset += len(raw)


def completed(input_=100, output=10, cached=20, event_id='turn'):
    return {'type': 'turn.completed', 'event_id': event_id,
            'usage': {'input_tokens': input_, 'output_tokens': output, 'cached_input_tokens': cached}}


@pytest.mark.parametrize('semantics', ['cumulative', 'per_turn'])
@pytest.mark.parametrize('inclusive', [False, True])
def test_unaccounted_thread_cannot_be_filtered_into_complete_usage(semantics, inclusive):
    accumulator=Accumulator(semantics)
    feed(accumulator, {'type':'thread.started','thread_id':'parent'}, {'type':'turn.started'}, completed())
    kwargs={'inclusive_parent':'parent'} if inclusive else {}
    assert accumulator.totals(**kwargs)['complete']
    def child(event):
        offset=accumulator.sources.get('child_source',{}).get('offset',-1)+1
        accumulator.accept('child_source',offset,canonical(event)+b'\n')
    child({'type':'thread.started','thread_id':'child'})
    unknown=accumulator.totals(**kwargs)
    assert unknown['input_tokens']==100 and not unknown['complete']
    assert unknown['actual_cost'] is None and not unknown['settlement_enabled']
    child({'type':'turn.started'})
    assert not accumulator.totals(**kwargs)['complete']
    child(completed(0,0,0,event_id='actual_zero'))
    # A literal actual zero is distinguishable from absent counters. It does
    # not add parent-inclusive counters or invent a second model receipt.
    known=accumulator.totals(**kwargs)
    assert known['complete'] and known['input_tokens']==100


@pytest.mark.parametrize('semantics', ['cumulative', 'per_turn'])
@pytest.mark.parametrize('inclusive', [False, True])
@pytest.mark.parametrize('missing', ['absent', 'empty', 'partial'])
def test_incomplete_participant_counters_never_hidden_by_inclusive_parent(semantics,inclusive,missing):
    accumulator=Accumulator(semantics)
    feed(accumulator,{'type':'thread.started','thread_id':'parent'},{'type':'turn.started'},completed())
    kwargs={'inclusive_parent':'parent'} if inclusive else {}
    def child(event):
        offset=accumulator.sources.get('child_source',{}).get('offset',-1)+1
        accumulator.accept('child_source',offset,canonical(event)+b'\n')
    child({'type':'thread.started','thread_id':'child'})
    child({'type':'turn.started'})
    event={'type':'turn.completed','event_id':'incomplete'}
    if missing!='absent':event['usage']={'input_tokens':7} if missing=='partial' else {}
    child(event)
    known=accumulator.totals(**kwargs)
    assert not known['complete']
    assert known['input_tokens']==(107 if missing=='partial' and not inclusive else 100)
    child({'type':'turn.started'})
    child(completed(7 if missing=='partial' else 0,0,0,event_id='next_complete'))
    # Qualified cumulative final counters can cover prior incomplete snapshots;
    # per-turn counters cannot retroactively settle an uncounted earlier turn.
    assert accumulator.totals(**kwargs)['complete'] is (semantics=='cumulative')


@pytest.mark.parametrize('counts', [(True, 10, 20), (-1, 10, 20), (100, 10, 101), (2**63, 10, 20)])
def test_invalid_or_overflowing_counter_math_denied(counts):
    accumulator = Accumulator('cumulative')
    feed(accumulator, {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'})
    with pytest.raises(Conflict): feed(accumulator, completed(*counts))


def test_stable_semantic_id_change_and_cumulative_regression_denied():
    accumulator = Accumulator('cumulative')
    feed(accumulator, {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'}, completed())
    with pytest.raises(Conflict, match='identity changed'): feed(accumulator, completed(200))
    feed(accumulator, {'type': 'turn.started'})
    with pytest.raises(Conflict, match='regressed'): feed(accumulator, completed(99, event_id='next'))


def test_old_stable_id_replay_cannot_complete_new_active_turn():
    accumulator = Accumulator('per_turn')
    feed(accumulator, {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'}, completed())
    feed(accumulator, {'type': 'turn.started'}, completed())
    assert accumulator.totals()['input_tokens'] == 100 and not accumulator.totals()['complete']
    feed(accumulator, completed(event_id='next'))
    assert accumulator.totals()['input_tokens'] == 200 and accumulator.totals()['complete']


@pytest.mark.parametrize('kind', ['thread', 'event'])
def test_escaped_surrogate_backend_identity_has_contextual_denial(kind):
    accumulator = Accumulator('per_turn')
    if kind == 'thread':
        raw = b'{"type":"thread.started","thread_id":"\\ud800"}\n'
    else:
        feed(accumulator, {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'})
        raw = b'{"type":"turn.completed","event_id":"\\ud800","usage":{"input_tokens":100,"output_tokens":10,"cached_input_tokens":20}}\n'
    offset = accumulator.sources.get('source', {}).get('offset', -1) + 1
    with pytest.raises(Conflict): accumulator.accept('source', offset, raw)


def test_model_or_tool_text_is_not_a_usage_event_and_missing_is_not_zero():
    accumulator = Accumulator('per_turn')
    feed(accumulator, {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(completed())}})
    value = accumulator.totals()
    assert value['input_tokens'] is None and value['output_tokens'] is None and not value['complete']


@pytest.mark.parametrize('raw', [b'{"type":"x","type":"x"}\n', b'{"type":"x","x":NaN}\n', b'{}',
                               b'{"type":"x","x":' + b'[' * 40 + b'0' + b']' * 40 + b'}\n'])
def test_bounded_literal_json_rejects_duplicates_nonfinite_partial_and_depth(raw):
    with pytest.raises(Conflict): parse_line(raw)


def test_capacity_denial_does_not_lose_dedup_or_walk_all_rows(monkeypatch):
    monkeypatch.setattr(stream_module, 'MAX_EVENTS', 1)
    accumulator = Accumulator('per_turn')
    feed(accumulator, {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'}, completed())
    feed(accumulator, completed())
    assert accumulator.totals()['input_tokens'] == 100
    feed(accumulator, {'type': 'turn.started'})
    with pytest.raises(Conflict, match='observation bound'): feed(accumulator, completed(event_id='second'))
