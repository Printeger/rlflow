"""Actual finite RUN denial/STOP without filling or changing the real disk."""
import copy
import os
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_disk_admission import FLOOR_BYTES, WORK_BYTES
from rlflow.store import Conflict
from tests.test_hybrid_host_execution import shared, requests
from tests.test_hybrid_finite_host_app import application, ORIGIN, path, start, stop
from tests.test_execution_adapter import setup as native_setup


def availability(monkeypatch, byte_count, inode_count=100):
    actual = os.fstatvfs
    def observed(fd):
        value = actual(fd)
        return SimpleNamespace(f_fsid=value.f_fsid, f_frsize=value.f_frsize,
            f_bavail=byte_count // value.f_frsize, f_favail=inode_count)
    monkeypatch.setattr(os, 'fstatvfs', observed)


def no_effects(monkeypatch):
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('denied RUN spawned'))
    monkeypatch.setattr(os, 'pwrite', lambda *a, **k: pytest.fail('denied RUN wrote core'))


def test_actual_shared_credit_low_disk_zero_effect_same_key_heals(shared, monkeypatch):
    host, units = shared
    original = requests(units)[0]
    versions = [unit.runtime.store.version() for unit in units]
    with monkeypatch.context() as patch:
        availability(patch, FLOOR_BYTES + WORK_BYTES)
        no_effects(patch)
        health = host._disk.health()
        assert len(health['filesystems']) == 1
        bucket = health['filesystems'][0]
        assert bucket['promised_claims'] == 2 and bucket['required_bytes'] == FLOOR_BYTES + 2 * WORK_BYTES
        assert not health['new_run_admissible'] and not health['stop_gated']
        with pytest.raises(Conflict, match='disk admission'):
            host.run(original[0], original[1], **original[2])
        assert units[0]._request is None
        assert [unit.runtime.store.version() for unit in units] == versions
        assert not any(unit._actual()['spawn_entered'] for unit in units)
        assert host.pool.snapshot()['occupied'] == 2
    result = host.run(original[0], original[1], **original[2])
    assert result['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    assert host._disk.health()['filesystems'][0]['promised_claims'] == 1
    assert not units[1]._actual()['spawn_entered']
    print('actual_disk_SDK', dict(shared_claims=2, denied_effects=0, same_key_healed=True,
          CPU_status=result['status'], other_scope_untouched=True), flush=True)


def test_actual_HTTP_inode_denial_same_body_key_then_STOP_not_gated(application, monkeypatch):
    host, units, services, observers, app, token, headers = application
    service = services[0]; body = start(service)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        with monkeypatch.context() as patch:
            availability(patch, 1024**3, 0); no_effects(patch)
            versions = [s.store.version() for s in services]
            diagnostic = client.get('/api/v1/finite-host/disk-admission')
            assert diagnostic.status_code == 200, diagnostic.text
            assert not diagnostic.json()['new_run_admissible']
            assert diagnostic.json()['audit_reserve_allocated'] is False
            assert [s.store.version() for s in services] == versions
            rejected = client.post(path(service) + '/commands', headers=headers, json=body)
            assert rejected.status_code == 503, rejected.text
            assert units[0]._request is None and not units[0]._actual()['spawn_entered']
            assert [s.store.version() for s in services] == versions
            stopped = client.post(path(services[1]) + '/commands',
                headers={**headers, 'Idempotency-Key': 'disk_stop'}, json=stop(services[1]))
            assert stopped.status_code == 202, stopped.text
            assert host.pool.snapshot()['occupied'] == 1
        healed = client.post(path(service) + '/commands', headers=headers, json=body)
        assert healed.status_code == 202, healed.text
        assert units[0]._last['status'] == 'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
        assert host.pool.snapshot()['occupied'] == 0
    print('actual_disk_HTTP', dict(inode_denial=503, STOP=202, same_body_key_healed=202,
          occupied=0, no_reserve_claim=True), flush=True)


def test_original_unbound_occupied_claim_blocks_run_not_STOP(shared, monkeypatch):
    host, units = shared
    unit = units[0]
    claim = host.pool.claim(unit.runtime.membership, expected_version=host.pool.snapshot()['version'],
                           request_key='disk_unbound', seconds=60)
    with monkeypatch.context() as patch:
        no_effects(patch)
        assert host._disk.health()['unbound_occupied_claim']
        original = requests(units)[0]
        with pytest.raises(Conflict, match='disk admission'):
            host.run(original[0], original[1], **original[2])
        assert unit._request is None and not unit._actual()['spawn_entered']
        assert host.cancel(unit.lease)['status'] == 'CANCELLED_SCOPE_STOPPED'
        assert host.pool.snapshot()['occupied'] == 2
        assert host.pool.check(claim)['state'] == 'CLAIM'
        assert host._disk.health()['unbound_occupied_claim']
    with pytest.raises(PermissionError):copy.copy(host._disk).health()
    print('actual_disk_unbound', dict(new_run=False, original_STOP=True, unbound_not_refunded=True), flush=True)


def test_actual_engineering_final_pwrite_rechecks_space_after_FREE(shared, monkeypatch):
    host, units = shared; unit = units[1]
    original = requests(units)[1]
    method = unit.output._last_effect
    entered = []
    def low_at_last(guard):
        entered.append(True)
        assert host.pool.snapshot()['occupied'] == 1  # other CPU claim only
        assert host._disk.health()['filesystems'][0]['promised_claims'] == 2
        with monkeypatch.context() as patch:
            availability(patch, 0)
            patch.setattr(os, 'pwrite', lambda *a, **k: pytest.fail('low disk core write'))
            return method(guard)
    monkeypatch.setattr(unit.output, '_last_effect', low_at_last)
    with pytest.raises(Conflict, match='disk admission'):
        host.run(original[0], original[1], **original[2])
    assert entered and unit._last is None
    assert unit._actual()['producer_identity'] is not None
    assert unit._actual()['terminal'] is not None
    assert host._disk.health()['filesystems'][0]['promised_claims'] == 2
    print('actual_disk_core_fence', dict(after_FREE=True, pwrite=0, credit_retained=True,
          no_automatic_redispatch=True), flush=True)


def test_actual_CANCEL_latch_without_completed_cleanup_keeps_credit(shared):
    host, units = shared; unit = units[0]
    unit.runtime.stop_to_terminal(unit.lease)
    unit._cancelled.set()
    assert unit.cleanup_error is None
    assert host.pool.snapshot()['occupied'] == 1
    assert host._disk.health()['filesystems'][0]['promised_claims'] == 2
    assert unit.cancel()['status'] == 'CANCELLED_SCOPE_STOPPED'
    assert host._disk.health()['filesystems'][0]['promised_claims'] == 1
    print('actual_disk_cancel_proof', dict(latch_not_refund=True, original_cleanup_refunds=True), flush=True)


def test_actual_disk_health_reauth_after_blocking_read_and_source_error_503(application, monkeypatch):
    host, units, services, observers, app, token, headers = application
    auth = services[0].auth; health = host._disk.health
    def revoking():
        value = health(); auth.revoke(token); return value
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        versions = [s.store.version() for s in services]
        monkeypatch.setattr(host._disk, 'health', revoking)
        denied = client.get('/api/v1/finite-host/disk-admission')
        assert denied.status_code == 401, denied.text
        assert 'available_bytes' not in denied.text
        from tests.test_hybrid_finite_host_app import PHRASE
        replacement, _ = auth.login('fixture_human', PHRASE)
        client.cookies.set('rlflow_session', replacement)
        def unavailable():raise Conflict('original FS source unavailable')
        monkeypatch.setattr(host._disk, 'health', unavailable)
        failed = client.get('/api/v1/finite-host/disk-admission')
        assert failed.status_code == 503, failed.text
        assert client.get('/api/v1/finite-host/disk-admission?x=1').status_code == 400
        assert [s.store.version() for s in services] == versions
    print('actual_disk_health', dict(revoked_after_read=401, source_error=503, closed_query=400,
          facts_unchanged=True), flush=True)


@pytest.mark.parametrize('boundary', ('spawn', 'G'))
def test_actual_disk_drop_at_final_worker_fence_never_restarts(shared, monkeypatch, boundary):
    host, units = shared; unit = units[0]; runtime = unit.runtime
    name = '_check_spawn_gate' if boundary == 'spawn' else '_check_release_gate'
    method = getattr(runtime, name); entered = []
    def low(attempt):
        entered.append(True)
        with monkeypatch.context() as patch:
            availability(patch, 0)
            return method(attempt)
    monkeypatch.setattr(runtime, name, low)
    original = requests(units)[0]
    with pytest.raises(Conflict, match='disk admission'):
        host.run(original[0], original[1], **original[2])
    attempt = unit._actual()
    assert entered and 'HANDOFF_UNKNOWN' in attempt['entries']
    assert not attempt['release_entered']
    assert host.pool.snapshot()['occupied'] == (2 if boundary == 'spawn' else 1)
    if boundary == 'G':
        source = runtime.sources._issued(attempt['source'])
        assert source['producer'].poll() is not None
        assert all(fd is None for fd in source['fds'].values())
    with monkeypatch.context() as patch:
        no_effects(patch)
        result = host.run(original[0], original[1], **original[2])
        assert result['status'] == 'UNKNOWN_RESULT_UNAVAILABLE'
    assert not units[1]._actual()['spawn_entered']
    print('actual_disk_final_worker_fence', dict(boundary=boundary, G=False,
          no_second_spawn=True, occupied=host.pool.snapshot()['occupied']), flush=True)
    if boundary == 'spawn':
        # Durable HANDOFF cannot be relabelled NO_HANDOFF by fixture teardown.
        # Retire only the original parent's FDs, retaining the occupied head.
        safety = runtime.shutdown_safety()
        assert not safety['pool_slots_freed'] and host.pool.snapshot()['occupied'] == 2


def test_actual_disk_worker_capacity_waiter_cancel_and_separate_STOP(application, monkeypatch):
    import asyncio
    import threading
    import time
    import httpx
    host, units, services, observers, app, token, headers = application
    entered = threading.Event(); release = threading.Event()
    health = host._disk.health
    def held():
        entered.set()
        assert release.wait(15)
        return health()
    monkeypatch.setattr(host._disk, 'health', held)
    disk_jobs = app.state.finite_host_disk_pool
    stop_jobs = app.state.finite_host_stop_pool
    assert disk_jobs is not stop_jobs and disk_jobs.limit == 1
    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                client.cookies.set('rlflow_session', token)
                first = asyncio.create_task(client.get('/api/v1/finite-host/disk-admission'))
                try:
                    assert await asyncio.to_thread(entered.wait, 2)
                    assert disk_jobs.pending == 1 and stop_jobs.pending == 0
                    second = await client.get('/api/v1/finite-host/disk-admission')
                    assert second.status_code == 429, second.text
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):await first
                    assert disk_jobs.pending == 1
                    third = await client.get('/api/v1/finite-host/disk-admission')
                    assert third.status_code == 429, third.text
                    stopped = await client.post(path(services[1]) + '/commands',
                        headers={**headers, 'Idempotency-Key': 'disk_queue_STOP'}, json=stop(services[1]))
                    assert stopped.status_code == 202, stopped.text
                    assert disk_jobs.pending == 1 and host.pool.snapshot()['occupied'] == 1
                finally:
                    release.set()
                    if not first.done():
                        first.cancel()
                        try:await first
                        except asyncio.CancelledError:pass
                deadline = time.monotonic() + 5
                while disk_jobs.pending and time.monotonic() < deadline:await asyncio.sleep(.01)
                assert disk_jobs.pending == 0
                final = await client.get('/api/v1/finite-host/disk-admission')
                assert final.status_code == 200, final.text
    asyncio.run(exercise())
    assert disk_jobs.closed and disk_jobs.pending == 0
    print('actual_disk_queue', dict(second_GET=429, cancelled_waiter_still_pending=True,
          third_GET=429, separate_STOP=202, after_future_GET=200, closed=True,
          barrier_before_Pool_lock=True), flush=True)
