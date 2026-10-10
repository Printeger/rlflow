"""Actual small blank allocation/STOP rescue, never fills the real filesystem."""
import errno
import os
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_audit_reserve import RESERVE_BYTES
from rlflow.store import Conflict
from tests.test_hybrid_disk_admission import availability
from tests.test_hybrid_host_execution import shared, requests
from tests.test_hybrid_finite_host_app import application, ORIGIN, path, start, stop
from tests.test_execution_adapter import setup as native_setup


def test_actual_shared_allocation_healthy_engineering_STOP_keeps_apply(shared):
    host, units = shared; original = requests(units)[1]
    assert host._disk.health()['audit_reserves'] == []
    result = host.run(original[0], original[1], **original[2])
    assert result['status'] == 'MACHINE_ACCEPTED_PENDING_REVIEW'
    assert result['fact']['machine_verification']['derived']['passed_cases'] == 21
    assert len(host._disk._reserves) == 1
    reserve = next(iter(host._disk._reserves.values()))
    info = os.fstat(reserve.fd)
    assert info.st_size == RESERVE_BYTES and info.st_blocks * 512 >= RESERVE_BYTES
    assert info.st_mode & 0o777 == 0o600 and info.st_nlink == 1
    assert not os.get_inheritable(reserve.fd)
    assert reserve.path not in units[1].runtime.workspace.working._slot(units[1]._actual()['observation'])[0]['copy'].path.parents
    assert not host._disk._emergency_frozen and not reserve.released
    print('actual_audit_reserve', dict(real_bytes=info.st_size, block_bytes=info.st_blocks * 512,
          single_shared_FS=True, healthy_STOP_keeps_apply=True, AST_cases=21), flush=True)


def test_actual_partial_allocation_same_key_uses_original_FD(shared, monkeypatch):
    host, units = shared; original = requests(units)[0]
    allocate = os.posix_fallocate; calls = []
    def partial(fd, offset, length):
        calls.append(fd); allocate(fd, offset, length // 2)
        raise OSError(errno.ENOSPC, 'injected partial actual reserve allocation')
    versions = [unit.runtime.store.version() for unit in units]
    with monkeypatch.context() as patch:
        patch.setattr(os, 'posix_fallocate', partial)
        with pytest.raises(OSError, match='partial actual reserve'):
            host.run(original[0], original[1], **original[2])
        assert units[0]._request is None and not units[0]._actual()['spawn_entered']
        assert [unit.runtime.store.version() for unit in units] == versions
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    identity = reserve.identity
    assert calls == [fd] and os.fstat(fd).st_size == RESERVE_BYTES // 2
    result = host.run(original[0], original[1], **original[2])
    assert result['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    assert reserve.fd == fd and reserve.identity == identity and len(host._disk._reserves) == 1
    assert os.fstat(fd).st_size == RESERVE_BYTES
    print('actual_audit_partial', dict(partial_allocated=RESERVE_BYTES // 2, same_FD=True,
          same_key_healed=True, no_preHANDOFF_effect=True), flush=True)


def test_actual_HTTP_low_disk_release_before_first_STOP_acceptance(application, monkeypatch):
    host, units, services, observers, app, token, headers = application
    unit = units[0]; service = services[0]
    # Allocate through actual original finite admission before HANDOFF, without
    # a second test-created file or model. Stop then acts on this original FD.
    host._disk.check(unit, allocate=True)
    reserve = next(iter(host._disk._reserves.values()))
    acceptance = service._accept_stop; entered = []
    def accepted(*args, **kwargs):
        entered.append(True)
        assert reserve.released and os.fstat(reserve.fd).st_size == 0
        assert host._disk._emergency_frozen
        return acceptance(*args, **kwargs)
    monkeypatch.setattr(service, '_accept_stop', accepted)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        with monkeypatch.context() as patch:
            availability(patch, 0)
            response = client.post(path(service) + '/commands', headers=headers, json=stop(service))
            assert response.status_code == 202, response.text
            assert entered and host.pool.snapshot()['occupied'] == 1
            assert unit._actual()['terminal'] is not None
            assert host._disk.health()['emergency_frozen']
    assert host._disk._emergency_frozen and os.fstat(reserve.fd).st_size == 0
    print('actual_audit_HTTP_STOP', dict(real_release_before_first_write=True, STOP=202,
          occupied=1, emergency_newwork_frozen=True, no_deleted_evidence=True), flush=True)


def test_original_reserve_coverage_requires_all_bound_filesystems(shared):
    host, units = shared
    host._disk.check(units[0], allocate=True)
    # Controlled coverage interruption, not a claim of a second actual FS.
    original = host._disk._locations
    try:
        host._disk._locations = {**original, ('uncreated', 'coverage'): next(iter(original.values()))}
        health = host._disk.health()
        assert not health['audit_reserve_allocated'] and not health['new_run_admissible']
    finally:
        host._disk._locations = original
    assert host._disk.health()['audit_reserve_allocated']


def test_unknown_space_freezes_without_consuming_actual_reserve(shared, monkeypatch):
    from types import SimpleNamespace
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values()))
    actual = os.fstatvfs
    with monkeypatch.context() as patch:
        def unknown(fd):
            value = actual(fd)
            return SimpleNamespace(f_fsid=value.f_fsid, f_frsize=0, f_bavail=0, f_favail=100)
        patch.setattr(os, 'fstatvfs', unknown)
        with pytest.raises(Conflict, match='rescue availability unavailable'):
            host._disk.prepare_stop(units[0], {})
        assert os.fstat(reserve.fd).st_size == RESERVE_BYTES and not reserve.release_entered
    assert host._disk._emergency_frozen
    assert host.cancel(units[0].lease)['status'] == 'CANCELLED_SCOPE_STOPPED'


