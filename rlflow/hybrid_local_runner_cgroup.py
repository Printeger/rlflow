"""Original finite-service task cgroup, never Core authority or a cold grant.

A trusted finite keeper calls this only inside its own new delegated user
service. The Controller remains outside that service. Candidate code must run
in task, under the inherited CPU sandbox; it must never execute in control.
TASK_EMPTY does not imply that the keeper/service/whole managed scope stopped.
"""
import os
from pathlib import Path
import re
import stat
import threading
import time


CGROUP = Path('/sys/fs/cgroup')


def _read(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, 16385)
    if len(raw) > 16384:
        raise RuntimeError('bounded original cgroup read exceeded')
    return raw.decode('ascii').strip()


def _inode(fd):
    value = os.fstat(fd)
    return value.st_dev, value.st_ino, value.st_uid


def _start(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def _membership():
    rows = Path('/proc/self/cgroup').read_text().splitlines()
    if len(rows) != 1 or not rows[0].startswith('0::/'):
        raise RuntimeError('original unified cgroup membership required')
    return rows[0][3:]


class OriginalTaskScope:
    """Live held kernel scope; no reconstruction from JSON/path/inode allowed.

    No task is forked or released here. Caller retains this object in the
    finite keeper, forks a held gate, closes copied scope FDs in that child,
    then obtains the original Core release through its separate protocol.
    """
    FILES = ('cgroup.events', 'cgroup.procs', 'cpu.stat', 'memory.current',
             'memory.peak', 'memory.events', 'pids.current', 'pids.events',
             'memory.max', 'memory.swap.max', 'cpu.max', 'pids.max', 'memory.oom.group')

    def __init__(self, limits):
        if type(limits) is not dict:
            raise ValueError('closed finite task limits required')
        limits = dict(limits)
        if (any(type(n) is not str for n in limits) or
                set(limits) != {'memory_max', 'cpu_max', 'pids_max'} or
                any(type(limits[n]) is not int or not 1 <= limits[n] < 2**63
                    for n in ('memory_max', 'pids_max')) or
                type(limits['cpu_max']) is not str or
                re.fullmatch(r'[1-9][0-9]* [1-9][0-9]*', limits['cpu_max']) is None):
            raise ValueError('closed finite task limits required')
        quota, period = map(int, limits['cpu_max'].split())
        if not 1000 <= quota < 2**63 or not 1000 <= period <= 1000000:
            raise ValueError('finite CPU quota/period required')
        self._pid = os.getpid(); self._thread = threading.get_ident()
        self._start = _start(self._pid)
        self._boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self._path = _membership()
        prefix = f'/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/app.slice/'
        suffix = self._path.removeprefix(prefix)
        if (not self._path.startswith(prefix) or
                re.fullmatch(r'rlflow-local-[0-9a-f]{32}\.service', suffix) is None):
            raise RuntimeError('new original project finite user service required')
        self._limits = dict(limits)
        self._fds = {}; self._identities = {}; self._closed = False
        self._temporaries = {}; self._temporary_identities = {}
        self._empty = False; self._closing = False
        self._root = None; self._root_identity = None
        try:
            self._root = os.open(CGROUP/self._path.lstrip('/'), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self._root_identity = _inode(self._root)
            if self._root_identity[2] != os.getuid():
                raise RuntimeError('original service delegation unavailable')
            initial = self._temporary(self._root, 'cgroup.procs', os.O_RDONLY)
            try:
                if _read(initial).split() != [str(self._pid)]:
                    raise RuntimeError('service contains unrelated processes')
            finally: self._close_temporary(initial)
            # mkdir never reuses an unknown previous scope.
            os.mkdir('control', dir_fd=self._root)
            self._control = os.open('control', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._root)
            self._control_identity = _inode(self._control)
            self._write(self._control, 'cgroup.procs', str(self._pid))
            self._write(self._root, 'cgroup.subtree_control', '+cpu +memory +pids')
            os.mkdir('task', dir_fd=self._root)
            self._task = os.open('task', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._root)
            self._task_identity = _inode(self._task)
            expected = {'memory.max': str(limits['memory_max']), 'memory.swap.max': '0',
                        'cpu.max': limits['cpu_max'], 'pids.max': str(limits['pids_max']),
                        'memory.oom.group': '1'}
            self._expected = expected
            for name, value in expected.items(): self._write(self._task, name, value)
            for name in (*self.FILES, 'cgroup.kill'):
                fd = os.open(name, (os.O_WRONLY if name == 'cgroup.kill' else os.O_RDONLY) | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self._task)
                self._fds[name] = fd; self._identities[name] = _inode(fd)
            self.check()
        except BaseException as exc:
            # No candidate has been forked/released here. Closing handles does
            # not assert successful service teardown; keeper must exit safely.
            # Continue independent closes even if one fails. Do not overwrite
            # the initialization failure with a secondary cleanup exception.
            self._preparation_failed = True; self._closing = True
            if self._close_remaining():
                # The original failure carries this exact cleanup owner, not a
                # serialized reconstruction. No child/release was attempted.
                exc.original_scope_cleanup = self
            raise

    def _temporary(self, directory, name, mode):
        fd = os.open(name, mode | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=directory)
        self._temporaries[fd] = fd  # Retain immediately, including failed fstat.
        self._temporary_identities[fd] = _inode(fd)
        return fd

    def _close_temporary(self, fd):
        if _inode(fd) != self._temporary_identities.get(fd):
            raise RuntimeError('original temporary cgroup FD changed')
        os.close(fd)
        self._temporaries[fd] = None

    def _write(self, directory, name, value):
        fd = self._temporary(directory, name, os.O_WRONLY)
        try:
            raw = value.encode('ascii')
            if os.write(fd, raw) != len(raw): raise RuntimeError('partial original cgroup write')
        finally: self._close_temporary(fd)

    def check(self):
        if (self._closed or self._closing or os.getpid() != self._pid or threading.get_ident() != self._thread or
                _start(self._pid) != self._start or
                Path('/proc/sys/kernel/random/boot_id').read_text().strip() != self._boot or
                _membership() != self._path+'/control'):
            raise RuntimeError('original live finite keeper required')
        self._check_handles()
        # Directory loss is UNKNOWN/error, never evidence of empty. Do not
        # reopen a replacement by path or acquire a new cgroup capability.
        for name, identity in (('control', self._control_identity), ('task', self._task_identity)):
            value = os.stat(name, dir_fd=self._root, follow_symlinks=False)
            if (value.st_dev, value.st_ino, value.st_uid) != identity:
                raise RuntimeError('original cgroup namespace changed')
        for name, value in self._expected.items():
            if _read(self._fds[name]) != value: raise RuntimeError('original task limit drift')

    def _check_handles(self):
        for fd, identity in ((self._root, self._root_identity),
                             (self._control, self._control_identity),
                             (self._task, self._task_identity)):
            if _inode(fd) != identity: raise RuntimeError('original cgroup handle changed')
        for name, fd in self._fds.items():
            if _inode(fd) != self._identities[name]: raise RuntimeError('original cgroup source FD changed')

    def enter_original_child(self):
        """Fork copy only; never accept an arbitrary external PID to migrate."""
        if (self._closed or self._closing or os.getpid() == self._pid or os.getppid() != self._pid or
                _membership() != self._path+'/control' or _inode(self._task) != self._task_identity):
            raise RuntimeError('original direct held child required')
        self._check_handles()
        self._write(self._task, 'cgroup.procs', str(os.getpid()))
        if _membership() != self._path+'/task': raise RuntimeError('original child task entry failed')
        # Do not give candidate any inherited control/cgroup/source handles.
        for fd in (*self._fds.values(), self._task, self._control, self._root): os.close(fd)
        self._closed = True

    def check_single_keeper(self):
        """Exact held topology; reject extra scope, never adopt/kill by name.

        Task descendants may still run in task. Root is empty, control contains
        only this original keeper, and neither child has further cgroups.
        This observation is NOT whole-scope STOP and is not a cold capability.
        """
        self.check()
        for directory,expected in ((self._root,{'control','task'}),
                                   (self._control,set()),(self._task,set())):
            children=set()
            with os.scandir(directory) as entries:
                for index,entry in enumerate(entries):
                    if index>=256:raise RuntimeError('bounded original scope topology required')
                    if stat.S_ISDIR(entry.stat(follow_symlinks=False).st_mode):children.add(entry.name)
            if children!=expected:raise RuntimeError('original scope contains additional cgroups')
        for directory,expected in ((self._root,[]),(self._control,[str(self._pid)])):
            fd=self._temporary(directory,'cgroup.procs',os.O_RDONLY)
            try:
                if _read(fd).split()!=expected:raise RuntimeError('original scope contains additional producers')
            finally:self._close_temporary(fd)

    def task_empty(self):
        self.check()
        lines = dict(line.split() for line in _read(self._fds['cgroup.events']).splitlines())
        if set(lines) != {'populated', 'frozen'} or any(v not in ('0', '1') for v in lines.values()):
            raise RuntimeError('original task events unavailable')
        empty = lines['populated'] == '0' and _read(self._fds['cgroup.procs']) == ''
        self._empty = empty
        return empty

    def stop_task(self, timeout):
        if type(timeout) not in (int, float) or not 0 < timeout <= 10:
            raise ValueError('bounded task cleanup timeout required')
        self.check()
        if os.write(self._fds['cgroup.kill'], b'1') != 1:
            raise RuntimeError('original task kill incomplete')
        end = time.monotonic()+timeout
        while True:
            if self.task_empty():
                return {'task_empty': True, 'whole_scope_stopped': False,
                        'cpu_stat': _read(self._fds['cpu.stat']),
                        'memory_peak': int(_read(self._fds['memory.peak'])),
                        'keeper_still_live': True}
            if time.monotonic() >= end: raise TimeoutError('original task remains populated')
            time.sleep(.01)

    def close_empty_task(self):
        # Caller must already have closed all future original gate/release
        # routes. This fragment never creates a Pool cancellation tombstone.
        if not self._closing:
            if not self.task_empty(): raise RuntimeError('populated original task cannot be closed')
            self.check_single_keeper()
            self._closing = True
        if (os.getpid() != self._pid or threading.get_ident() != self._thread or
                _start(self._pid) != self._start or
                Path('/proc/sys/kernel/random/boot_id').read_text().strip() != self._boot or
                _membership() != self._path+'/control'):
            raise RuntimeError('original closing finite keeper required')
        failures = self._close_remaining()
        if failures:
            raise RuntimeError('original task handle cleanup incomplete: '+','.join(failures))
        # A receipt here must NEVER release Pool: keeper/manager are still live.
        return {'task_handles_closed': True, 'whole_scope_stopped': False}

    def retry_preparation_cleanup(self):
        if (not getattr(self, '_preparation_failed', False) or os.getpid() != self._pid or
                threading.get_ident() != self._thread or _start(self._pid) != self._start or
                Path('/proc/sys/kernel/random/boot_id').read_text().strip() != self._boot):
            raise RuntimeError('original failed preparation cleanup owner required')
        if self._close_remaining(): raise RuntimeError('original preparation handles remain unknown')
        return {'preparation_handles_closed': True, 'whole_scope_stopped': False}

    def _close_remaining(self):
        """Only held original identities; success cleared, unknown never adopted."""
        failures = []
        slots = [(name, self._fds, name, self._identities.get(name)) for name in self._fds]
        slots += [('temporary-'+str(fd), self._temporaries, fd, self._temporary_identities.get(fd))
                  for fd in self._temporaries]
        for name in ('_task', '_control', '_root'):
            slots.append((name, self.__dict__, name, getattr(self, name+'_identity', None)))
        for label, container, key, identity in slots:
            fd = container.get(key)
            if fd is None: continue
            try:
                if identity is None or _inode(fd) != identity:
                    raise RuntimeError('original close FD identity unavailable')
                os.close(fd)
            except (OSError, RuntimeError):
                failures.append(label)  # Strong retain; no foreign close/rebind.
            else:
                container[key] = None
        self._closed = not failures
        return failures
