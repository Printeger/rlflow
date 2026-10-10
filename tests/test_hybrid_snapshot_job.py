"""Actual original finite Host cache maintenance, no business scheduler/model."""
import os
import sqlite3
import subprocess
import time

import pytest

from rlflow.store import Conflict
from tests.test_hybrid_host_execution import shared
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_fixture_runtime import _FIXED_CPU_POPEN


@pytest.fixture(autouse=True)
def fixed_cache_only(shared, monkeypatch):
    original = subprocess.Popen
    def launch(argv, **kwargs):
        if len(argv) == 8 and argv[4] == '-c':
            assert argv[:4] == [__import__('sys').executable, '-B', '-I', '-S']
            assert argv[5] == ('import sys;sys.path[:0]=sys.argv[1:3];'
                               'from rlflow.hybrid_snapshot_job_worker import main;main()')
            assert kwargs['env'] == {'LANG': 'C.UTF-8'} and kwargs['close_fds']
            return _FIXED_CPU_POPEN(argv, **kwargs)
        return original(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', launch)


def terminal(host):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        value = host.poll_snapshot_maintenance()
        if value['status'] != 'PENDING':return value
        time.sleep(.02)
    pytest.fail('original snapshot worker failed to terminate')


def test_actual_original_SDK_background_publish_preserves_business_and_cursor(shared):
    host, units = shared; store = units[0].runtime.store
    with store.read_connection() as db:
        before = tuple(db.execute('SELECT source_version,seq FROM observation_meta').fetchone())
        events = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    result = host.request_snapshot_maintenance(units[0].lease)
    assert result['status'] == 'PENDING' and result['pid'] != os.getpid()
    value = terminal(host)
    assert value['status'] == 'SNAPSHOT_PUBLISHED_AS_OF', value
    assert value['snapshot_version'] == before[0] and value['exit_code'] == 0
    with store.read_connection() as db:
        assert tuple(db.execute('SELECT source_version,seq FROM observation_meta').fetchone()) == before
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == events
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone()) == (0, before[0])
        assert db.execute('SELECT COUNT(*) FROM snapshots WHERE version=?', (before[0],)).fetchone()[0] == 1
    assert host.pool.snapshot()['occupied'] == 2
    print('actual_snapshot_job', dict(independent_PID=True, snapshot_version=before[0],
          business_version_and_cursor_unchanged=True, model_calls=0), flush=True)


def test_actual_shared_slot_busy_before_second_project_mark_and_shutdown_reaps(shared):
    import signal
    host, units = shared
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; process = job.process
    # Stop the exact original child while its bounded job is still occupied.
    signal.pidfd_send_signal(job.pidfd, signal.SIGSTOP)
    with units[1].runtime.store.read_connection() as db:
        before = tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone())
    with pytest.raises(Conflict, match='occupied'):
        host.request_snapshot_maintenance(units[1].lease)
    with units[1].runtime.store.read_connection() as db:
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone()) == before
    job.close()
    assert process.poll() is not None and job.pidfd is None
    with units[0].runtime.store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] > 0


def test_original_emergency_freeze_during_last_mark_IO_never_launches(shared, monkeypatch):
    from rlflow import hybrid_snapshot_job as jobs
    host, units = shared; actual = jobs._head
    def freeze(db, record):
        version = actual(db, record)
        host._disk._emergency_frozen = True
        return version
    monkeypatch.setattr(jobs, '_head', freeze)
    with pytest.raises(Conflict, match='frozen'):
        host.request_snapshot_maintenance(units[0].lease)
    assert host._snapshots.process is None and not host._snapshots.spawn_entered
    with units[0].runtime.store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] == 0


def test_actual_failed_child_with_corrupt_old_cache_never_reports_publication(shared):
    host, units = shared; store = units[0].runtime.store
    host.request_snapshot_maintenance(units[0].lease)
    assert terminal(host)['status'] == 'SNAPSHOT_PUBLISHED_AS_OF'
    with store.lock(), store.connect() as db:
        db.execute("UPDATE snapshots SET state=X'00'")
    host.request_snapshot_maintenance(units[0].lease)
    value = terminal(host)
    assert value['exit_code'] != 0 and value['status'] == 'PUBLICATION_UNKNOWN'
    with store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] > 0
        assert bytes(db.execute('SELECT state FROM snapshots').fetchone()[0]) == b'\0'


def test_actual_fork_closes_original_job_pidfd_without_signalling_parent(shared):
    import select
    import signal
    host, units = shared
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; descriptor = job.pidfd
    signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            try:os.fstat(descriptor)
            except OSError:os.write(write_fd, b'closed')
            else:os.write(write_fd, b'open')
        finally:os._exit(0)
    os.close(write_fd)
    try:
        assert select.select([read_fd], [], [], 4)[0]
        assert os.read(read_fd, 32) == b'closed'
        assert os.waitpid(pid, 0)[1] == 0
        assert job.process.poll() is None
        signal.pidfd_send_signal(descriptor, signal.SIGCONT)
        assert terminal(host)['status'] == 'SNAPSHOT_PUBLISHED_AS_OF'
    finally:os.close(read_fd)