def test_partial_release_fsync_failure_retains_original_retryable_FD(shared, monkeypatch):
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    actual = os.fsync
    with host.pool._lock:
        with monkeypatch.context() as patch:
            def fail_sync(target):
                if target == fd:raise OSError(errno.EIO, 'injected original release fsync')
                return actual(target)
            patch.setattr(os, 'fsync', fail_sync)
            with pytest.raises(OSError, match='release fsync'):reserve.release()
        assert reserve.fd == fd and reserve.release_entered and not reserve.released
        assert os.fstat(fd).st_size == 0
        with pytest.raises(Conflict, match='cannot replenish'):reserve.allocate()
        reserve.release()
        assert reserve.released and reserve.fd == fd


def test_changed_blank_file_never_authorizes_truncation(shared, monkeypatch):
    from types import SimpleNamespace
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); actual = os.fstat
    # Observation faults preserve the actual original file for honest teardown;
    # no changing the owner's expected stamp to adopt a tampered file.
    for field, changed in (('st_size', RESERVE_BYTES + 1), ('st_mtime_ns', reserve.stamp[1] + 1)):
        with monkeypatch.context() as patch, host.pool._lock:
            def foreign(fd):
                info = actual(fd)
                if fd != reserve.fd:return info
                values = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
                values[field] = changed
                return SimpleNamespace(**values)
            patch.setattr(os, 'fstat', foreign)
            patch.setattr(os, 'ftruncate', lambda *args: pytest.fail('changed file truncated'))
            with pytest.raises(Conflict, match='blank reserve file changed'):reserve.release()
    assert os.fstat(reserve.fd).st_size == RESERVE_BYTES and not reserve.release_entered


