"""Actual nonexecuting fixture installation material, not a published bootstrap.

Under construction: the protected Store INTENT/READY owner is not wired yet.
Only new private temporary installations are constructed. No old namespace,
release, worker or actual capability is adopted from disk or caller JSON.
"""
from dataclasses import dataclass
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import uuid

from . import releases
from .hybrid_goals import digest
from .files import stamp
from .hybrid_protocol import ID, validate_schema
from .hybrid_runtime_boundary import (_held_chain, directory_chain, _catalog, policy_source)
from .hybrid_runtime_installation import intent_key, validate_record, SECTIONS
from .jobs import identity
from .observation import enable, ObservationReader
from .store import Store, Conflict, canonical, sha


@dataclass(frozen=True, eq=False)
class FixtureInstallationMaterial:
    id: str
    raw: bytes
    stage_path: Path
    release_path: Path


class _MaterialWitness:
    """Short-lived held original inventory, never serialized or request-created."""
    def __init__(self, builder, material, path, inventory, deadline):
        self.builder, self.material, self.path = builder, material, path
        self.inventory, self.deadline = inventory, deadline
        self.thread = threading.get_ident()

    def check(self):
        if threading.get_ident() != self.thread:
            raise PermissionError('original installation witness thread required')
        self.builder._check_physical(); _, value = self.builder._slot(self.material)
        sources, directories, chain = self.inventory
        _verify_inventory(self.path, sources, directories, chain, self.deadline)
        if _catalog(value['expected_seal']['descriptor']) != value['expected_seal']['catalog']:
            raise Conflict('original installation witness catalog differs')
        _deadline(self.deadline)


