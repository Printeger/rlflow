"""One explicitly requested, original-Host derived-cache worker; no scheduler."""
import json
import contextlib
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import time

from .hybrid_runtime_boundary import _held_chain
from .jobs import identity, owns
from .store import Conflict, canonical, Store

CPU_SECONDS = 10
ADDRESS_BYTES = 1024**3
WALL_SECONDS = 15
_child_quarantine = []


def _binding(store, project, epoch):
    store._check_existing_identity()
    with _held_chain(store.root / 'runtime') as (_, chain):
        locks = getattr(store, '_existing_lock_identities', {})
        expected = {'research.db': list(store._existing_identity),
                    'writer.lock': list(store._existing_lock_identity),
                    'snapshot-maintenance.lock': list(locks['snapshot-maintenance'])}
        record = dict(root=str(store.root), chain=chain, files=expected,
                      project=project, epoch=epoch)
        _physical(record)
        return record


def _physical(record):
    with _held_chain(Path(record['root']) / 'runtime') as (fds, chain):
        if canonical(chain) != canonical(record['chain']):
            raise Conflict('original snapshot job directory changed')
        for name, expected in record['files'].items():
            info = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or
                    [info.st_dev, info.st_ino] != expected):
                raise Conflict('original snapshot job file changed')


def _resources(record):
    from .hybrid_disk_admission import FLOOR_BYTES, WORK_BYTES, FLOOR_INODES, WORK_INODES
    credits = max(1, record['resource_credits'])
    for path, captured, filesystem in record['anchors']:
        with _held_chain(path) as (fds, chain):
            info = os.fstat(fds[-1]); space = os.fstatvfs(fds[-1])
            if (canonical(chain) != canonical(captured) or
                    [info.st_dev, space.f_fsid] != filesystem or space.f_frsize <= 0 or
                    space.f_bavail * space.f_frsize < FLOOR_BYTES + credits * WORK_BYTES or
                    space.f_favail < FLOOR_INODES + credits * WORK_INODES):
                raise Conflict('optional snapshot work lacks original disk headroom')


def _head(db, record):
    meta = db.execute('SELECT project_id,data_mode,store_epoch,source_version FROM observation_meta WHERE singleton=1').fetchone()
    version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
    tip = db.execute('SELECT MAX(seq) FROM events').fetchone()[0] or 0
    if (tuple(meta[:3]) != (record['project'], 'fixture', record['epoch']) or
            type(version) is not int or version < 0 or version != meta[3] or version != tip):
        raise Conflict('original snapshot job source head changed')
    if version:
        event = db.execute('SELECT previous_state_version,new_state_version FROM events WHERE seq=?', (version,)).fetchone()
        if event is None or tuple(event) != (version - 1, version):
            raise Conflict('original snapshot job event tip changed')
    due = db.execute('SELECT due_version,last_complete FROM snapshot_due WHERE singleton=1').fetchone()
    if (due is None or any(type(v) is not int or not 0 <= v <= version for v in due) or
            due[1] and not db.execute('SELECT 1 FROM snapshots WHERE version=?', (due[1],)).fetchone()):
        raise Conflict('original snapshot job maintenance metadata changed')
    return version


