"""Finite CPU keeper protocol substrate; NOT Core release/Pool authority.

Runs only in an original new delegated service. The product's general start
paths remain denied. A future original runtime owner must check its durable
lease/budget/STOP before calling release_gate; this class supplies only the
kernel protocol and original process/FD observations, not that authorization.
"""
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import threading
import time

from .hybrid_local_runner_cgroup import OriginalTaskScope, _inode, _start
from .hybrid_local_runner_sandbox import confine


class FiniteCpuKeeper:
    def __init__(self, scope):
        if type(scope) is not OriginalTaskScope:
            raise TypeError('original live task scope required')
        scope.check()
        self.scope = scope; self._pid = os.getpid()
        self._thread = threading.get_ident(); self._ready_proved = False
        self._producer = None; self._gate = None; self._ready = None
        self._gate_identity = None; self._ready_identity = None; self._pidfd_identity = None
        self._pidfd = None; self._closed = False; self._stop = False
        self._released = False; self._reaped = False
        self._gate_unknown = False
        self._task_stopped = False
        self._prepared = False
        self._child_gate = None; self._child_ready = None
        self._child_gate_identity = None; self._child_ready_identity = None
        if ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
            raise RuntimeError('finite keeper subreaper unavailable')

    def prepare_gate(self, code, work, output_fd, error_fd, *, seconds):
        self.scope.check()
        if self._prepared or self._producer is not None or self._gate_unknown or self._closed or self._stop:
            raise RuntimeError('original keeper cannot prepare again')
        if type(code) is not str or not 0 < len(code.encode()) <= 32768:
            raise ValueError('bounded CPU task source required')
        if type(seconds) is not int or not 1 <= seconds <= 300:
            raise ValueError('finite CPU task deadline required')
        work = Path(work).resolve(strict=True)
        sources = []
        for fd in (output_fd, error_fd):
            if type(fd) is not int or fd < 3:
                raise ValueError('original distinct output source descriptors required')
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise RuntimeError('private regular single-link output source required')
            sources.append((info.st_dev, info.st_ino))
        if sources[0] == sources[1]:
            raise RuntimeError('output/error original sources must be distinct')
        self._output_identities = tuple(sources)
        compiled = compile(code, '<original-local-task>', 'exec')
        self._prepared = True  # Never reopen even an uncertain partial prepare.
        self._child_gate, self._gate = os.pipe2(os.O_CLOEXEC)
        self._child_gate_identity = _inode(self._child_gate)
        self._gate_identity = _inode(self._gate)
        self._ready, self._child_ready = os.pipe2(os.O_CLOEXEC)
        self._ready_identity = _inode(self._ready)
        self._child_ready_identity = _inode(self._child_ready)
        read_gate, write_ready = self._child_gate, self._child_ready
        self._deadline = time.monotonic()+seconds
        self._source_hash = hashlib.sha256(code.encode()).hexdigest()
        self._gate_identity = _inode(self._gate); self._ready_identity = _inode(self._ready)
        # Handoff flag precedes fork: a lost fork return cannot be retried.
        self._gate_unknown = True
        pid = os.fork()
        if pid == 0:
            try:
                os.close(self._gate); os.close(self._ready)
                self.scope.enter_original_child()
                self._child(compiled, work, output_fd, error_fd, read_gate, write_ready, seconds)
            except BaseException:
                os._exit(125)
            os._exit(0)
        self._producer = pid
        self._starttime = _start(pid)
        self._pidfd = os.pidfd_open(pid)
        self._pidfd_identity = _inode(self._pidfd)
        self._gate_unknown = False
        os.close(read_gate); self._child_gate = None
        os.close(write_ready); self._child_ready = None
        if not select.select([self._ready], [], [], min(5, seconds))[0]:
            raise TimeoutError('original confined gate readiness unavailable')
        raw = os.read(self._ready, 4097)
        if len(raw) > 4096: raise RuntimeError('bounded gate readiness exceeded')
        receipt = json.loads(raw)
        expected = {'pid': pid, 'starttime': self._starttime,
                    'source_sha256': self._source_hash, 'sandbox': 'CPU_LOCAL_LANDLOCK_SECCOMP'}
        if receipt != expected:
            raise RuntimeError('original confined gate receipt differs')
        if Path(f'/proc/{pid}/cgroup').read_text().strip() != '0::'+self.scope._path+'/task':
            raise RuntimeError('original gate outside task scope')
        self.scope.check()
        if (_inode(self._ready) != self._ready_identity or
                _inode(self._pidfd) != self._pidfd_identity or _start(pid) != self._starttime):
            raise RuntimeError('original readiness source changed')
        self._ready_proved = True
        return receipt

    def _child(self, compiled, work, output_fd, error_fd, gate, ready, seconds):
        os.environ.clear()
        os.environ.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='none')
        null = os.open('/dev/null', os.O_RDONLY)
        os.dup2(null, 0); os.close(null)
        if tuple(_inode(fd)[:2] for fd in (output_fd, error_fd)) != self._output_identities:
            raise RuntimeError('original output source identity changed')
        os.dup2(output_fd, 1); os.dup2(error_fd, 2)
        python = Path('/usr/bin/python3').resolve(strict=True)
        executable = os.open(python, os.O_PATH | os.O_CLOEXEC)
        loader = os.open('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2', os.O_PATH | os.O_CLOEXEC)
        reads = [os.open(path, os.O_PATH | os.O_CLOEXEC) for path in ('/usr/lib', '/etc/ld.so.cache')]
        writable = os.open(work, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        keep = {0, 1, 2, gate, ready, executable, loader, writable, *reads}
        # No Controller/service/cgroup/pidfd/socket/secret descriptors reach
        # task code. This happens before inherited restrictions are installed.
        for number in os.listdir('/proc/self/fd'):
            fd = int(number)
            if fd not in keep:
                try: os.fstat(fd)
                except OSError as exc:
                    if exc.errno != errno.EBADF: raise
                else: os.close(fd)  # Any uncertain close aborts before G.
        starttime = _start(os.getpid())
        os.chdir(work)
        confine((executable, loader), tuple(reads), writable)
        for fd in (executable, loader, writable, *reads): os.close(fd)
        receipt = {'pid': os.getpid(), 'starttime': starttime,
                   'source_sha256': self._source_hash, 'sandbox': 'CPU_LOCAL_LANDLOCK_SECCOMP'}
        raw = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()
        if os.write(ready, raw) != len(raw): raise RuntimeError('partial confined receipt')
        os.close(ready)  # Task code can never forge the original ready source.
        signal.alarm(seconds)
        if not select.select([gate], [], [], seconds)[0] or os.read(gate, 1) != b'G':
            os._exit(126)
        os.close(gate)
        import sys
        try:
            exec(compiled, {'__name__': '__main__', 'WORK': str(work)})
        except BaseException as error:
            # Task-owned diagnostic only, after sandbox + G. Never print
            # pre-G trusted setup exceptions or parent control identities.
            sys.stderr.write('Task exception: '+type(error).__name__[:80]+': '+str(error)[:2048]+'\n')
            raise
        finally:
            # os._exit in the fork wrapper does not flush Python streams.
            # Preserve both success and failure logs inside the same deadline.
            sys.stdout.flush()
            sys.stderr.flush()

    def release_gate(self):
        # Kernel protocol only. Original Core authorization must be supplied
        # by its future owner, never inferred from this method's existence.
        self.scope.check()
        if self._stop or self._closed or not self._ready_proved or self._released or self._gate_unknown or self._producer is None:
            raise RuntimeError('original gate release unavailable')
        if time.monotonic() >= self._deadline:
            raise TimeoutError('original gate execution deadline passed')
        self.scope.check_single_keeper()
        if (_inode(self._gate) != self._gate_identity or _inode(self._pidfd) != self._pidfd_identity or
                _start(self._producer) != self._starttime):
            raise RuntimeError('original live gate identity changed')
        self._released = True  # Entered effect, including a lost/partial return.
        if os.write(self._gate, b'G') != 1: raise RuntimeError('gate release incomplete')

    def stop_and_reap_task(self):
        if os.getpid() != self._pid or threading.get_ident() != self._thread:
            raise RuntimeError('original keeper required')
        self._stop = True  # Irreversible before gate cancellation/kill.
        gate_unknown = False
        if self._gate is not None:
            try:
                if _inode(self._gate) != self._gate_identity:
                    raise RuntimeError('original release FD changed')
                os.close(self._gate)
            except (OSError, RuntimeError): gate_unknown = True
            else: self._gate = None
        # The original producer may still be in control immediately after
        # fork. Revoke it by its captured pidfd before checking task empty.
        if self._pidfd is not None:
            try:
                if _inode(self._pidfd) != self._pidfd_identity:
                    raise RuntimeError('original producer pidfd changed')
                try: signal.pidfd_send_signal(self._pidfd, signal.SIGKILL)
                except ProcessLookupError: pass  # Still require original waitpid.
            except (OSError, RuntimeError): gate_unknown = True
        result = self.scope.stop_task(5)
        end = time.monotonic()+5
        reaped = []
        while True:
            try: pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError: break
            if pid:
                reaped.append({'pid': pid, 'status': status})
                if pid == self._producer: self._reaped = True
            elif time.monotonic() >= end:
                raise TimeoutError('original keeper children not all reaped')
            else: time.sleep(.01)
        if self._producer is not None and not self._reaped:
            raise RuntimeError('original producer reap missing')
        # No remaining keeper children can enter task after this proof. This
        # also covers a gate with a lost fork return that exited on G EOF.
        result = self.scope.stop_task(5)
        self._task_stopped = True
        return {**result, 'reaped': reaped, 'release_attempted': self._released,
                'handoff_unknown': self._gate_unknown, 'stop_latched': True,
                'protocol_cleanup_unknown': gate_unknown}

    def run_original_control(self, control_fd):
        """Finite service-side protocol; never a Core authorization decision.

        The original external owner must durably authorize its one G before
        writing it. EOF, any other byte, producer exit and deadline all latch
        STOP and reap descendants. The caller still owns the control/source
        descriptors and must prove keeper/manager terminal before Pool FREE.
        """
        self.scope.check()
        if not self._ready_proved or self._stop or self._closed or self._released:
            raise RuntimeError('original prepared unreleased control loop required')
        if type(control_fd) is not int or control_fd < 3:
            raise ValueError('original read-only control pipe required')
        info = os.fstat(control_fd)
        if (not stat.S_ISFIFO(info.st_mode) or
                fcntl.fcntl(control_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            raise ValueError('original read-only control pipe required')
        control_identity = _inode(control_fd)
        reason = None
        try:
            while reason is None:
                self.scope.check()
                if (_inode(control_fd) != control_identity or
                        _inode(self._pidfd) != self._pidfd_identity):
                    raise RuntimeError('original control/producer source changed')
                remaining = self._deadline-time.monotonic()
                if remaining <= 0:
                    reason = 'DEADLINE'
                    break
                ready = select.select([control_fd, self._pidfd], [], [], min(.05, remaining))[0]
                # A producer terminal event wins over queued G. STOP then
                # clears any remaining descendant instead of starting more work.
                if self._pidfd in ready:
                    reason = 'PRODUCER_EXIT'
                elif control_fd in ready:
                    if _inode(control_fd) != control_identity:
                        raise RuntimeError('original control pipe changed before read')
                    command = os.read(control_fd, 1)
                    if command == b'G' and not self._released:
                        self.release_gate()
                    else:
                        reason = 'CONTROL_EOF' if not command else 'CONTROL_STOP'
        except BaseException:
            # Keep the original exception and cleanup handle if proof fails.
            # Never turn a lost G return or source error into a retry.
            self.stop_and_reap_task()
            raise
        result = self.stop_and_reap_task()
        return {**result, 'control_terminal_reason': reason}

    def close_stopped_task(self):
        if os.getpid() != self._pid or threading.get_ident() != self._thread:
            raise RuntimeError('original keeper required')
        if not self._stop or not self._task_stopped or (self._producer is not None and not self._reaped):
            raise RuntimeError('original STOP/reap required before close')
        failures = []
        for name, identity in (('_gate', self._gate_identity), ('_ready', self._ready_identity),
                               ('_pidfd', self._pidfd_identity),
                               ('_child_gate', self._child_gate_identity), ('_child_ready', self._child_ready_identity)):
            fd = getattr(self, name)
            if fd is not None:
                try:
                    if _inode(fd) != identity: raise RuntimeError('original keeper FD changed')
                    os.close(fd)
                except (OSError, RuntimeError): failures.append(name)
                else: setattr(self, name, None)
        result = self.scope.close_empty_task()
        if failures: raise RuntimeError('original keeper FD cleanup incomplete: '+','.join(failures))
        self._closed = True
        return {**result, 'keeper_protocol_handles_closed': True, 'stop_latched': True}