def test_pool_shutdown_failure_retains_live_owner_and_original_reserve(shared, monkeypatch):
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    for unit in units:unit.runtime.shutdown()
    actual = os.ftruncate
    with monkeypatch.context() as patch:
        def fail_release(target, length):
            if target == fd:raise OSError(errno.EIO, 'injected shutdown blank release')
            return actual(target, length)
        patch.setattr(os, 'ftruncate', fail_release)
        with pytest.raises(OSError, match='shutdown blank release'):host.pool.shutdown()
        assert host.pool._live and reserve.fd == fd and os.fstat(fd).st_size == RESERVE_BYTES
    host.pool.shutdown()
    assert not host.pool._live and reserve.fd is None and reserve.parent is None


@pytest.mark.parametrize('critical_write_fails', [False, True])
def test_actual_preG_low_disk_STOP_and_failed_critical_facts(application, monkeypatch, critical_write_fails):
    host, units, services, observers, app, token, headers = application
    unit = units[0]; service = services[0]; runtime = unit.runtime
    attempt = unit._actual(); entered = threading.Event(); register = runtime._register_release
    def waiting(row):
        entered.set(); assert unit._cancelled.wait(2)
        return register(row)
    monkeypatch.setattr(runtime, '_register_release', waiting)
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session', token)
        future = worker.submit(client.post, path(service) + '/commands', headers=headers, json=start(service))
        assert entered.wait(8)
        source = runtime.sources._issued(attempt['source'])
        assert source['producer'].poll() is None
        reserve = next(iter(host._disk._reserves.values()))
        stop_headers = {**headers, 'Idempotency-Key': 'reserve_preG_stop'}
        with monkeypatch.context() as patch:
            availability(patch, 0)
            if critical_write_fails:
                def no_commit(*args, **kwargs):
                    assert reserve.released and os.fstat(reserve.fd).st_size == 0
                    raise OSError(errno.ENOSPC, 'injected critical facts still unavailable after release')
                patch.setattr(service.store, '_commit', no_commit)
            stopped = client.post(path(service) + '/commands', headers=stop_headers, json=stop(service))
            assert stopped.status_code == (503 if critical_write_fails else 202), stopped.text
            assert future.result(timeout=10).status_code == 202
            assert not attempt['release_entered'] and source['producer'].poll() is not None
            assert all(fd is None for fd in source['fds'].values())
            assert host.pool.snapshot()['occupied'] == (2 if critical_write_fails else 1)
            assert (attempt['terminal'] is None) == critical_write_fails
            assert reserve.released and host._disk._emergency_frozen
        if critical_write_fails:
            import subprocess
            with monkeypatch.context() as patch:
                patch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('STOP retry spawned'))
                recovered = client.post(path(service) + '/commands', headers=stop_headers, json=stop(service))
                assert recovered.status_code == 202, recovered.text
            assert host.pool.snapshot()['occupied'] == 1
        assert not units[1]._cancelled.is_set() and not units[1]._actual()['spawn_entered']
    print('actual_reserve_preG_STOP', dict(critical_write_failed=critical_write_fails,
          real_release=True, G=False, physical_reaped=True, UNKNOWN_not_FREE=critical_write_fails,
          original_STOP_retry_no_spawn=True), flush=True)


def test_same_HTTP_STOP_release_failure_not_reissued_by_fallback(application, monkeypatch):
    host, units, services, observers, app, token, headers = application
    unit = units[0]; service = services[0]
    host._disk.check(unit, allocate=True)
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    actual = os.ftruncate; calls = []
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        with monkeypatch.context() as patch:
            availability(patch, 0)
            def fail_release(target, length):
                if target == fd:
                    calls.append(target)
                    raise OSError(errno.EIO, 'injected original STOP release failure')
                return actual(target, length)
            patch.setattr(os, 'ftruncate', fail_release)
            stopped = client.post(path(service) + '/commands', headers=headers, json=stop(service))
            assert stopped.status_code == 503, stopped.text
            assert calls == [fd] and os.fstat(fd).st_size == RESERVE_BYTES
            assert unit._actual()['terminal'] is None and host.pool.snapshot()['occupied'] == 2
        with monkeypatch.context() as patch:
            availability(patch, 0)
            recovered = client.post(path(service) + '/commands', headers=headers, json=stop(service))
            assert recovered.status_code == 202, recovered.text
        assert reserve.fd == fd and reserve.released and host.pool.snapshot()['occupied'] == 1