def test_foreign_reused_pidfd_never_closed_or_signalled(shared):
    import signal
    host, units = shared
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; descriptor = job.pidfd
    signal.pidfd_send_signal(descriptor, signal.SIGSTOP)
    retained = os.dup(descriptor)
    foreign = os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.dup2(foreign, descriptor, inheritable=False)
        with pytest.raises(Conflict, match='pidfd changed'):job.close()
        assert job.process.poll() is None and os.fstat(descriptor).st_ino == os.fstat(foreign).st_ino
        os.dup2(retained, descriptor, inheritable=False)
        job.close()
        assert job.pidfd is None
    finally:
        os.close(retained); os.close(foreign)


def test_actual_job_wait_timeout_still_closes_other_original_reserve(shared, monkeypatch):
    import signal
    host, units = shared
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values()))
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; process = job.process
    signal.pidfd_send_signal(job.pidfd, signal.SIGSTOP)
    for unit in units:unit.runtime.shutdown()
    actual_wait = process.wait
    with monkeypatch.context() as patch:
        def timeout(*args, **kwargs):raise subprocess.TimeoutExpired('original snapshot', 2)
        patch.setattr(process, 'wait', timeout)
        with pytest.raises(Conflict, match='cleanup remains uncertain'):host.pool.shutdown()
        assert host.pool._live and job.spawn_entered and not job.closed
        assert reserve.fd is None and reserve.parent is None
    actual_wait(timeout=2)
    host.pool.shutdown()
    assert not host.pool._live and job.closed


def test_reentrant_original_request_rejects_before_any_Pool_health(shared, monkeypatch):
    from rlflow import hybrid_snapshot_job as jobs
    host, units = shared; actual = jobs._head; seen = []
    def reenter(db, record):
        with monkeypatch.context() as patch:
            patch.setattr(host._disk, 'health', lambda:pytest.fail('reentrant request entered Pool IO'))
            with pytest.raises(Conflict, match='occupied'):
                host.request_snapshot_maintenance(units[1].lease)
        seen.append(True)
        return actual(db, record)
    monkeypatch.setattr(jobs, '_head', reenter)
    host.request_snapshot_maintenance(units[0].lease)
    # The poll also verifies the head; restore the diagnostic mark hook first.
    monkeypatch.setattr(jobs, '_head', actual)
    assert terminal(host)['status'] == 'SNAPSHOT_PUBLISHED_AS_OF' and seen == [True]


def test_actual_hash_barrier_STOP_and_snapshot_tail_offline_recovery(shared, monkeypatch, tmp_path):
    import inspect
    import signal
    from rlflow import snapshot_maintenance as maintenance
    from rlflow.store import Store
    host, units = shared; store = units[0].runtime.store
    source, first = inspect.getsourcelines(maintenance.maintain)
    line = first + next(i for i, value in enumerate(source) if 'digest=hashlib.sha256(raw)' in value)
    filename = inspect.getsourcefile(maintenance.maintain)
    original_launch = subprocess.Popen
    # Test-only trace stops the real fixed child immediately before its hash,
    # after actual consistent construction/lineage validation. No business FD.
    trace = ("import os,signal,sys\n"
        "sys.path[:0]=sys.argv[1:3]\n"
        "def barrier(frame,event,arg):\n"
        f" if event=='line' and frame.f_code.co_filename=={filename!r} and frame.f_lineno=={line}:\n"
        "  sys.settrace(None);os.kill(os.getpid(),signal.SIGSTOP)\n"
        " return barrier\n"
        "sys.settrace(barrier)\n"
        "from rlflow.hybrid_snapshot_job_worker import main\nmain()")
    def launch(argv, **kwargs):
        assert argv[:5] == [__import__('sys').executable, '-B', '-I', '-S', '-c']
        assert argv[5] == ('import sys;sys.path[:0]=sys.argv[1:3];'
                           'from rlflow.hybrid_snapshot_job_worker import main;main()')
        assert kwargs['close_fds'] and kwargs['env'] == {'LANG': 'C.UTF-8'}
        diagnostic = list(argv); diagnostic[5] = trace
        return _FIXED_CPU_POPEN(diagnostic, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, 'Popen', launch)
        pending = host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with open('/proc/' + str(pending['pid']) + '/status') as stream:status = stream.read()
        if 'State:\tT' in status:break
        assert job.process.poll() is None
        time.sleep(.01)
    else:pytest.fail('real cache child never reached actual hash trace barrier')
    before = store.version()
    cancelled = host.cancel(units[0].lease)
    assert cancelled is not None and store.version() > before
    assert job.process.poll() is None and job.spawn_entered
    signal.pidfd_send_signal(job.pidfd, signal.SIGCONT)
    value = terminal(host)
    assert value['status'] == 'SNAPSHOT_PUBLISHED_AS_OF' and value['snapshot_version'] == before
    expected = store.audit()
    for unit in units:unit.runtime.shutdown()
    host.pool.shutdown()
    clone = tmp_path / 'offline_recovery'; clone.mkdir(mode=0o700)
    runtime = clone / 'runtime'; runtime.mkdir(mode=0o700)
    destination = runtime / 'research.db'
    with store.read_connection() as original, sqlite3.connect(destination) as copied:
        original.backup(copied)
    destination.chmod(0o600)
    lock = os.open(runtime / 'writer.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(lock)
    attached = Store.attach_existing(clone, project_id=job.record['project'], data_mode='fixture')
    with attached.connect() as db:
        assert db.execute('SELECT MAX(version) FROM snapshots').fetchone()[0] == before
        assert db.execute('SELECT COUNT(*) FROM events WHERE seq>?', (before,)).fetchone()[0] > 0
        db.execute('DELETE FROM projection')
    assert attached.recover() == expected
    print('actual_hash_STOP_snapshot_tail', dict(snapshot=before, tail=expected['version'] - before,
          isolated_attach_no_DDL=True, control_completed_while_child_stopped=True), flush=True)


def test_actual_low_space_request_never_marks_or_consumes_original_reserve(shared, monkeypatch):
    from types import SimpleNamespace
    host, units = shared; store = units[0].runtime.store
    host._disk.check(units[0], allocate=True)
    reserve = next(iter(host._disk._reserves.values())); actual = os.fstatvfs
    def low(fd):
        value = actual(fd)
        return SimpleNamespace(f_fsid=value.f_fsid, f_frsize=value.f_frsize, f_bavail=0, f_favail=value.f_favail)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'fstatvfs', low)
        with pytest.raises(Conflict, match='admission unavailable'):
            host.request_snapshot_maintenance(units[0].lease)
    assert not host._snapshots.spawn_entered and host._snapshots.process is None
    assert os.fstat(reserve.fd).st_size == 8 * 1024**2 and not reserve.release_entered
    with store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] == 0