class _SnapshotJobs:
    def __init__(self, host):
        self.host = host; self.rows = {}; self.lock = threading.RLock()
        self.process = self.producer = self.pidfd = self.started = None
        self.spawn_entered = False; self.closed = False; self.last = None
        self.record = self.store = self.requested_version = None
        self.pidfd_identity = self.stdin_identity = None
        self.requesting = False

    def bind(self, unit):
        self.rows[id(unit.lease)] = _binding(unit.runtime.store,
            unit.runtime.workspace.project_id, unit.runtime.workspace.store_epoch)

    def _original(self):
        self.host._pure_identity()
        if self.closed or getattr(self.host, '_snapshots', None) is not self:
            raise PermissionError('original live snapshot coordinator required')

    def request(self, lease):
        self._original(); unit = self.host._unit(lease)
        # Reentrant calls must reject before Pool IO (fork takes Pool -> job).
        if self.requesting or self.spawn_entered:
            raise Conflict('snapshot maintenance occupied; inspect original job')
        # Acquire Pool only before the job lock, preserving the fork lock order.
        health = self.host._disk.health()
        if (health['emergency_frozen'] or health['unbound_occupied_claim'] or
                not health['filesystems'] or not all(row['admissible'] for row in health['filesystems'])):
            raise Conflict('optional snapshot admission unavailable')
        if not self.lock.acquire(blocking=False):raise Conflict('snapshot maintenance busy; no queue')
        entered = False
        try:
            self._original()
            if self.spawn_entered or self.requesting:raise Conflict('snapshot maintenance occupied; inspect original job')
            self.requesting = True
            entered = True
            if self.host._disk._emergency_frozen:raise Conflict('optional snapshot admission frozen')
            record = dict(self.rows[id(lease)])
            rows = self.host._disk._rows
            record.update(resource_credits=len(rows), anchors=[(str(path), chain, list(filesystem))
                for row in rows for path, chain, filesystem in row['anchors']])
            _physical(record); _resources(record)
            store = unit.runtime.store
            root = str(Path(__file__).resolve().parents[1])
            dependencies = str(Path(__import__('jsonschema').__file__).resolve().parent.parent)
            bootstrap = ('import sys;sys.path[:0]=sys.argv[1:3];'
                         'from rlflow.hybrid_snapshot_job_worker import main;main()')
            config = canonical(dict(binding=record, parent=os.getpid()))
            if len(config) > 65536:raise Conflict('snapshot worker configuration exceeds bound')
            with store.lock(nonblocking=True), contextlib.closing(sqlite3.connect(
                    store.db.as_uri() + '?mode=rw', uri=True, timeout=0)) as db:
                with db:
                    if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                        raise Conflict('original snapshot journal mode changed')
                    db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
                    _physical(record); version = _head(db, record)
                    if self.host._disk._emergency_frozen:raise Conflict('optional snapshot admission frozen')
                    db.execute('UPDATE snapshot_due SET due_version=MAX(due_version,?) WHERE singleton=1', (version,))
            # Persist the pending request before an uncertain child handoff.
            self.record, self.store, self.requested_version = record, store, version
            self._original()
            if self.host._disk._emergency_frozen:raise Conflict('optional snapshot admission frozen')
            self.spawn_entered = True; self.started = time.monotonic()
            self.process = subprocess.Popen([sys.executable, '-B', '-I', '-S', '-c', bootstrap, root, dependencies],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, env={'LANG': 'C.UTF-8'}, cwd=root, start_new_session=True)
            self.producer = identity(self.process.pid)
            if self.producer is None:raise Conflict('snapshot original child identity unavailable')
            pipe = os.fstat(self.process.stdin.fileno())
            self.stdin_identity = (pipe.st_dev, pipe.st_ino)
            self.pidfd = os.pidfd_open(self.process.pid)
            pin = os.fstat(self.pidfd); self.pidfd_identity = (pin.st_dev, pin.st_ino)
            self._stdin_check(); self.process.stdin.write(config)
            self._stdin_check(); self.process.stdin.close()
            return {'status': 'PENDING', 'pid': self.producer['pid'], 'requested_version': version,
                    'resource_enforcement': 'partial', 'business_version_changed': False}
        finally:
            if entered:self.requesting = False
            self.lock.release()

    def _stdin_check(self):
        fd = self.process.stdin.fileno(); info = os.fstat(fd)
        if (not stat.S_ISFIFO(info.st_mode) or (info.st_dev, info.st_ino) != self.stdin_identity or
                os.get_inheritable(fd)):
            raise Conflict('snapshot original input descriptor changed')

    def _pidfd_check(self, *, live):
        if self.pidfd is None:raise Conflict('snapshot original pidfd unavailable')
        info = os.fstat(self.pidfd)
        if (info.st_dev, info.st_ino) != self.pidfd_identity or os.get_inheritable(self.pidfd):
            raise Conflict('snapshot original pidfd changed')
        if live:
            with open('/proc/self/fdinfo/' + str(self.pidfd), 'rb') as stream:raw = stream.read(4097)
            if len(raw) > 4096 or ('Pid:\t' + str(self.producer['pid']) + '\n').encode() not in raw:
                raise Conflict('snapshot original pidfd target changed')

    def poll(self):
        self._original()
        with self.lock:
            self._original()
            if not self.spawn_entered:return self.last or {'status': 'IDLE'}
            if self.process is None:return {'status': 'UNKNOWN', 'slot_occupied': True}
            if self.process.poll() is None:
                if time.monotonic() - self.started > WALL_SECONDS:
                    self._kill()
                else:return {'status': 'PENDING', 'pid': self.process.pid, 'slot_occupied': True}
            code = self.process.wait(timeout=1)
            if self.pidfd is not None:
                self._pidfd_check(live=False); os.close(self.pidfd); self.pidfd = None
            self.last = {'status': 'WORKER_EXITED', 'exit_code': code, 'slot_occupied': False,
                         'resource_enforcement': 'partial'}
            self.process = self.producer = None; self.spawn_entered = False
            # Reap proves the slot is clear, not that cache publication happened.
            try:
                _physical(self.record)
                with self.store.read_connection() as db:
                    db.execute('BEGIN'); _head(db, self.record)
                    completed = db.execute('SELECT last_complete FROM snapshot_due WHERE singleton=1').fetchone()[0]
                    row = db.execute('SELECT sha256 FROM snapshots WHERE version=?', (completed,)).fetchone()
                    if (code == 0 and completed >= self.requested_version and row is not None and
                            type(row[0]) is str and len(row[0]) == 64 and
                            all(char in '0123456789abcdef' for char in row[0])):
                        self.last.update(status='SNAPSHOT_PUBLISHED_AS_OF', snapshot_version=completed)
                    elif code != 0:self.last['status'] = 'PUBLICATION_UNKNOWN'
            except (OSError, ValueError, Conflict, sqlite3.Error):
                self.last['status'] = 'PUBLICATION_UNKNOWN'
            return dict(self.last)

    def _kill(self):
        if self.process is not None and self.process.poll() is None:
            if self.pidfd is None or self.producer is None or not owns(self.producer):
                raise Conflict('snapshot original identity uncertain; never kill by PID')
            self._pidfd_check(live=True)
            signal.pidfd_send_signal(self.pidfd, signal.SIGKILL)
            self.process.wait(timeout=2)

    def close(self):
        self._original()
        with self.lock:
            if self.spawn_entered and self.process is None:
                raise Conflict('snapshot handoff UNKNOWN; original slot retained')
            self._kill()
            if self.process is not None:
                self.process.wait(timeout=2)
                if self.process.stdin is not None and not self.process.stdin.closed:
                    self._stdin_check(); self.process.stdin.close()
            if self.pidfd is not None:
                self._pidfd_check(live=False); os.close(self.pidfd)
            self.process = self.pidfd = None; self.closed = True

    def child_close(self):
        if self.process is not None:
            if self.process.stdin is not None and not self.process.stdin.closed:
                try:self._stdin_check(); os.close(self.process.stdin.fileno())
                except (OSError, ValueError, Conflict):pass
            _child_quarantine.append(self.process)
        if self.pidfd is not None:
            try:self._pidfd_check(live=False); os.close(self.pidfd)
            except (OSError, Conflict):pass
        self.process = self.pidfd = None; self.closed = True
