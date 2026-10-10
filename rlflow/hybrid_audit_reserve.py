"""Small original-FD blank emergency allocation; not a quota/COMMIT guarantee."""
from contextlib import contextmanager
import fcntl
import os
import stat
import uuid

from .hybrid_runtime_boundary import _held_chain
from .store import Conflict

RESERVE_BYTES = 8 * 1024**2


class _AuditReserve:
    def __init__(self, domain, anchor):
        self.domain = domain
        self.path, self.chain, self.filesystem = anchor
        self.name = '.rlflow-audit-reserve-' + uuid.uuid4().hex + '.blank'
        self.fd = self.parent = None
        self.identity = None
        self.stamp = None
        self.release_entered = False
        self.creation_entered = False
        self.allocated = self.released = False

    def _actual(self):
        self.domain._actual()
        if (not self.domain.host.pool._lock._is_owned() or
                self.domain._reserves.get(self.filesystem) is not self):
            raise PermissionError('original held blank reserve required')

    @contextmanager
    def _directory(self):
        with _held_chain(self.path) as (fds, chain):
            info = os.fstat(fds[-1]); space = os.fstatvfs(fds[-1])
            if (chain != self.chain or (info.st_dev, space.f_fsid) != self.filesystem or
                    info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise Conflict('original private reserve directory changed')
            if self.parent is not None:
                held = os.fstat(self.parent)
                if (held.st_dev, held.st_ino) != (info.st_dev, info.st_ino) or os.get_inheritable(self.parent):
                    raise Conflict('original reserve parent descriptor changed')
            yield fds[-1]

    @staticmethod
    def _stamp(info):
        return (info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _file(self, parent, *, own_change=False):
        if self.fd is None or self.identity is None:
            raise Conflict('original reserve file descriptor unavailable')
        info = os.fstat(self.fd)
        named = os.stat(self.name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or
                (info.st_dev, info.st_ino) != self.identity or
                (named.st_dev, named.st_ino) != self.identity or os.get_inheritable(self.fd) or
                fcntl.fcntl(self.fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR or
                not 0 <= info.st_size <= RESERVE_BYTES or
                (not own_change and self.stamp is not None and self._stamp(info) != self.stamp)):
            raise Conflict('original blank reserve file changed')
        return info

    def allocate(self):
        self._actual()
        with self._directory() as parent:
            if self.fd is None:
                if self.creation_entered:
                    raise Conflict('unknown original reserve creation; no replacement adoption')
                if self.parent is None:
                    self.parent = os.dup(parent)
                self.creation_entered = True
                self.fd = os.open(self.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  0o600, dir_fd=parent)
                info = os.fstat(self.fd); self.identity = (info.st_dev, info.st_ino)
                self.stamp = self._stamp(info)
            self._file(parent)
            if self.release_entered:raise Conflict('consumed reserve cannot replenish new work')
            if not self.allocated:
                try:os.posix_fallocate(self.fd, 0, RESERVE_BYTES)
                finally:self.stamp = self._stamp(self._file(parent, own_change=True))
                os.fsync(self.fd); os.fsync(self.parent)
                info = self._file(parent)
                if info.st_size != RESERVE_BYTES or info.st_blocks * 512 < RESERVE_BYTES:
                    raise Conflict('real allocated reserve blocks required; no sparse substitute')
                self.allocated = True

    def observe(self):
        self._actual()
        with self._directory() as parent:
            # Exact pre-open interruption has no file effect to adopt. Keep
            # this original object retryable; unknown creation is NOT pending.
            if (self.fd is None and not self.creation_entered and self.identity is None and
                    self.stamp is None and not self.release_entered and
                    not self.allocated and not self.released):
                return {'allocated_bytes': 0, 'logical_bytes': 0,
                        'allocation_complete': False, 'released': False}
            info = self._file(parent)
            expected = 0 if self.released else RESERVE_BYTES if self.allocated else None
            if expected is not None and (info.st_size != expected or
                    (self.allocated and not self.released and info.st_blocks * 512 < RESERVE_BYTES)):
                raise Conflict('original reserve allocation changed')
            return {'allocated_bytes': info.st_blocks * 512, 'logical_bytes': info.st_size,
                    'allocation_complete': self.allocated, 'released': self.released}

    def release(self):
        self._actual()
        with self._directory() as parent:
            self._file(parent)
            if not self.released:
                self.release_entered = True
                try:os.ftruncate(self.fd, 0)
                finally:self.stamp = self._stamp(self._file(parent, own_change=True))
                os.fsync(self.fd); os.fsync(self.parent)
                info = self._file(parent)
                if info.st_size != 0:raise Conflict('original blank reserve release unknown')
                self.released = True

    def shutdown(self):
        self._actual()
        if self.fd is not None:
            # Keep the sole original FD if truncate/fsync fails. No unlink or
            # adoption: only this owner's blank extents, never experiment data.
            self.release()
            os.close(self.fd); self.fd = None
        if self.parent is not None:
            os.close(self.parent); self.parent = None

    def child_close(self):
        # Existing Pool fork coordinator holds all original Pool locks. Child
        # closes inherited descriptions only, never truncates the parent's file.
        for fd in (self.fd, self.parent):
            if fd is not None:
                try:os.close(fd)
                except OSError:pass
        self.fd = self.parent = None