@pytest.mark.parametrize('failure', ['space', 'deadline'])
def test_actual_late_publication_guard_keeps_SDK_pending_and_no_partial_snapshot(shared, monkeypatch, failure):
    import signal
    from types import SimpleNamespace
    from rlflow import hybrid_snapshot_job as jobs, snapshot_maintenance as maintenance
    host, units = shared; store = units[0].runtime.store
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots
    signal.pidfd_send_signal(job.pidfd, signal.SIGSTOP)
    job.close()
    record = job.record; actual = os.fstatvfs; now = time.monotonic(); clock = [now]
    def late():
        if failure == 'deadline':clock[0] += 6
        else:
            def low(fd):
                value = actual(fd)
                return SimpleNamespace(f_fsid=value.f_fsid, f_frsize=value.f_frsize, f_bavail=0, f_favail=value.f_favail)
            with monkeypatch.context() as patch:
                patch.setattr(os, 'fstatvfs', low)
                jobs._resources(record)
    with monkeypatch.context() as patch:
        if failure == 'deadline':patch.setattr(maintenance.time, 'monotonic', lambda:clock[0])
        assert not maintenance.maintain(store, _before_publish=late)
    with store.read_connection() as db:
        assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone()) == (job.requested_version, 0)
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()


def test_actual_original_job_wall_timeout_reaps_before_slot_reuse(shared):
    import signal
    host, units = shared
    host.request_snapshot_maintenance(units[0].lease)
    job = host._snapshots; process = job.process
    signal.pidfd_send_signal(job.pidfd, signal.SIGSTOP)
    value = terminal(host)  # Wait for the real fixed 15-second parent deadline.
    assert value['status'] == 'PUBLICATION_UNKNOWN' and value['exit_code'] == -signal.SIGKILL
    assert process.poll() is not None and job.pidfd is None and not job.spawn_entered
    with units[0].runtime.store.read_connection() as db:
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] > 0
        assert not db.execute('SELECT 1 FROM snapshots').fetchone()
    host.request_snapshot_maintenance(units[1].lease)
    assert terminal(host)['status'] == 'SNAPSHOT_PUBLISHED_AS_OF'


def test_original_writer_namespace_replacement_refuses_before_mark_or_spawn(shared):
    host, units = shared; store = units[0].runtime.store
    writer = store.root / 'runtime/writer.lock'; retained = writer.with_name('writer-original.lock')
    writer.rename(retained)
    fd = os.open(writer, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
    try:
        # The original runtime identity gate rejects the rebound writer even
        # before the cache-specific file check; neither path can mark/launch.
        with pytest.raises(Conflict, match='original project database rebound'):
            host.request_snapshot_maintenance(units[0].lease)
        assert job_idle(host)
        with store.read_connection() as db:
            assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0] == 0
    finally:
        writer.unlink(); retained.rename(writer)


def job_idle(host):
    return host._snapshots.process is None and not host._snapshots.spawn_entered
