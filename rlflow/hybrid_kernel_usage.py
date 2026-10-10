"""Original fixed-child wait4 observations, never a billing/refund capability.

Linux rusage includes waited descendants; only our pinned no-descendant programs
qualify for the fixed-participant lifetime label. maxrss is KiB, not a tree sum.
"""
import copy
import inspect
import os
import sys

from .observation import utc


class _KernelUsageCapture:
    def __init__(self, process):
        self.process = process
        self.creator = os.getpid(); self.pid = process.pid
        self.record = None
        self.installed = False
        if (sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 12) or
                sys.platform != 'linux' or not hasattr(os, 'wait4') or process.returncode is not None):
            return
        if '_waitpid' not in inspect.signature(process._internal_poll).parameters:
            return
        self._poll = process._internal_poll
        self._wait = process._wait
        self._try = process._try_wait
        self._kernel_wait = os.wait4
        # Preserve CPython's existing _waitpid_lock and timeout/status handling.
        process._internal_poll = self._internal_poll
        process._try_wait = self._try_wait
        process._wait = self._original_wait
        self.installed = True

    def _original(self):
        if os.getpid() != self.creator or self.process.pid != self.pid:
            raise PermissionError('original kernel usage child required')

    def _bound(self):
        """Observation identity only; never an extra physical reap gate."""
        self._original()
        return self.installed and all(getattr(getattr(self.process, name, None), '__self__', None) is self
            for name in ('_internal_poll', '_try_wait', '_wait'))

    def _wait4(self, pid, flags):
        self._original()
        if pid != self.pid:raise PermissionError('foreign kernel usage wait refused')
        waited, status, usage = self._kernel_wait(pid, flags)
        if waited == self.pid and self.record is None:
            # No Source/Pool/Store locks, schema work, or publication in reap.
            try:
                self.record = dict(status='KNOWN', source='LINUX_WAIT4',
                    scope='FIXED_PARTICIPANT_LIFETIME', exit_code=os.waitstatus_to_exitcode(status),
                    cpu_user_us=round(usage.ru_utime * 1000000),
                    cpu_system_us=round(usage.ru_stime * 1000000),
                    peak_rss_bytes=usage.ru_maxrss * 1024, reaped_at=utc())
            except Exception:
                # Resource observation must not discard a real reap/status.
                self.record = None
        return waited, status

    def _internal_poll(self, _deadstate=None):
        self._original()  # Before the inherited waitpid lock.
        return self._poll(_deadstate, _waitpid=self._wait4)

    def _try_wait(self, flags):
        try:return self._wait4(self.pid, flags)
        except ChildProcessError:
            # Preserve existing Popen exit handling, but absent rusage stays None.
            return self._try(flags)

    def _original_wait(self, timeout):
        self._original()  # Before CPython _wait acquires its lock.
        return self._wait(timeout)

    def snapshot(self):
        self._original()
        if not self.installed:return None
        if not self._bound():raise PermissionError('original installed kernel observer required')
        return copy.deepcopy(self.record)