def test_actual_fork_closes_inherited_reserve_without_releasing_parent(shared):
    import select
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); descriptors = (reserve.fd, reserve.parent)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            closed = []
            for fd in descriptors:
                try:os.fstat(fd)
                except OSError:closed.append(fd)
            os.write(write_fd, b'closed' if tuple(closed) == descriptors else b'open')
        finally:os._exit(0)
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 4)[0]
        assert os.read(read_fd, 32) == b'closed'
        assert os.waitpid(pid, 0)[1] == 0
        assert os.fstat(reserve.fd).st_size == RESERVE_BYTES and not reserve.released
    finally:os.close(read_fd)


def test_allocation_fsync_failure_heals_only_original_FD(shared, monkeypatch):
    host, units = shared; original = os.fsync
    with monkeypatch.context() as patch:
        def fail_sync(fd):
            if any(reserve.fd == fd for reserve in host._disk._reserves.values()):
                raise OSError(errno.EIO, 'injected allocation fsync failure')
            return original(fd)
        patch.setattr(os, 'fsync', fail_sync)
        with pytest.raises(OSError, match='allocation fsync'):
            host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    assert not reserve.allocated and os.fstat(fd).st_size == RESERVE_BYTES
    assert not host._disk.health()['audit_reserve_allocated']
    host._disk.check(units[0], allocate=True)
    assert reserve.fd == fd and reserve.allocated and len(host._disk._reserves) == 1
    assert all(unit._request is None and not unit._actual()['spawn_entered'] for unit in units)


@pytest.mark.parametrize('boundary', ['G', 'pwrite'])
def test_actual_emergency_freeze_AFTER_final_auth_blocks_effect_and_other_RUN(application, monkeypatch, boundary):
    import subprocess
    import sys
    host, units, services, observers, app, token, headers = application
    index = 0 if boundary == 'G' else 1
    unit = units[index]; service = services[index]; entered = []
    authority = service._check_final_authority
    target = '_final_effect_gate' if boundary == 'G' else '_last_effect'
    def freeze_after_auth(**kwargs):
        value = authority(**kwargs)
        actual_write_fence = (boundary != 'pwrite' or
            (sys._getframe(3).f_code.co_name == 'last_effect' and
             sys._getframe(4).f_code.co_name == '_apply_once'))
        if (not kwargs['cleanup'] and sys._getframe(1).f_code.co_name == '_unit_effect_check' and
                sys._getframe(2).f_code.co_name == target and
                actual_write_fence and
                (boundary != 'G' or unit._actual()['producer_identity'] is not None)):
            if boundary == 'pwrite':
                row = unit.output._rows[id(unit.lease)]
                assert row['intent'] is not None and not row['material'].write_entered
                assert row['material'].fd is not None
            entered.append(True)
            host._disk._emergency_frozen = True
        return value
    monkeypatch.setattr(service, '_check_final_authority', freeze_after_auth)
    monkeypatch.setattr(os, 'pwrite', lambda *args: pytest.fail('emergency allowed pwrite'))
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        accepted = client.post(path(service) + '/commands', headers=headers, json=start(service))
        assert accepted.status_code == 202, accepted.text
        assert entered and unit._last is None and host._disk._emergency_frozen
        attempt = unit._actual(); source = unit.runtime.sources._issued(attempt['source'])
        assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
        if boundary == 'G':assert not attempt['release_entered']
        else:assert attempt['release_entered'] and attempt['terminal'] is not None
        other = units[1-index]; original = requests(units)[1-index]
        versions = [u.runtime.store.version() for u in units]
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('frozen new RUN spawned'))
            with pytest.raises(Conflict, match='disk admission'):
                host.run(original[0], original[1], **original[2])
        assert other._request is None and not other._actual()['spawn_entered']
        assert [u.runtime.store.version() for u in units] == versions
    print('actual_emergency_final_fence', dict(boundary=boundary, after_actual_auth=True,
          protected_effect=False, other_RUN_effects=0, original_worker_reaped=True), flush=True)


