"""Bounded private candidate copies from a protected explicit source manifest.

No discovery, Git, worker, lease or execution authority. The descriptor identifies
the copy, NOT an atomic point in a mutable source tree. Deadlines are cooperative
checks between local regular-file operations, not a kernel IO timeout guarantee.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
import uuid

from .files import relative_name, stamp
from .store import canonical, Conflict, sha

MAX_FILES = 4096
MAX_BYTES = 256*1024**2
MAX_NAME_BYTES = 1024*1024
MAX_SECONDS = 30
BLOCK = 65536


@contextmanager
def _directory(path):
    """Open all ancestors without following links; caller owns final descriptor."""
    path = Path(path).absolute(); descriptors = []
    try:
        if '..' in path.parts: raise Conflict('snapshot path must be canonical')
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC); descriptors.append(fd)
        for part in path.parts[1:]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            descriptors.append(fd)
        yield fd
    except OSError as error:
        raise Conflict('snapshot directory unavailable') from error
    finally:
        for fd in reversed(descriptors): os.close(fd)


@contextmanager
def _file(root_fd, name):
    descriptors = []; parts = name.split('/'); fd = root_fd
    try:
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            descriptors.append(fd)
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        descriptors.append(source)
        yield source, fd, parts[-1]
    except OSError as error:
        raise Conflict('snapshot source unavailable') from error
    finally:
        for fd in reversed(descriptors): os.close(fd)


def _identity(info):
    return [info.st_dev, info.st_ino]


def _private(info):
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Conflict('snapshot control requires private owned directory')


@dataclass(frozen=True, eq=False)
class CandidateSnapshot:
    id: str
    raw: bytes
    path: Path


def validate_manifest(source_files):
    """Validate the same finite explicit manifest without filesystem access."""
    if type(source_files) not in (list, tuple) or not 1 <= len(source_files) <= MAX_FILES:
        raise Conflict('bounded concrete snapshot manifest required')
    names = []; name_bytes = 0
    for name in source_files:
        relative_name(name)
        if '\x00' in name or len(name) > 4000: raise Conflict('invalid bounded snapshot name')
        try: name_bytes += len(name.encode())
        except UnicodeError as error: raise Conflict('invalid snapshot name encoding') from error
        if name_bytes > MAX_NAME_BYTES: raise Conflict('snapshot manifest exceeds bound')
        names.append(name)
    if len(set(names)) != len(names): raise Conflict('duplicate snapshot source')
    known = set(names); directories = {''}
    for name in names:
        parts = name.split('/')
        if len(parts) > 64: raise Conflict('snapshot source depth exceeds bound')
        directories.update('/'.join(parts[:index]) for index in range(1, len(parts)))
        if len(directories) > MAX_FILES: raise Conflict('snapshot directory count exceeds bound')
        if any('/'.join(parts[:index]) in known for index in range(1, len(parts))):
            raise Conflict('snapshot file/ancestor collision')
    return tuple(sorted(names)), tuple(sorted(directories))


class SnapshotBuilder:
    """Protected startup fixes both source root and finite exact source names.

    This internal builder does not resolve Goal scope or approval. The later
    service must check the protected manifest against approved boundaries. The
    API deliberately does not accept per-request paths, discovery or limits.
    """
    def __init__(self, source_root, source_files, control_root, *, byte_limit=MAX_BYTES,
                 seconds=MAX_SECONDS, clock=time.monotonic):
        self.names, self.directories = validate_manifest(source_files)
        if (type(byte_limit) is not int or not 1 <= byte_limit <= MAX_BYTES or
                type(seconds) not in (int, float) or not 0 < seconds <= MAX_SECONDS):
            raise Conflict('finite snapshot limits required')
        self.source = Path(source_root).absolute()
        self.root = Path(control_root).absolute()
        if (self.source == self.root or self.source in self.root.parents or self.root in self.source.parents):
            raise Conflict('snapshot source and control overlap')
        with _directory(self.source) as fd: self._source_identity = _identity(os.fstat(fd))
        with _directory(self.root) as fd:
            info = os.fstat(fd); _private(info); self._root_identity = _identity(info)
        self.byte_limit, self.seconds, self.clock = byte_limit, seconds, clock
        self._issued = {}; self._lock = threading.RLock()

    def _deadline(self, deadline):
        if self.clock() >= deadline: raise Conflict('snapshot deadline exceeded')

    def _roots(self, source, control):
        info = os.fstat(control); _private(info)
        if _identity(info) != self._root_identity or _identity(os.fstat(source)) != self._source_identity:
            raise Conflict('snapshot root identity changed')
        # Independently reopen paths to detect renamed/replaced ancestors.
        with _directory(self.root) as fd:
            if _identity(os.fstat(fd)) != self._root_identity: raise Conflict('snapshot control rebound')
        with _directory(self.source) as fd:
            if _identity(os.fstat(fd)) != self._source_identity: raise Conflict('snapshot source rebound')

    def build(self):
        with self._lock, _directory(self.source) as source, _directory(self.root) as control:
            self._roots(source, control)
            if len(self._issued) >= 128: raise Conflict('snapshot capacity reached')
            deadline = self.clock()+self.seconds
            # Random exclusive private path; neither source names nor identifiers
            # choose a directory that could overwrite existing user artifacts.
            key = 'snapshot_'+uuid.uuid4().hex
            os.mkdir(key, mode=0o700, dir_fd=control)
            path = self.root/key; identity = _identity(path.lstat()); success = False
            try:
                rows = []; total = 0
                for name in self.directories:
                    self._deadline(deadline)
                    if name: (path/name).mkdir(mode=0o700)
                for name in self.names:
                    self._deadline(deadline)
                    with _file(source, name) as (fd, parent, leaf):
                        before = os.fstat(fd)
                        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                                or before.st_size > self.byte_limit-total):
                            raise Conflict('snapshot source exceeds regular-file budget')
                        destination = path/name
                        digest = hashlib.sha256(); size = 0
                        with destination.open('xb') as output:
                            os.fchmod(output.fileno(), 0o600)
                            while chunk := os.read(fd, min(BLOCK, self.byte_limit-total+1)):
                                self._deadline(deadline); total += len(chunk); size += len(chunk)
                                if total > self.byte_limit: raise Conflict('snapshot bytes exceed bound')
                                digest.update(chunk); output.write(chunk)
                            output.flush(); os.fsync(output.fileno())
                        after = os.fstat(fd); current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                        if stamp(before) != stamp(after) or stamp(after) != stamp(current) or size != before.st_size:
                            raise Conflict('snapshot source changed during copy')
                        # Reopen descriptor-relative from root, so a swapped
                        # subdirectory cannot hide behind the old open parent.
                        with _file(source, name) as (again, _, _):
                            if stamp(os.fstat(again)) != stamp(after): raise Conflict('snapshot source path changed')
                        rows.append({'name': name, 'bytes': size, 'sha256': digest.hexdigest(),
                                     'mode': 0o600, 'source_executable': bool(before.st_mode & 0o111)})
                self._roots(source, control); self._deadline(deadline)
                value = {'schema_version': '1.0', 'files': rows, 'total_bytes': total,
                         'tree_hash': 'sha256:'+sha(rows), 'execution_enabled': False}
                snapshot = CandidateSnapshot(key, canonical(value), path)
                self._issued[key] = {'snapshot': snapshot, 'directory_identity': identity}
                try: self._verify(snapshot, deadline)
                except BaseException:
                    self._issued.pop(key, None); raise
                # Persist directory entries as well as file content before any
                # later core intent can claim this provisional copy is durable.
                for name in reversed(self.directories):
                    self._deadline(deadline)
                    with _directory(path/name) as directory: os.fsync(directory)
                os.fsync(control)
                self._deadline(deadline); self._roots(source, control)
                with _directory(path) as directory:
                    info = os.fstat(directory); _private(info)
                    if _identity(info) != identity: raise Conflict('snapshot copy directory rebound after fsync')
                success = True
                return snapshot
            finally:
                if not success:
                    self._issued.pop(key, None)
                    self._roots(source, control)
                    if _identity(path.lstat()) != identity: raise Conflict('snapshot staging rebound')
                    shutil.rmtree(path)

    def _inventory(self, path, deadline):
        expected = set(self.names) | set(self.directories)
        seen = {''}
        for name in self.directories:
            self._deadline(deadline)
            with _directory(path/name) as directory:
                _private(os.fstat(directory))
                with os.scandir(directory) as entries:
                    for entry in entries:
                        self._deadline(deadline)
                        relative = name+'/'+entry.name if name else entry.name
                        if relative not in expected or relative in seen:
                            raise Conflict('snapshot copy contains unexpected entries')
                        seen.add(relative)
                        current = entry.stat(follow_symlinks=False)
                        if not (stat.S_ISDIR(current.st_mode) if relative in self.directories
                                else stat.S_ISREG(current.st_mode)):
                            raise Conflict('snapshot copy entry type differs')
        if seen != expected: raise Conflict('snapshot copy inventory differs')

    def _verify(self, snapshot, deadline):
        issued = self._issued.get(getattr(snapshot, 'id', None))
        if type(snapshot) is not CandidateSnapshot or issued is None or issued['snapshot'] is not snapshot:
            raise PermissionError('actual builder-issued snapshot required')
        value = json.loads(snapshot.raw)
        with _directory(self.source) as source, _directory(self.root) as control, _directory(snapshot.path) as root:
            self._roots(source, control)
            info = os.fstat(root); _private(info)
            if _identity(info) != issued['directory_identity']: raise Conflict('snapshot copy directory rebound')
            self._inventory(snapshot.path, deadline)
            total = 0; verified = {}
            for row in value['files']:
                self._deadline(deadline)
                with _file(root, row['name']) as (fd, parent, leaf):
                    before = os.fstat(fd)
                    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.getuid()
                            or stat.S_IMODE(before.st_mode) != row['mode'] or before.st_size != row['bytes']):
                        raise Conflict('snapshot copy unavailable')
                    digest = hashlib.sha256(); size = 0
                    while chunk := os.read(fd, min(BLOCK, self.byte_limit-total+1)):
                        self._deadline(deadline); total += len(chunk); size += len(chunk)
                        if total > self.byte_limit: raise Conflict('snapshot copy exceeds bound')
                        digest.update(chunk)
                    after = os.fstat(fd)
                    if (stamp(before) != stamp(after) or stamp(after) != stamp(os.stat(leaf, dir_fd=parent, follow_symlinks=False))
                            or size != row['bytes'] or digest.hexdigest() != row['sha256']):
                        raise Conflict('snapshot copy changed')
                    with _file(root, row['name']) as (again, _, _):
                        if stamp(os.fstat(again)) != stamp(after): raise Conflict('snapshot copy path changed')
                    verified[row['name']] = stamp(after)
            if total != value['total_bytes']: raise Conflict('snapshot total differs')
            for name, expected in verified.items():
                self._deadline(deadline)
                with _file(root, name) as (fd, _, _):
                    if stamp(os.fstat(fd)) != expected: raise Conflict('snapshot copy changed after hashing')
            self._inventory(snapshot.path, deadline)
            with _directory(snapshot.path) as again:
                if _identity(os.fstat(again)) != issued['directory_identity']:
                    raise Conflict('snapshot copy directory rebound')
            self._roots(source, control); self._deadline(deadline)
            return {'snapshot_id': snapshot.id, 'tree_hash': value['tree_hash'],
                    'total_bytes': total, 'execution_enabled': False}

    def verify(self, snapshot):
        with self._lock: return self._verify(snapshot, self.clock()+self.seconds)