def _write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(fd, remaining)
            if count <= 0:
                raise Conflict('fixture material write failed')
            remaining = remaining[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _deadline(deadline):
    if deadline is not None and time.monotonic() > deadline:
        raise Conflict('fixture material exceeds finite cooperative time bound')


def _read_bounded(path, limit, *, parent_fd=None, expected=None, deadline=None):
    _deadline(deadline)
    fd = os.open(path if parent_fd is None else Path(path).name,
                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        if expected is not None and stamp(before) != expected:
            raise Conflict('original captured fixture file identity differs')
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= limit:
            raise Conflict('bounded original regular fixture file required')
        blocks = []; remaining = limit + 1
        while remaining:
            _deadline(deadline)
            block = os.read(fd, min(65536, remaining))
            if not block: break
            blocks.append(block); remaining -= len(block)
        raw = b''.join(blocks)
        after = os.fstat(fd)
        current = os.stat(path if parent_fd is None else Path(path).name,
                          dir_fd=parent_fd, follow_symlinks=False)
        if (len(raw) != before.st_size or len(raw) > limit or
                stamp(before) != stamp(after) or stamp(after) != stamp(current)):
            raise Conflict('original fixture file changed during bounded read')
        _deadline(deadline)
        return raw
    finally:
        os.close(fd)


_FOLDERS = {'rlflow', 'schemas', 'roles', 'tests'}
_TOP_FILES = {'model_policy.yaml', 'bootstrap.py', 'pyproject.toml', 'requirements.lock'}


@contextmanager
def _inventory(root, *, closed=False, deadline=None):
    """Retain the original descriptor graph; closed releases admit no hidden bytes.

    The trusted source checkout intentionally selects the existing code-only
    release domain. A staged release instead inventories EVERY entry, including
    root extras and caches, before it can be considered sealed.
    """
    root = Path(root); opened = []; sources = {}; directories = []
    with _held_chain(root) as (chain_fds, chain):
        root_fd = chain_fds[-1]
        root_info = os.fstat(root_fd)
        directories.append({'path': root, 'fd': root_fd, 'stamp': stamp(root_info), 'parent_fd': None})
        stack = [(root, root_fd, 0)]; entries_seen = 0; seen_top = set()
        try:
            while stack:
                _deadline(deadline)
                path, parent_fd, depth = stack.pop()
                if depth > 64: raise Conflict('fixture release directory enumeration exceeds bound')
                with os.scandir(parent_fd) as entries:
                    for item in entries:
                        _deadline(deadline); entries_seen += 1
                        if entries_seen > 4096:
                            raise Conflict('fixture release entry count exceeds bound')
                        name = item.name
                        if depth == 0:
                            if name not in _FOLDERS | _TOP_FILES | ({'release.json'} if closed else set()):
                                if closed: raise Conflict('fixture release contains extra root entry')
                                continue
                            seen_top.add(name)
                        if name == '__pycache__':
                            if closed: raise Conflict('fixture release contains unsealed cache')
                            continue
                        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                        if closed and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                            raise Conflict('fixture release requires private owner entries')
                        target = path / name
                        if stat.S_ISDIR(info.st_mode):
                            if depth == 0 and name not in _FOLDERS:
                                raise Conflict('fixture release root file is a directory')
                            if len(directories) >= 2048:
                                raise Conflict('fixture release directory enumeration exceeds bound')
                            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                         dir_fd=parent_fd); opened.append(fd)
                            if stamp(os.fstat(fd)) != stamp(info):
                                raise Conflict('original fixture directory changed during inventory')
                            directories.append({'path': target, 'fd': fd, 'stamp': stamp(info), 'parent_fd': parent_fd})
                            stack.append((target, fd, depth + 1))
                        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            if depth == 0 and name in _FOLDERS:
                                raise Conflict('fixture release root directory is a file')
                            if len(sources) >= 1025:
                                raise Conflict('fixture release file count exceeds bound')
                            sources[str(target.relative_to(root))] = {
                                'path': target, 'parent_fd': parent_fd, 'stamp': stamp(info)}
                        else:
                            raise Conflict('fixture release contains nonregular entry or symlink')
            if seen_top != _FOLDERS | _TOP_FILES | ({'release.json'} if closed else set()):
                raise Conflict('fixture release required root domain differs')
            if closed and (root_info.st_uid != os.getuid() or root_info.st_mode & 0o077):
                raise Conflict('fixture release requires private owner root')
            _deadline(deadline)
            yield sources, directories, chain
        finally:
            for fd in reversed(opened): os.close(fd)


def _verify_inventory(root, sources, directories, chain, deadline):
    for item in directories:
        _deadline(deadline)
        if stamp(os.fstat(item['fd'])) != item['stamp']:
            raise Conflict('original fixture directory changed during operation')
        current = (Path(root).lstat() if item['parent_fd'] is None else
                   os.stat(item['path'].name, dir_fd=item['parent_fd'], follow_symlinks=False))
        if stamp(current) != item['stamp']:
            raise Conflict('original fixture directory path changed during operation')
    for item in sources.values():
        _deadline(deadline)
        if stamp(os.stat(item['path'].name, dir_fd=item['parent_fd'], follow_symlinks=False)) != item['stamp']:
            raise Conflict('original captured fixture file changed during operation')
    if directory_chain(root) != chain:
        raise Conflict('original fixture ancestor chain changed during operation')
    _deadline(deadline)


def _sealed_domain(sources, directories, root, manifest):
    if set(sources) != set(manifest) | {'release.json'}:
        raise Conflict('original fixture release file domain differs')
    expected_dirs = {Path(root)}
    for name in manifest:
        parent = (Path(root) / name).parent
        while parent != root:
            expected_dirs.add(parent); parent = parent.parent
    if {item['path'] for item in directories} != expected_dirs:
        raise Conflict('fixture release contains unsealed extra directory')


class FixtureMaterialBuilder:
    """Fixed actual Store/source/namespace owner; at most one preparation attempt.

    Construction is trusted protected startup, not an HTTP/request interface.
    publish() below is deliberately unavailable until a core owner supplies the
    original persisted INTENT proof. verify() alone never permits publication.
    """
    @classmethod
    def create_live(cls,parent,*,project_id):
        """Protected fresh private Store only; no attach/migration or execution."""
        return cls(parent,project_id=project_id,_data_mode='live')

    def __init__(self, parent, *, project_id, _data_mode='fixture'):
        if _data_mode not in ('fixture','live'):raise ValueError('closed fresh installation domain')
        self.data_mode=_data_mode
        validate_schema(ID, project_id)
        parent = Path(parent).absolute()
        with _held_chain(parent) as (fds, _):
            info = os.fstat(fds[-1])
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Conflict('fixture installer requires a private owner parent')
        self._owner = identity(os.getpid())
        if self._owner is None:
            raise Conflict('actual fixture installation owner unavailable')
        self._lock = threading.RLock(); self._attempt = None; self._issued = {}
        self.root = Path(tempfile.mkdtemp(prefix='rlflow-guarded-fixture-', dir=parent))
        self._roots = {}
        for name in ('store', 'working', 'snapshots', 'source', 'bootstrap'):
            path = self.root / name; path.mkdir(mode=0o700)
            self._roots[name] = path
        # This is our freshly created isolated namespace, never an existing
        # install/migration. Do not depend on the host's group-writable umask.
        (self._roots['store']/'runtime').mkdir(mode=0o700)
        runtime=self._roots['store']/'runtime'
        with _held_chain(runtime) as (fds,chain):
            self._runtime_chain=chain
            self.store=Store(self._roots['store'])
            if directory_chain(runtime)!=chain:raise Conflict('new fixture original runtime changed during Store creation')
            original={}
            for name in ('research.db','writer.lock'):
                fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fds[-1])
                try:
                    info=os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
                        raise Conflict('new fixture original private Store file required')
                    original[name]=(info.st_dev,info.st_ino)
                    if stamp(os.stat(name,dir_fd=fds[-1],follow_symlinks=False))!=stamp(info):
                        raise Conflict('new fixture original Store file rebound before protection')
                    os.fchmod(fd,0o600);os.fsync(fd)
                    if (stamp(os.stat(name,dir_fd=fds[-1],follow_symlinks=False))!=stamp(os.fstat(fd)) or
                            directory_chain(runtime)!=chain):
                        raise Conflict('new fixture original Store file/parent rebound during protection')
                finally:os.close(fd)
            # Pin BEFORE enable; a lost/replaced database/lock must never
            # cause creation or adoption during initial registration.
            self._database_identity=list(original['research.db'])
            self.store._existing_identity=original['research.db']
            self.store._existing_lock_identity=original['writer.lock']
            self.project_id=project_id
            if directory_chain(runtime)!=chain:raise Conflict('new fixture original runtime changed before enable')
            self.store_epoch=enable(self.store,project_id=self.project_id,data_mode=self.data_mode)
            for name,expected in original.items():
                info=os.stat(name,dir_fd=fds[-1],follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or
                        stat.S_IMODE(info.st_mode)!=0o600 or (info.st_dev,info.st_ino)!=expected):
                    raise Conflict('new fixture original Store identity changed during enable')
            if directory_chain(runtime)!=chain:raise Conflict('new fixture original runtime changed during enable')
            os.fsync(fds[-1]);os.fsync(fds[-2])
        maintenance_lock = self.store.root / 'runtime/snapshot-maintenance.lock'
        _write_new(maintenance_lock, b'')
        maintenance_info = maintenance_lock.lstat()
        self.store._existing_lock_identities = {'writer': self.store._existing_lock_identity,
            'snapshot-maintenance': (maintenance_info.st_dev, maintenance_info.st_ino)}
        self._chains = {name: directory_chain(path) for name, path in self._roots.items()}
        self._root_chain = directory_chain(self.root)
        self._mount_namespace = os.stat('/proc/thread-self/ns/mnt').st_ino
        self._source = releases.ROOT
        self._source_chain = directory_chain(self._source)

    def _check_physical(self):
        if identity(os.getpid()) != self._owner:
            raise PermissionError('original actual fixture builder process required')
        if os.stat('/proc/thread-self/ns/mnt').st_ino != self._mount_namespace:
            raise Conflict('fixture installation mount namespace changed')
        if directory_chain(self.root) != self._root_chain:
            raise Conflict('fixture installation root rebound')
        for name, path in self._roots.items():
            with _held_chain(path) as (fds, chain):
                info = os.fstat(fds[-1])
                if chain != self._chains[name] or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise Conflict('fixture installation protected scope rebound')
        info = self.store.db.lstat()
        if directory_chain(self.store.db.parent) != self._runtime_chain:
            raise Conflict('fixture original database parent rebound')
        with _held_chain(self.store.db.parent) as (fds,_):
            parent_info=os.fstat(fds[-1])
            if parent_info.st_uid!=os.getuid() or parent_info.st_mode&0o077:
                raise Conflict('fixture original private database parent changed')
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode)!=0o600 or [info.st_dev, info.st_ino] != self._database_identity):
            raise Conflict('fixture original database identity differs')
        info = (self.store.root / 'runtime/writer.lock').lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode)!=0o600 or (info.st_dev, info.st_ino) != self.store._existing_lock_identity):
            raise Conflict('fixture original writer lock identity differs')

    def _check(self):
        self._check_physical()
        with self.store.read_connection() as db:
            db.execute('BEGIN')
            meta = ObservationReader._meta(db)
            if (meta['project_id'], meta['data_mode'], meta['store_epoch']) != (self.project_id, self.data_mode, self.store_epoch):
                raise Conflict('fixture installation original registration differs')

    def prepare(self):
        with self._lock:
            deadline = time.monotonic() + 30
            self._check()
            if self._attempt is not None:
                # Never remint IDs or unbounded provisional material after an
                # interrupted call. Known completed material remains reachable.
                if self._issued:
                    material = next(iter(self._issued.values()))['material']
                    self.verify(material, _operation_deadline=deadline)
                    _deadline(deadline)
                    return material
                raise Conflict('original fixture preparation incomplete; retained blocked attempt')
            request = {'action': 'prepare_fixture_runtime_installation', 'project_id': self.project_id,
                'data_mode': self.data_mode, 'store_epoch': self.store_epoch,
                'installation_id': 'fixture_install_' + uuid.uuid4().hex,
                'idempotency_key': 'fixture_intent', 'expected_state_version': 0}
            if self.data_mode=='live':
                from .hybrid_live_domain import PROFILE,PREPARE
                request.update(action=PREPARE,domain_profile=PROFILE)
            entry = {'request': request}
            self._attempt = entry  # ONE retained attempt before any material IO.
            with self.store.read_connection() as db:
                if db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0] != 0:
                    raise Conflict('new fixture installation core is no longer empty')
            bootstrap = self._roots['bootstrap']
            stage = bootstrap / ('stage-' + request['installation_id']); stage.mkdir(mode=0o700)
            destination = bootstrap / ('release-' + request['installation_id'])
            catalog_path = bootstrap / 'catalog.json'
            catalog = {'version': 1, 'mode': 'HYBRID_LEGACY_DENIED',
                'scopes': [{'reserved_path': str(path), 'directory_chain': self._chains[name]}
                           for name, path in self._roots.items()],
                'installation_ref': {'intent_key': intent_key(request), 'accepted_state_version': 1},
                'execution_enabled': False, 'release_enabled': False}
            raw = canonical(catalog); _write_new(catalog_path, raw)
            info = catalog_path.stat()
            descriptor = {'version': 1, 'mode': 'BOUND_HYBRID_NONEXECUTING',
                'catalog_path': str(catalog_path), 'catalog_sha256': hashlib.sha256(raw).hexdigest(),
                'catalog_parent_chain': self._chains['bootstrap'], 'catalog_identity': [info.st_dev, info.st_ino]}
            if directory_chain(self._source) != self._source_chain:
                raise Conflict('original fixture bootstrap source root rebound')
            manifest = {}; total = 0
            with _inventory(self._source, deadline=deadline) as (sources, directories, chain):
                if chain != self._source_chain or len(sources) > 1024:
                    raise Conflict('original fixture bootstrap source identity or count differs')
                for name, source in sources.items():
                    _deadline(deadline)
                    original = _read_bounded(source['path'], 16 * 1024**2 - total,
                        parent_fd=source['parent_fd'], expected=source['stamp'], deadline=deadline)
                    data = policy_source(descriptor) if name == 'rlflow/runtime_boundary_policy.py' else original
                    total += len(data)
                    if total > 16 * 1024**2:
                        raise Conflict('fixture release material exceeds finite bound')
                    target = stage / name
                    # pathlib parents=True applies mode only to the leaf.
                    # Nested packaged resources (e.g. skills/rlflow/SKILL.md)
                    # must not introduce default-umask intermediate dirs.
                    directory = stage
                    for part in Path(name).parts[:-1]:
                        directory /= part
                        directory.mkdir(mode=0o700, exist_ok=True)
                    _write_new(target, data); manifest[name] = hashlib.sha256(data).hexdigest()
                _verify_inventory(self._source, sources, directories, chain, deadline)
            seal = {'descriptor': descriptor, 'catalog': catalog, 'release_manifest': manifest, 'release_id': sha(manifest)}
            _write_new(stage / 'release.json', canonical({'id': seal['release_id'], 'files': manifest}))
            with _inventory(stage, closed=True, deadline=deadline) as (sources, directories, chain):
                _sealed_domain(sources, directories, stage, manifest)
                for directory in sorted(directories, key=lambda item: len(item['path'].parts), reverse=True):
                    _deadline(deadline); os.fsync(directory['fd'])
                _verify_inventory(stage, sources, directories, chain, deadline)
            _sync_directory(bootstrap); _sync_directory(self.root)
            _deadline(deadline)
            value = {'request': request, 'request_hash': digest(request),
                'binding': {'store_root': str(self.store.root), 'store_root_chain': self._chains['store'],
                    'database_identity': self._database_identity, 'working_namespace': str(self._roots['working']),
                    'working_namespace_chain': self._chains['working'], 'release_path': str(destination),
                    'release_parent_chain': self._chains['bootstrap'],
                    'bootstrap_template_hash': sha({n: h for n, h in manifest.items() if n != 'rlflow/runtime_boundary_policy.py'})},
                'expected_seal': seal, 'accepted_state_version': 1, 'state': 'LEGACY_DENIED_UNPUBLISHED',
                'execution_enabled': False, 'release_enabled': False}
            validate_record(SECTIONS[0], intent_key(request), value)
            raw = canonical(value)
            material = FixtureInstallationMaterial(request['installation_id'], raw, stage, destination)
            entry.update({'material': material, 'raw': raw, 'stage_path': stage, 'release_path': destination,
                          'stage_identity': directory_chain(stage)[-1]})
            self._issued[material.id] = entry  # Original object reachable after lost return.
            self.verify(material, _operation_deadline=deadline)
            _deadline(deadline)
            return material

    def _slot(self, material):
        if type(material) is not FixtureInstallationMaterial:
            raise PermissionError('actual original fixture material required')
        entry = next((entry for entry in self._issued.values() if entry['material'] is material), None)
        if entry is None:
            raise PermissionError('original issued fixture material required')
        if (material.raw != entry['raw'] or material.id != entry['request']['installation_id'] or
                material.stage_path != entry['stage_path'] or material.release_path != entry['release_path']):
            raise Conflict('original issued fixture material fields differ')
        return entry, json.loads(entry['raw'])

    def verify(self, material, *, _operation_deadline=None):
        with self._lock:
            deadline = min(time.monotonic() + 30, _operation_deadline) if _operation_deadline is not None else time.monotonic() + 30
            _deadline(deadline)
            self._check(); entry, value = self._slot(material)
            if material.release_path.exists() or material.release_path.is_symlink():
                path = material.release_path
                if material.stage_path.exists() or material.stage_path.is_symlink():
                    raise Conflict('fixture stage and destination both exist')
            else:
                path = material.stage_path
            if directory_chain(path)[-1] != entry['stage_identity']:
                raise Conflict('original fixture release directory identity differs')
            expected = value['expected_seal']
            actual = {}; remaining = 16 * 1024**2
            with _inventory(path, closed=True, deadline=deadline) as (sources, directories, chain):
                _sealed_domain(sources, directories, path, expected['release_manifest'])
                for name in expected['release_manifest']:
                    source = sources[name]
                    data = _read_bounded(source['path'], remaining, parent_fd=source['parent_fd'],
                                         expected=source['stamp'], deadline=deadline)
                    remaining -= len(data); actual[name] = hashlib.sha256(data).hexdigest()
                source = sources['release.json']
                raw = _read_bounded(source['path'], 1024**2, parent_fd=source['parent_fd'],
                                    expected=source['stamp'], deadline=deadline)
                if actual != expected['release_manifest'] or raw != canonical({'id': expected['release_id'], 'files': expected['release_manifest']}):
                    raise Conflict('original expected fixture release seal differs')
                if _catalog(expected['descriptor']) != expected['catalog']:
                    raise Conflict('original fixed fixture catalog differs')
                _verify_inventory(path, sources, directories, chain, deadline)
            self._check()
            _deadline(deadline)
            return value

    @contextmanager
    def _witness(self, material):
        """Hash outside writer, retain exactly that original FD/stamp graph.

        No builder lock is retained across yield: actual service lock order is
        Store writer -> Service -> Builder. The witness is ephemeral and can
        never be reconstructed from a READY/INTENT DTO or disk path.
        """
        deadline = time.monotonic() + 30
        with ExitStack() as cleanup:
            with self._lock:
                self._slot(material)
                path = material.release_path if material.release_path.exists() else material.stage_path
                inventory = cleanup.enter_context(_inventory(path, closed=True, deadline=deadline))
                self.verify(material, _operation_deadline=deadline)
                witness = _MaterialWitness(self, material, path, inventory, deadline)
                witness.check()
            yield witness

    def publish(self, material):
        # No persist-before-publish owner exists yet. This explicit refusal
        # cannot be bypassed with a JSON fact, expected hash or caller boolean.
        self._check(); self._slot(material)
        raise PermissionError('original core installation INTENT owner not yet available')