def test_actual_preG_release_failure_still_reaps_and_retains_UNKNOWN(application, monkeypatch):
    host, units, services, observers, app, token, headers = application
    unit = units[0]; service = services[0]; runtime = unit.runtime
    entered = threading.Event(); register = runtime._register_release
    def waiting(row):
        entered.set(); assert unit._cancelled.wait(2)
        return register(row)
    monkeypatch.setattr(runtime, '_register_release', waiting)
    actual = os.ftruncate; attempts = []
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as worker:
        client.cookies.set('rlflow_session', token)
        future = worker.submit(client.post, path(service) + '/commands', headers=headers, json=start(service))
        assert entered.wait(8)
        attempt = unit._actual(); source = runtime.sources._issued(attempt['source'])
        reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
        assert source['producer'].poll() is None
        stop_headers = {**headers, 'Idempotency-Key': 'active_release_fault'}
        with monkeypatch.context() as patch:
            availability(patch, 0)
            def fail_release(target, length):
                if target == fd:
                    attempts.append(threading.get_ident())
                    raise OSError(errno.EIO, 'injected active original release failure')
                return actual(target, length)
            patch.setattr(os, 'ftruncate', fail_release)
            failed = client.post(path(service) + '/commands', headers=stop_headers, json=stop(service))
            assert failed.status_code == 503, failed.text
            assert future.result(timeout=10).status_code == 202
            # RUN and HTTP STOP are separate original scopes, each memoized;
            # their two cleanup entries must not be counted as one operation.
            assert attempts and len(attempts) == len(set(attempts))
            assert source['producer'].poll() is not None and all(v is None for v in source['fds'].values())
            assert not attempt['release_entered'] and attempt['terminal'] is None
            assert host.pool.snapshot()['occupied'] == 2 and os.fstat(fd).st_size == RESERVE_BYTES
        with monkeypatch.context() as patch:
            availability(patch, 0)
            recovered = client.post(path(service) + '/commands', headers=stop_headers, json=stop(service))
            assert recovered.status_code == 202, recovered.text
        assert reserve.fd == fd and reserve.released and host.pool.snapshot()['occupied'] == 1
    print('actual_active_release_fault', dict(reaped=True, G=False, UNKNOWN_not_FREE=True,
          one_attempt_per_original_scope=True, original_FD_retry=True), flush=True)


