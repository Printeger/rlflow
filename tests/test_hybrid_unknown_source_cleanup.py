"""Unknown startup closes only original parent FDs, never adopts a process."""
import os
import subprocess

import pytest

from rlflow import hybrid_usage_source as source_module
from rlflow.store import Conflict
from tests.test_hybrid_usage_source import source_owner


def test_unknown_start_parent_FD_close_partial_retry_and_no_other_source_change(source_owner, monkeypatch):
    owner, member, claim = source_owner
    first = owner.start_fixture(member, claim, 'partial')
    original = owner._issued(first); first_fds = dict(original['fds'])
    second = owner.pool.claim(member, expected_version=owner.pool.snapshot()['version'], request_key='unknown_start')
    with monkeypatch.context() as patch:
        def unknown(*args, **kwargs): raise OSError('actual Popen entry has no returned child identity')
        patch.setattr(subprocess, 'Popen', unknown)
        with pytest.raises(OSError): owner.start_fixture(member, second)
    attempt = owner._attempts[id(second)]; source = attempt['source']
    retained = attempt['fds']['read']; close = os.close
    with monkeypatch.context() as patch:
        def fail_close(fd):
            if fd == retained: raise OSError('one original parent FD close failure')
            return close(fd)
        patch.setattr(os, 'close', fail_close)
        with pytest.raises(Conflict, match='partial cleanup'): owner.stop_fixture(source)
    assert attempt['fds']['read'] == retained and os.fstat(retained)
    assert all(fd is None for name, fd in attempt['fds'].items() if name != 'read')
    assert original['fds'] == first_fds and original['producer'].poll() is None
    assert owner._live and attempt['status'] == 'UNKNOWN'
    owner.stop_fixture(first)
    # Safety cannot retire an owner while its exact original close is failing.
    with monkeypatch.context() as patch:
        patch.setattr(os, 'close', fail_close)
        with pytest.raises(Conflict, match='partial cleanup'): owner.shutdown_safety()
    assert owner._live and attempt['fds']['read'] == retained
    with pytest.raises(Conflict, match='startup outcome unknown'): owner.stop_fixture(source)
    assert all(fd is None for fd in attempt['fds'].values()) and attempt['status'] == 'UNKNOWN'
    with pytest.raises(Conflict, match='startup outcome unknown'): owner.shutdown()
    assert owner._live and owner.pool.snapshot()['occupied'] == 2
    result = owner.shutdown_safety()
    assert result['state'] == 'PARENT_FDS_CLOSED_EXPOSURE_UNKNOWN'
    assert not result['runtime_stopped'] and not result['settlement_enabled'] and not owner._live
    assert owner.pool.snapshot()['occupied'] == 2


def test_Popen_object_with_missing_identity_is_not_retired_as_no_process(source_owner, monkeypatch):
    owner, member, claim = source_owner
    identity = source_module.identity
    with monkeypatch.context() as patch:
        patch.setattr(source_module, 'identity', lambda pid: identity(pid) if pid == os.getpid() else None)
        with pytest.raises(Conflict, match='producer identity unavailable'): owner.start_fixture(member, claim)
    attempt = owner._attempts[id(claim)]; process = attempt['producer']
    assert process is not None and process.poll() is None and attempt['producer_identity'] is None
    with pytest.raises(Conflict, match='identity uncertain'): owner.shutdown_safety()
    assert owner._live and process.poll() is None and any(fd is not None for fd in attempt['fds'].values())
    # Original fixed child's own finite watchdog terminates it; no adoption,
    # caller PID or fabricated pidfd is used to clean this negative fixture.
    process.wait(timeout=4)
    owner.stop_fixture(attempt['source'])
    assert owner.shutdown_safety()['state'] == 'ORIGINAL_PARENT_FDS_CLOSED'
    assert owner.pool.snapshot()['occupied'] == 1