def test_actual_preopen_failure_other_STOP_then_same_object_key_heals(shared, monkeypatch):
    import sys
    host, units = shared; request = requests(units)[0]; duplicate = os.dup
    versions = [unit.runtime.store.version() for unit in units]
    with monkeypatch.context() as patch:
        def fail_duplicate(fd):
            if sys._getframe(1).f_globals['__name__'] == 'rlflow.hybrid_audit_reserve':
                raise OSError(errno.EIO, 'injected original pre-open dup failure')
            return duplicate(fd)
        patch.setattr(os, 'dup', fail_duplicate)
        with pytest.raises(OSError, match='pre-open dup'):
            host.run(request[0], request[1], **request[2])
    reserve = next(iter(host._disk._reserves.values()))
    assert reserve.fd is None and not reserve.creation_entered
    assert host._disk.health()['audit_reserves'] == [dict(allocated_bytes=0, logical_bytes=0,
        allocation_complete=False, released=False)]
    assert [unit.runtime.store.version() for unit in units] == versions
    assert units[0]._request is None and not units[0]._actual()['spawn_entered']
    with monkeypatch.context() as patch:
        availability(patch, 0)
        assert host.cancel(units[1].lease)['status'] == 'CANCELLED_SCOPE_STOPPED'
        assert not host._disk._emergency_frozen
    result = host.run(request[0], request[1], **request[2])
    assert result['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    assert next(iter(host._disk._reserves.values())) is reserve
    assert reserve.fd is not None and reserve.allocated and host.pool.snapshot()['occupied'] == 0
    print('actual_preopen_heal', dict(same_object=True, same_key=True,
          preHANDOFF_effects=0, other_STOP_not_permanent_freeze=True), flush=True)


def test_actual_retained_precreation_parent_FD_is_reused_without_duplicate(shared, monkeypatch):
    import sys
    host, units = shared; duplicate = os.dup; retained = []
    def interrupted_duplicate(fd):
        if sys._getframe(1).f_globals['__name__'] == 'rlflow.hybrid_audit_reserve':
            reserve = next(iter(host._disk._reserves.values()))
            # Model interruption after original parent assignment, before the
            # creation-entered marker. Keep the actual original descriptor.
            reserve.parent = duplicate(fd); retained.append(reserve.parent)
            raise OSError(errno.EIO, 'original assigned parent interruption')
        return duplicate(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'dup', interrupted_duplicate)
        with pytest.raises(OSError, match='assigned parent interruption'):
            host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values()))
    assert reserve.parent == retained[0] and reserve.fd is None and not reserve.creation_entered
    def forbid_reduplicate(fd):
        if sys._getframe(1).f_globals['__name__'] == 'rlflow.hybrid_audit_reserve':
            pytest.fail('original retained parent was overwritten by another dup')
        return duplicate(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'dup', forbid_reduplicate)
        host._disk.check(units[0], allocate=True)
    assert reserve.parent == retained[0] and reserve.allocated
    assert os.fstat(reserve.fd).st_size == RESERVE_BYTES
    assert not os.get_inheritable(reserve.parent)


def test_actual_partial_and_unknown_creation_STOP_never_replenish(shared, monkeypatch):
    host, units = shared; allocator = os.posix_fallocate
    with monkeypatch.context() as patch:
        def partial(fd, offset, length):
            allocator(fd, offset, length // 2)
            raise OSError(errno.ENOSPC, 'injected partial reserve for STOP')
        patch.setattr(os, 'posix_fallocate', partial)
        with pytest.raises(OSError, match='partial reserve for STOP'):
            host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); fd = reserve.fd
    assert os.fstat(fd).st_size == RESERVE_BYTES // 2
    assert host.cancel(units[0].lease)['status'] == 'CANCELLED_SCOPE_STOPPED'
    assert reserve.released and host._disk._emergency_frozen and os.fstat(fd).st_size == 0
    with host.pool._lock, pytest.raises(Conflict, match='cannot replenish'):reserve.allocate()


def test_actual_unknown_creation_without_FD_freezes_never_adopts(shared, monkeypatch):
    host, units = shared; opened = os.open
    with monkeypatch.context() as patch:
        def fail_open(name, *args, **kwargs):
            if str(name).startswith('.rlflow-audit-reserve-'):
                raise OSError(errno.ENOSPC, 'injected original creation outcome unavailable')
            return opened(name, *args, **kwargs)
        patch.setattr(os, 'open', fail_open)
        with pytest.raises(OSError, match='creation outcome unavailable'):
            host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values()))
    assert reserve.fd is None and reserve.creation_entered and reserve.parent is not None
    with pytest.raises(Conflict, match='file descriptor unavailable'):host._disk.health()
    with monkeypatch.context() as patch:
        patch.setattr(os, 'ftruncate', lambda *args: pytest.fail('unknown file truncated'))
        with pytest.raises(Conflict, match='file descriptor unavailable'):
            host._disk.prepare_stop(units[0], {})
    assert host._disk._emergency_frozen and host.pool.snapshot()['occupied'] == 2
    # Retire only original parent/runtime FDs, never forge terminal or FREE.
    for unit in units:unit.runtime.shutdown_safety()
