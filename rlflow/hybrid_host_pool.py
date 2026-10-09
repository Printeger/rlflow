"""Fixed shared three-slot FIXTURE application pool; no runtime handoff.

Protected startup only, never request/environment-selected installation paths.
Actual FD locks AND durable occupied heads are required. Death, expiry, restart
or idle flock never refunds an unknown claim. This does not migrate production,
fence noncooperating same-UID programs, or authorize a model/provider request.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
import uuid

from .hybrid_fixture_materials import _write_new, _read_bounded, _sync_directory
from .hybrid_installation_service import FixtureInstallationService
from .hybrid_runtime_boundary import _held_chain, directory_chain, _chain_value
from .hybrid_workspace_kernel import _fd_scope, _exclusive_lock, _private
from .hybrid_host_pool_ledger import (CAPACITY, MAX_EVENTS, MAX_BYTES, closed, count,
                                    pair, identifier, validate, parse, head, links, member)
from .hybrid_runtime_installation import SECTIONS, validate_complete
from .hybrid_reads import ReadBudget
from .hybrid_goals import digest
from .observation import ObservationReader
from .jobs import identity
from .store import Store, Conflict, canonical, sha

_owners = {}
_registry_lock = threading.RLock()
_fork_sql_quarantine = []  # Child must not invoke inherited SQLite cleanup.
_fork_extensions = {}  # Trusted module lifecycle hooks; never request-selected.

_SLOT_EXPR = "json_extract(raw,'$.slot')"
_ACTION_EXPR = "json_extract(raw,'$.action')"
_DDL = (
    'CREATE TABLE meta(singleton INTEGER PRIMARY KEY CHECK(singleton=1),version INTEGER NOT NULL)',
    'CREATE TABLE ledger(seq INTEGER PRIMARY KEY,key TEXT UNIQUE NOT NULL,action TEXT NOT NULL,slot INTEGER,raw TEXT NOT NULL,hash TEXT NOT NULL)',
    'CREATE INDEX slot_tip ON ledger(' + _SLOT_EXPR + ',seq DESC)',
    'CREATE INDEX action_tip ON ledger(' + _ACTION_EXPR + ',seq DESC)',
    "CREATE TRIGGER immutable_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'immutable pool fact'); END",
    "CREATE TRIGGER immutable_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'immutable pool fact'); END",
    'CREATE TABLE members(id TEXT PRIMARY KEY,project_id TEXT UNIQUE NOT NULL,store_root TEXT UNIQUE NOT NULL,key TEXT UNIQUE NOT NULL)',
    'CREATE TABLE heads(slot INTEGER PRIMARY KEY,raw TEXT NOT NULL)',
)


def _bounded(column, limit):
    # Never allocate attacker-sized SQL cells in Python, including headers.
    return (f"CASE WHEN typeof({column})='text' AND length(CAST({column} AS BLOB))<={limit} "
            f'THEN {column} END AS {column}')


def _rw_descriptors():
    result = {}
    with os.scandir('/proc/self/fd') as entries:
        for index, entry in enumerate(entries):
            if index >= 4096: raise Conflict('finite native descriptor census exceeded')
            try:
                fd = int(entry.name); info = os.fstat(fd)
                if stat.S_ISREG(info.st_mode) and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDWR:
                    result[fd] = (info.st_dev, info.st_ino)
            except OSError as error:
                if error.errno != 9: raise
    return result


def _native_sql_fd(db, before, expected):
    after = _rw_descriptors()
    created = [(fd, pair_) for fd, pair_ in after.items() if before.get(fd) != pair_]
    if len(created) != 1 or list(created[0][1]) != list(expected):
        raise Conflict('actual native pool SQLite descriptor identity differs or is uncertain')
    fd = created[0][0]
    _check_sql_fd(fd, expected)
    return fd


def _check_sql_fd(fd, expected):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
            stat.S_IMODE(info.st_mode) != 0o600 or [info.st_dev, info.st_ino] != list(expected) or
            os.get_inheritable(fd) or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR):
        raise Conflict('actual original native SQLite descriptor changed')


def _fork_prepare():
    _registry_lock.acquire()
    for owner in _owners.values(): owner._lock.acquire()
    # Python runs before-fork callbacks in REVERSE registration order. Owned
    # downstream components join this coordinator, not a later os callback.
    for name in sorted(_fork_extensions): _fork_extensions[name][0]()


def _fork_parent():
    for name in reversed(sorted(_fork_extensions)): _fork_extensions[name][1]()
    for owner in reversed(tuple(_owners.values())): owner._lock.release()
    _registry_lock.release()


def _fork_child():
    global _registry_lock
    # Only CLOSE inherited descriptions. LOCK_UN would unlock the parent.
    for owner in tuple(_owners.values()):
        owner._live = False
        descriptors = set(owner._pins.values())
        for db, fd in owner._sql_active.values():
            descriptors.add(fd); _fork_sql_quarantine.append(db)
        # A same-thread fork can occur with an open rollback journal. Close its
        # inherited FD too, never call SQLite/LOCK_UN in the child.
        if owner._sql_active:
            with os.scandir('/proc/self/fd') as entries:
                for entry in entries:
                    try:
                        if os.readlink(entry.path) == str(owner.root / 'pool.db-journal'):
                            descriptors.add(int(entry.name))
                    except OSError: pass
        for slot in owner._slots.values(): descriptors.update(fd for fd in slot.fds if fd is not None)
        for fd in descriptors:
            try: os.close(fd)
            except OSError: pass
        owner._lock = threading.RLock()
    for _, _, child in _fork_extensions.values(): child()
    _owners.clear(); _registry_lock = threading.RLock()


os.register_at_fork(before=_fork_prepare, after_in_parent=_fork_parent, after_in_child=_fork_child)


@dataclass(frozen=True, eq=False)
class PoolMembership:
    """Original nonexecuting membership, not an ExecutionLease or bootstrap."""
    id: str
    raw: bytes


@dataclass(frozen=True, eq=False)
class PoolClaim:
    id: str
    raw: bytes


@dataclass(frozen=True, eq=False)
class _Closing:
    claim: PoolClaim
    raw: bytes


@dataclass(frozen=True, eq=False)
class ClosedSlotWitness:
    closing: _Closing
    raw: bytes


class _Slot:
    def __init__(self, owner, number):
        self.owner, self.number = owner, number
        self.fds = [None, None]; self.closed = False
        owner._slots[number] = self  # Retain even a failed cleanup before return.
        path = owner.root / ('slot' + str(number))
        with _held_chain(path) as (fds, chain):
            if chain != owner.binding['slot_chains'][number]: raise Conflict('original pool slot rebound')
            _private(fds[-1]); _private(fds[-2])
            try:
                self.fds[0] = os.dup(fds[-1]); self.fds[1] = os.dup(fds[-2])
                fcntl.flock(self.fds[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                self.close(); raise
        try: self.check()
        except BaseException:
            self.close(); raise

    def check(self):
        if self.closed or any(fd is None for fd in self.fds): raise Conflict('original pool slot closed')
        expected = self.owner.binding['slot_chains'][self.number]
        for fd, scope in zip(self.fds, (expected[-1], expected[-2])):
            if list(_fd_scope(fd)) != scope or os.get_inheritable(fd):
                raise Conflict('original pool slot descriptor differs')
            _private(fd)
        _exclusive_lock(self.fds[0], self.owner.process['pid'])
        if directory_chain(self.owner.root / ('slot' + str(self.number))) != expected:
            raise Conflict('original pool slot ancestor differs')

    def close(self):
        expected = self.owner.binding['slot_chains'][self.number]
        errors = []
        for index, scope in enumerate((expected[-1], expected[-2])):
            fd = self.fds[index]
            if fd is None: continue
            try:
                if list(_fd_scope(fd)) != scope: raise Conflict('original slot descriptor reused before close')
                os.close(fd); self.fds[index] = None
            except (OSError, Conflict) as error: errors.append(error)
        if errors: raise Conflict('pool slot cleanup uncertain; original descriptors retained') from errors[0]
        self.closed = True


class HostPoolOwner:
    """One fixed application installation shared by all its managed projects.

create_fixture()/trusted_attach() are PROTECTED fixture startup interfaces.
Projects get original membership objects, never a pool path/create parameter.
All model, child process and native delegation handoff remain denied.
"""
    @classmethod
    def create_fixture(cls, parent):
        parent = Path(parent).absolute()
        with _held_chain(parent) as (fds, _): _private(fds[-1])
        app = Path(tempfile.mkdtemp(prefix='rlflow-host-fixture-', dir=parent))
        root = app / 'host_pool'; root.mkdir(mode=0o700)
        projects = app / 'projects'; projects.mkdir(mode=0o700)
        for number in range(CAPACITY): (root / ('slot' + str(number))).mkdir(mode=0o700)
        for name in ('pool.db', 'writer.lock'): _write_new(root / name, b'')
        expected_database = _file_pair(root / 'pool.db')
        before = _rw_descriptors(); db = sqlite3.connect(root / 'pool.db')
        try:
            _native_sql_fd(db, before, expected_database)
            db.execute('PRAGMA journal_mode=DELETE'); db.execute('PRAGMA synchronous=FULL')
            for statement in _DDL: db.execute(statement)
            db.execute('INSERT INTO meta VALUES(1,0)')
            db.executemany('INSERT INTO heads VALUES(?,?)', [(i, 'null') for i in range(CAPACITY)])
            db.commit()
        finally: db.close()
        owner_process = identity(os.getpid())
        if owner_process is None: raise Conflict('actual pool startup process unavailable')
        binding = {'version': 1, 'pool_id': 'pool_' + uuid.uuid4().hex, 'capacity': CAPACITY,
            'boot_id': owner_process['boot_id'], 'application_chain': directory_chain(app),
            'pool_chain': directory_chain(root), 'projects_chain': directory_chain(projects),
            'database_identity': list(_file_pair(root / 'pool.db')),
            'writer_identity': list(_file_pair(root / 'writer.lock')),
            'slot_chains': [directory_chain(root / ('slot' + str(i))) for i in range(CAPACITY)]}
        raw = canonical(binding); _write_new(root / 'descriptor.json', raw)
        _sync_directory(root); _sync_directory(app)
        return cls.trusted_attach(app, _raw_hash(raw), list(_file_pair(root / 'descriptor.json')))

    @classmethod
    def trusted_attach(cls, application_root, descriptor_sha256, descriptor_identity):
        """Fixed protected startup PIN, not a request JSON or restored slot grant.

        The operator-installed fixture application is the shared namespace.
        A second pool directory cannot be selected inside this application.
        Historical occupied heads stay occupied; only FREE slots can be issued.
        """
        if (type(descriptor_sha256) is not str or len(descriptor_sha256) != 64 or
                any(c not in '0123456789abcdef' for c in descriptor_sha256)):
            raise Conflict('original protected pool descriptor pin required')
        pair(descriptor_identity)
        app = Path(application_root).absolute(); root = app / 'host_pool'
        with _held_chain(root) as (fds, _):
            _private(fds[-1]); _private(fds[-2])
            if list(_file_pair(root / 'descriptor.json')) != descriptor_identity:
                raise Conflict('original pool descriptor identity differs')
            raw = _read_bounded(root / 'descriptor.json', MAX_BYTES, parent_fd=fds[-1])
        if _raw_hash(raw) != descriptor_sha256: raise Conflict('original protected pool descriptor digest differs')
        try: binding = json.loads(raw)
        except (ValueError, RecursionError): raise Conflict('invalid pool startup descriptor') from None
        closed(binding, ('version', 'pool_id', 'capacity', 'boot_id', 'application_chain', 'pool_chain',
                         'projects_chain', 'database_identity', 'writer_identity', 'slot_chains'))
        if (canonical(binding) != raw or type(binding['version']) is not int or binding['version'] != 1 or
                type(binding['capacity']) is not int or binding['capacity'] != CAPACITY or
                type(binding['slot_chains']) is not list or len(binding['slot_chains']) != CAPACITY):
            raise Conflict('fixed closed three-slot descriptor required')
        pair(binding['database_identity']); pair(binding['writer_identity']); identifier(binding['pool_id'])
        for path, key in ((app, 'application_chain'), (root, 'pool_chain'), (app / 'projects', 'projects_chain')):
            _chain_value(binding[key], path)
        for i in range(CAPACITY): _chain_value(binding['slot_chains'][i], root / ('slot' + str(i)))
        owner = cls.__new__(cls)
        owner.application_root, owner.root, owner.projects_root = app, root, app / 'projects'
        owner.binding, owner.descriptor_sha256, owner.descriptor_identity = binding, descriptor_sha256, descriptor_identity
        owner.process = identity(os.getpid()); owner._namespace = os.stat('/proc/thread-self/ns/mnt').st_ino
        if owner.process is None: raise Conflict('actual original pool startup process unavailable')
        owner._lock = threading.RLock(); owner._live = True; owner._pins = {}; owner._slots = {}; owner._sql_active = {}
        owner._members = {}; owner._claims = {}; owner._claim_slots = {}; owner._attempts = {}; owner._closings = {}; owner._witnesses = {}
        with _registry_lock:
            if len(_owners) >= 32: raise Conflict('fixture pool owner capacity reached')
            try:
                with _held_chain(root) as (fds, _):
                    for name in ('pool.db', 'writer.lock', 'descriptor.json'):
                        owner._pins[name] = os.open(name,
                            (os.O_RDWR if name == 'writer.lock' else os.O_RDONLY) |
                            os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fds[-1])
                owner._physical()
                _owners[id(owner)] = owner
                with owner._transaction(audit=True) as db: owner._audit(db)
            except BaseException:
                owner._live = False
                for fd in owner._pins.values():
                    try: os.close(fd)
                    except OSError: pass
                _owners.pop(id(owner), None); raise
        return owner

    def _actual(self):
        if not self._live or identity(os.getpid()) != self.process:
            raise PermissionError('actual original host pool process required')

    def _physical(self):
        self._actual()
        if self.process['boot_id'] != self.binding['boot_id'] or os.stat('/proc/thread-self/ns/mnt').st_ino != self._namespace:
            raise Conflict('host pool boot or mount namespace changed; occupied claims not cleared')
        for path, key in ((self.application_root, 'application_chain'), (self.root, 'pool_chain'),
                          (self.projects_root, 'projects_chain')):
            with _held_chain(path) as (fds, chain):
                _private(fds[-1])
                if chain != self.binding[key]: raise Conflict('original application pool namespace rebound')
        expected = {'pool.db': self.binding['database_identity'], 'writer.lock': self.binding['writer_identity'],
                    'descriptor.json': self.descriptor_identity}
        with _held_chain(self.root) as (fds, _):
            for name, original in expected.items():
                info = os.fstat(self._pins[name]); current = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                        stat.S_IMODE(info.st_mode) != 0o600 or [info.st_dev, info.st_ino] != original or
                        (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or
                        os.get_inheritable(self._pins[name])):
                    raise Conflict('original private pool file descriptor differs')
            raw = _read_bounded(self.root / 'descriptor.json', MAX_BYTES, parent_fd=fds[-1])
            if _raw_hash(raw) != self.descriptor_sha256: raise Conflict('original pool descriptor changed')

    @contextmanager
    def _transaction(self, final=None, source=None, witness=None, slot_guard=None, clock=None, audit=False):
        with self._lock:
            if self._sql_active: raise Conflict('original SQLite transaction cleanup remains uncertain')
            self._physical(); fd = self._pins['writer.lock']
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            db = None; native_fd = None; deadline = time.monotonic() + (30 if audit else 5); stack = ExitStack()
            try:
                self._physical()
                before = _rw_descriptors()
                db = sqlite3.connect((self.root / 'pool.db').as_uri() + '?mode=rw', uri=True, timeout=1)
                native_fd = _native_sql_fd(db, before, self.binding['database_identity'])
                self._sql_active[id(db)] = (db, native_fd)
                db.row_factory = sqlite3.Row
                if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                    raise Conflict('fixed pool journal mode differs')
                db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
                if source is not None:
                    if type(source) is not FixtureInstallationService:
                        raise PermissionError('fixed original pool installation source required')
                    stack.enter_context(source._lock); stack.enter_context(source.builder._lock)
                yield db
                self._actual()  # Forked child must never touch inherited SQLite.
                self._state(db)
                if final is not None: final(db)
                if source is not None:
                    with source.store.read_connection() as original_db:
                        original_db.execute('BEGIN')
                        source._bootstrap_point(original_db, witness, ReadBudget(original_db, 16*1024**2))
                self._physical()
                if slot_guard is not None: slot_guard()
                _check_sql_fd(native_fd, self.binding['database_identity'])
                _exclusive_lock(fd, self.process['pid'])
                if time.monotonic() > deadline: raise Conflict('finite host pool transaction deadline exceeded')
                # Fresh original TTL is checked AFTER every source/FD/path IO.
                # No capability minting, IO or caller callback between this and COMMIT.
                if clock is not None: clock()
                db.commit()
            except BaseException:
                if db is not None and os.getpid() == self.process['pid']: db.rollback()
                raise
            finally:
                if os.getpid() == self.process['pid']:
                    stack.close()
                    if db is not None:
                        db.close(); self._sql_active.pop(id(db), None)
                    fcntl.flock(fd, fcntl.LOCK_UN)

    def _schema(self, db):
        self._actual()
        rows = db.execute('SELECT ' + _bounded('sql', 4096) +
                          ' FROM sqlite_master WHERE sql IS NOT NULL LIMIT 10').fetchall()
        if len(rows) != len(_DDL) or sorted(row[0] for row in rows if type(row[0]) is str) != sorted(_DDL):
            raise Conflict('fixed pool schema/index definition differs')

    def _point(self, db, key):
        self._actual()
        if type(key) is not str: raise Conflict('bounded indexed pool key required')
        identifier(key)
        row = db.execute('SELECT seq,' + ','.join((_bounded('key', 160), _bounded('action', 32),
                         "CASE WHEN typeof(slot) IN ('integer','null') THEN slot END AS slot",
                         "typeof(slot) IN ('integer','null') AS slot_ok",
                         _bounded('raw', MAX_BYTES), _bounded('hash', 64))) +
                         ' FROM ledger WHERE key=?', (key,)).fetchone()
        if row is None: return None
        value = parse(row['raw'])
        if (not row['slot_ok'] or type(row['seq']) is not int or
                (row['slot'] is not None and type(row['slot']) is not int) or
                value['pool_id'] != self.binding['pool_id'] or value['key'] != row['key'] or
                value['version'] != row['seq'] or value['action'] != row['action'] or
                value['slot'] != row['slot'] or _raw_hash(row['raw'].encode()) != row['hash']):
            raise Conflict('original indexed pool event differs')
        return value

    def _member_point(self, db, member_id):
        self._actual()
        if type(member_id) is not str: raise Conflict('bounded indexed pool member ID required')
        identifier(member_id)
        row = db.execute('SELECT ' + ','.join(_bounded(name, limit) for name, limit in
                         (('id', 160), ('project_id', 160), ('store_root', MAX_BYTES), ('key', 160))) +
                         ' FROM members WHERE id=?', (member_id,)).fetchone()
        if row is None: return None
        if any(type(row[name]) is not str for name in row.keys()):
            raise Conflict('bounded pool member projection required')
        value = self._point(db, row['key'])
        if (value is None or value['action'] != 'REGISTER' or value['payload']['member_id'] != row['id'] or
                value['payload']['project_id'] != row['project_id'] or value['payload']['store_root'] != row['store_root']):
            raise Conflict('immutable pool project membership differs')
        return value

    def _state(self, db):
        self._schema(db)
        rows = db.execute("SELECT CASE WHEN typeof(singleton)='integer' THEN singleton END AS singleton,"
                          "CASE WHEN typeof(version)='integer' THEN version END AS version FROM meta LIMIT 2").fetchall()
        if len(rows) != 1 or rows[0]['singleton'] != 1: raise Conflict('fixed pool metadata missing')
        version = rows[0]['version']; count(version)
        tip, total = db.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM ledger').fetchone()
        if version != tip or version != total or version > MAX_EVENTS:
            raise Conflict('complete pool event tip/count differs')
        if version and self._point(db, db.execute('SELECT ' + _bounded('key', 160) +
                ' FROM ledger WHERE seq=?', (version,)).fetchone()[0]) is None:
            raise Conflict('original pool global tip missing')
        heads = db.execute('SELECT slot,' + _bounded('raw', 1024) + ' FROM heads ORDER BY slot LIMIT 4').fetchall()
        if [row['slot'] for row in heads] != list(range(CAPACITY)): raise Conflict('fixed pool three heads required')
        result = []
        for row in heads:
            raw = row['raw']
            if type(raw) is not str or len(raw) > 1024: raise Conflict('bounded current pool head required')
            latest = db.execute('SELECT ' + _bounded('key', 160) + ' FROM ledger INDEXED BY slot_tip WHERE ' +
                                _SLOT_EXPR + '=? ORDER BY seq DESC LIMIT 1', (row['slot'],)).fetchone()
            value = self._point(db, latest['key']) if latest else None
            current = head(value) if value else None
            if canonical(current).decode() != raw:
                raise Conflict('pool head is not original derived indexed head')
            if value is not None:
                lookup = lambda key: self._point(db, key)
                members = lambda key: self._member_point(db, key)
                links(value, lookup, members)
                self._verify_runtime_source(db, value)
                if value['action'] != 'CLAIM':
                    claim = lookup(value['payload']['claim_key']); links(claim, lookup, members)
                if value['action'] in ('FREE', 'FIXTURE_FREE'): links(lookup(value['payload']['prior_key']), lookup, members)
            result.append(current)
        projected_members = db.execute('SELECT COUNT(*) FROM members').fetchone()[0]
        original_members = db.execute('SELECT COUNT(*) FROM ledger INDEXED BY action_tip WHERE ' +
                                      _ACTION_EXPR + "='REGISTER'").fetchone()[0]
        if projected_members != original_members or projected_members > 64:
            raise Conflict('finite application project bound exceeded')
        return version, result

    def _audit(self, db):
        """Finite full replay at protected startup/explicit diagnostic, never hot path."""
        version, heads = self._state(db)
        replay = [None] * CAPACITY; registrations = {}
        for seq in range(1, version + 1):
            row = db.execute('SELECT ' + _bounded('key', 160) + ' FROM ledger WHERE seq=?', (seq,)).fetchone()
            if row is None: raise Conflict('pool full audit event gap')
            value = self._point(db, row[0])
            if value['action'] == 'REGISTER':
                member_id = value['payload']['member_id']
                if member_id in registrations or self._member_point(db, member_id) != value:
                    raise Conflict('pool full audit membership differs')
                registrations[member_id] = value
            else:
                current = replay[value['slot']]
                if current is None and (value['action'] != 'CLAIM' or value['payload']['prior_key'] is not None):
                    raise Conflict('pool full audit initial slot lineage differs')
                links(value, lambda key: self._point(db, key), registrations.get, current=current)
                self._verify_runtime_source(db, value)
                replay[value['slot']] = head(value)
        if replay != heads or len(registrations) != db.execute('SELECT COUNT(*) FROM members').fetchone()[0]:
            raise Conflict('pool full audit projection replay differs')

    def audit(self):
        self._actual()
        with self._transaction(audit=True) as db: self._audit(db)
        return {'verified': True, 'execution_enabled': False}

    def _verify_runtime_source(self, db, value):
        """Bounded historical Project event proof, never a reconstructed cap."""
        from .hybrid_host_pool_ledger import RUNTIME_ACTIONS
        if value['action'] not in RUNTIME_ACTIONS: return
        from .hybrid_budget_ledger import SECTIONS as BUDGET, EVENT, expected_objects, account_key, scope, validate_record
        claim = self._point(db, value['payload']['claim_key'])
        registered = self._member_point(db, claim['payload']['member_id'])
        member_value = registered['payload']; root = Path(member_value['store_root'])
        if self.projects_root not in root.parents: raise Conflict('fixture runtime project outside actual pool')
        with _held_chain(root) as (fds, chain):
            _private(fds[-1])
            if chain != member_value['store_chain']: raise Conflict('fixture runtime project namespace rebound')
        with _held_chain(root / 'runtime') as (fds, chain):
            _private(fds[-1])
            if chain != member_value['runtime_chain']: raise Conflict('fixture runtime runtime namespace rebound')
        if (list(_file_pair(root / 'runtime/research.db')) != member_value['db_identity'] or
                list(_file_pair(root / 'runtime/writer.lock')) != member_value['writer_identity']):
            raise Conflict('fixture runtime original project database rebound')
        store = Store.attach_existing(root, project_id=member_value['project_id'], data_mode='fixture')
        with store.read_connection() as project_db:
            project_db.execute('BEGIN'); read = ReadBudget(project_db, 16*1024**2)
            meta = ObservationReader._meta(project_db)
            if (meta['project_id'],meta['data_mode'],meta['store_epoch']) != (member_value['project_id'],'fixture',member_value['store_epoch']):
                raise Conflict('fixture pool original Project registration differs')
            key = value['payload']['project_fact_key']; fact = read.object(BUDGET[0], key)
            if fact is None or digest(fact) != value['payload']['project_fact_hash']:
                raise Conflict('fixture pool original Project phase source differs')
            validate_record(BUDGET[0], key, fact)
            proof = store._budget_event(project_db, key, _parse=read.parse, _decode=read.decode)
            if proof != ((EVENT, 'hybrid-core', account_key(scope(fact['request'])), fact['accepted_state_version']), expected_objects(fact)):
                raise Conflict('fixture pool original Project event differs')
            runtime = fact['request'].get('fixture_runtime'); origin = runtime['origin'] if runtime else {}
            expected_phase = {'FIXTURE_LINKED':'REGISTER_NO_HANDOFF', 'FIXTURE_HANDOFF_UNKNOWN':'HANDOFF_UNKNOWN',
                'FIXTURE_STOP_REQUESTED':'STOP_REQUESTED', 'FIXTURE_STOPPED':'FIXTURE_SCOPE_STOPPED',
                'FIXTURE_FREE':'FIXTURE_SCOPE_STOPPED'}[value['action']]
            if (runtime is None or runtime['phase'] != expected_phase or
                    origin['lease_id'] != value['payload']['runtime_lease_id'] or
                    origin['pool_claim'] != {'key':claim['key'], 'hash':digest(claim)} or
                    origin['pool_id'] != self.binding['pool_id'] or origin['member_id'] != member_value['member_id'] or
                    (fact['request']['project_id'],fact['request']['data_mode'],fact['request']['store_epoch']) !=
                    (member_value['project_id'],'fixture',member_value['store_epoch'])):
                raise Conflict('fixture pool original Project runtime scope differs')

    def _append(self, db, value):
        validate(value); previous = self._point(db, value['key'])
        if previous is not None:
            if previous != value: raise Conflict('original pool idempotency key reused')
            return True
        version, heads = self._state(db)
        if version != value['version'] - 1 or version >= MAX_EVENTS: raise Conflict('stale host pool CAS')
        lookup = lambda key: self._point(db, key)
        members = lambda key: self._member_point(db, key)
        if value['action'] != 'REGISTER':
            current = heads[value['slot']]
            if value['action'] == 'CLAIM' and current is None and value['payload']['prior_key'] is not None:
                raise Conflict('unowned pool initial prior head')
            if value['action'] != 'CLAIM' and current is None: raise Conflict('original occupied pool head missing')
            links(value, lookup, members, current=current)
        raw = canonical(value).decode()
        db.execute('INSERT INTO ledger VALUES(?,?,?,?,?,?)',
                   (value['version'], value['key'], value['action'], value['slot'], raw, _raw_hash(raw.encode())))
        if value['action'] == 'REGISTER':
            p = value['payload']
            db.execute('INSERT INTO members VALUES(?,?,?,?)', (p['member_id'], p['project_id'], p['store_root'], value['key']))
        else:
            db.execute('UPDATE heads SET raw=? WHERE slot=?', (canonical(head(value)).decode(), value['slot']))
        db.execute('UPDATE meta SET version=? WHERE singleton=1', (value['version'],))
        return False

    def snapshot(self):
        with self._transaction() as db:
            version, heads = self._state(db)
            return {'pool_id': self.binding['pool_id'], 'version': version, 'capacity': CAPACITY,
                    'occupied': sum(h is not None and h['state'] != 'FREE' for h in heads),
                    'heads': heads, 'execution_enabled': False, 'release_enabled': False}

    def _issued_member(self, membership):
        self._actual()
        if type(membership) is not PoolMembership or self._members.get(id(membership)) is not membership:
            raise PermissionError('actual original pool membership required')
        return parse(membership.raw.decode())

    def _verify_member_sources(self, value):
        deadline = time.monotonic() + 5
        member(value); root = Path(value['store_root'])
        if self.projects_root not in root.parents:
            raise Conflict('project cannot select a different application host pool')
        for path, expected in ((root, value['store_chain']), (root / 'runtime', value['runtime_chain'])):
            with _held_chain(path) as (fds, chain):
                _private(fds[-1])
                if chain != expected: raise Conflict('pool original project namespace rebound')
        if (list(_file_pair(root / 'runtime/research.db')) != value['db_identity'] or
                list(_file_pair(root / 'runtime/writer.lock')) != value['writer_identity']):
            raise Conflict('pool original project database/writer identity differs')
        store = Store.attach_existing(root, project_id=value['project_id'], data_mode='fixture')
        with store.read_connection() as db:
            db.execute('BEGIN'); budget = ReadBudget(db, 16*1024**2)
            meta = ObservationReader._meta(db)
            version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
            tip, total = db.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM events').fetchone()
            if ((meta['project_id'], meta['data_mode'], meta['store_epoch']) !=
                    (value['project_id'], 'fixture', value['store_epoch']) or
                    version != meta['source_version'] or version != tip or version != total):
                raise Conflict('pool project registration/event tip differs')
            state = {'version': version}
            for section in SECTIONS:
                rows = db.execute('SELECT ' + _bounded('object_key', 160) +
                                  ' FROM projection WHERE section=? ORDER BY object_key LIMIT 3',
                                  (section,)).fetchall()
                if (len(rows) != 2 or any(type(row[0]) is not str for row in rows) or
                        rows[0][0] != '' or budget.object(section, '') != {}):
                    raise Conflict('pool original installation collections differ')
                state[section] = {rows[1][0]: budget.object(section, rows[1][0])}
            validate_complete(state, (value['project_id'], 'fixture'),
                lambda key: store._installation_event(db, key, _parse=budget.parse, _decode=budget.decode),
                event_summary=store._installation_summary(db, version))
            refs = value['bootstrap']
            intent = state[SECTIONS[0]].get(refs['intent_key']); ready = state[SECTIONS[1]].get(refs['publication_key'])
            if (intent is None or ready is None or digest(intent) != refs['intent_hash'] or
                    digest(ready) != refs['publication_hash'] or digest(intent['expected_seal']) != refs['expected_seal_hash'] or
                    intent['request']['installation_id'] != refs['installation_id'] or ready['release_id'] != refs['release_id'] or
                    intent['binding']['store_root'] != value['store_root'] or
                    intent['binding']['store_root_chain'] != value['store_chain'] or
                    intent['binding']['database_identity'] != value['db_identity']):
                raise Conflict('pool original installation source binding differs')
            if time.monotonic() > deadline: raise Conflict('finite pool project source verification deadline exceeded')

    def register_project(self, installation, material, *, expected_version):
        """Original owner-published bootstrap only, inside this fixed application."""
        self._actual()
        if type(installation) is not FixtureInstallationService or installation._published is not material:
            raise PermissionError('original actual installation publication required')
        installation.builder._slot(material)  # Identity before caller fields/version.
        count(expected_version)
        if self.projects_root not in installation.builder.root.parents:
            raise Conflict('project cannot create/select another application pool')
        with installation._bootstrap_witness(material) as witness:
            payload = {'project_id': installation.project_id, 'data_mode': 'fixture', 'store_epoch': installation.store_epoch,
                'store_root': str(installation.store.root), 'store_chain': directory_chain(installation.store.root),
                'runtime_chain': installation.builder._runtime_chain,
                'db_identity': list(installation.store._existing_identity),
                'writer_identity': list(installation.store._existing_lock_identity), 'bootstrap': json.loads(witness.raw)}
            payload['member_id'] = 'member_' + sha(payload); member(payload)
            key = 'register_' + sha([self.binding['pool_id'], payload['member_id']])
            with self._lock:
                original = self._attempts.get(key)
                value = {'pool_id': self.binding['pool_id'], 'action': 'REGISTER', 'key': key,
                         'version': expected_version + 1, 'slot': None, 'payload': payload}
                if original is None:
                    if len(self._attempts) >= MAX_EVENTS: raise Conflict('finite original pool attempt capacity reached')
                    original = PoolMembership(payload['member_id'], canonical(value))
                    self._attempts[key] = original; self._members[id(original)] = original
                elif type(original) is not PoolMembership or original.raw != canonical(value):
                    raise Conflict('original pool project registration attempt differs')
                with self._transaction(source=installation, witness=witness,
                                       final=lambda _: self._verify_member_sources(payload)) as db:
                    self._append(db, value)
                return original

    def join_registered(self, project_id):
        """New source-only membership after protected restart; NO claim adoption."""
        self._actual(); identifier(project_id)
        with self._transaction() as db:
            row = db.execute('SELECT ' + _bounded('id', 160) + ' FROM members WHERE project_id=?', (project_id,)).fetchone()
            if row is None: raise Conflict('fixed application project is not registered')
            value = self._member_point(db, row['id']); self._verify_member_sources(value['payload'])
            existing = next((m for m in self._members.values() if m.id == row['id']), None)
            if existing is not None: return existing
            if len(self._members) >= 64: raise Conflict('finite original pool membership capacity reached')
            membership = PoolMembership(row['id'], canonical(value)); self._members[id(membership)] = membership
            return membership

    def _member_current(self, db, membership):
        original = self._issued_member(membership)
        value = self._member_point(db, membership.id)
        if value != original: raise Conflict('original durable pool membership missing or changed')
        self._verify_member_sources(value['payload'])
        return value

    def _issued_claim(self, claim):
        self._actual()
        if type(claim) is not PoolClaim or self._claims.get(id(claim)) is not claim:
            raise PermissionError('actual original process-issued pool claim required')
        return parse(claim.raw.decode())

    def _claim_current(self, db, claim, *, deadline=True, closing=False):
        value = self._issued_claim(claim); slot = value['slot']
        if self._point(db, value['key']) != value: raise Conflict('original durable pool claim missing')
        _, heads = self._state(db); current = heads[slot]
        allowed = ({'CLAIM', 'UNKNOWN', 'CLOSE_INTENT', 'FIXTURE_LINKED', 'FIXTURE_HANDOFF_UNKNOWN',
                    'FIXTURE_STOP_REQUESTED', 'FIXTURE_STOPPED'} if closing else
                   {'CLAIM', 'UNKNOWN', 'FIXTURE_LINKED', 'FIXTURE_HANDOFF_UNKNOWN'})
        if current is None or current['claim_key'] != value['key'] or current['state'] not in allowed:
            raise Conflict('pool claim no longer has original occupied head')
        if value['payload']['owner'] != self.process: raise PermissionError('original pool process identity differs')
        self._claim_slots[id(claim)].check()
        if deadline: self._claim_clocks(value)
        return value, current

    @staticmethod
    def _claim_clocks(value):
        p = value['payload']; wall, mono = time.time(), time.monotonic()
        if not p['recorded_wall'] <= wall < p['deadline_wall'] or not p['recorded_mono'] <= mono < p['deadline_mono']:
            raise Conflict('pool claim expired/regressed; occupied exposure is NOT released')

    def claim(self, membership, *, expected_version, request_key, seconds=30):
        original_member = self._issued_member(membership)  # Before parsing request/version.
        count(expected_version); identifier(request_key)
        if type(seconds) is not int or not 1 <= seconds <= 60: raise Conflict('finite original pool claim duration required')
        key = 'claim_' + sha([membership.id, request_key])
        with self._lock:
            original = self._attempts.get(key)
            def final(db):
                self._member_current(db, membership); self._claim_current(db, original)
            with self._transaction(final=final,
                    slot_guard=lambda: self._claim_slots[id(original)].check(),
                    clock=lambda: self._claim_clocks(self._issued_claim(original))) as db:
                self._member_current(db, membership)
                if original is not None:
                    value = self._issued_claim(original)
                    if (value['version'] != expected_version + 1 or
                            value['payload']['member_id'] != original_member['payload']['member_id'] or
                            value['payload']['deadline_mono'] - value['payload']['recorded_mono'] != seconds):
                        raise Conflict('original pool claim request differs')
                else:
                    version, heads = self._state(db)
                    if version != expected_version: raise Conflict('stale host pool claim CAS')
                    if len(self._attempts) >= MAX_EVENTS: raise Conflict('finite original pool attempt capacity reached')
                    number = None
                    for candidate, current in enumerate(heads):
                        if current is not None and current['state'] != 'FREE': continue
                        retained = self._slots.get(candidate)
                        if retained is not None and not retained.closed: continue
                        try: slot = _Slot(self, candidate)
                        except BlockingIOError: continue
                        number = candidate; break
                    if number is None: raise Conflict('shared host model session pool exhausted (3 including descendants)')
                    wall, mono = time.time(), time.monotonic()
                    value = {'pool_id': self.binding['pool_id'], 'action': 'CLAIM', 'key': key,
                        'version': expected_version + 1, 'slot': number,
                        'payload': {'claim_id': 'slot_' + uuid.uuid4().hex, 'member_id': membership.id,
                            'owner': dict(self.process), 'recorded_wall': wall, 'recorded_mono': mono,
                            'deadline_wall': wall + seconds, 'deadline_mono': mono + seconds,
                            'prior_key': heads[number]['key'] if heads[number] is not None else None}}
                    original = PoolClaim(value['payload']['claim_id'], canonical(value))
                    self._attempts[key] = original; self._claims[id(original)] = original
                    self._claim_slots[id(original)] = slot
                self._append(db, value)
            return original

    def check(self, claim):
        self._issued_claim(claim)
        with self._transaction(final=lambda db: self._claim_current(db, claim),
                slot_guard=lambda: self._claim_slots[id(claim)].check(),
                clock=lambda: self._claim_clocks(self._issued_claim(claim))) as db:
            value, current = self._claim_current(db, claim)
            return {'claim_id': claim.id, 'slot': value['slot'], 'state': current['state'],
                    'execution_enabled': False, 'release_enabled': False}

    def _change(self, claim, action, expected_version, extra=None):
        original = self._issued_claim(claim); count(expected_version)
        key = action.lower() + '_' + sha(original['key'])
        def final(db):
            self._claim_current(db, claim, deadline=False, closing=action == 'CLOSE_INTENT')
            registration = self._member_point(db, original['payload']['member_id'])
            if registration is None: raise Conflict('original closing pool member missing')
            self._verify_member_sources(registration['payload'])
        with self._transaction(final=final, slot_guard=lambda: self._claim_slots[id(claim)].check()) as db:
            value, current = self._claim_current(db, claim, deadline=False, closing=action == 'CLOSE_INTENT')
            previous = self._attempts.get(key)
            if previous is None:
                if self._state(db)[0] != expected_version: raise Conflict('stale occupied pool CAS')
                payload = {'claim_key': value['key'], 'claim_hash': digest(value), 'prior_key': current['key']}
                payload.update(extra or {})
                previous = {'pool_id': self.binding['pool_id'], 'action': action, 'key': key,
                            'version': expected_version + 1, 'slot': value['slot'], 'payload': payload}
                self._attempts[key] = previous
            elif previous['version'] != expected_version + 1 or any(previous['payload'].get(k) != v for k, v in (extra or {}).items()):
                raise Conflict('original occupied pool transition request differs')
            self._append(db, previous)
        return previous

    def mark_unknown(self, claim, *, expected_version, reason='OWNER_REQUESTED_UNKNOWN'):
        return self._change(claim, 'UNKNOWN', expected_version, {'reason': reason})

    def request_close_no_handoff(self, claim, *, expected_version):
        self._issued_claim(claim)
        value = self._change(claim, 'CLOSE_INTENT', expected_version)
        closing = self._closings.get(id(claim))
        if closing is None:
            closing = _Closing(claim, canonical(value)); self._closings[id(claim)] = closing
        return closing

    def _fixture_runtime_change(self, owner, lease, action, project_value):
        """Exact original Runtime proof, not a caller stopped/refund boolean."""
        from .hybrid_fixture_runtime import FixtureRuntimeOwner
        from .hybrid_host_pool_ledger import RUNTIME_ACTIONS
        if type(owner) is not FixtureRuntimeOwner or owner.pool is not self or action not in RUNTIME_ACTIONS:
            raise PermissionError('actual original fixed fixture Runtime owner required')
        attempt = owner._issued(lease); claim = self._issued_claim(attempt['claim'])
        owner._verify_pool_link(attempt, action, project_value)
        key = action.lower() + '_' + sha([claim['key'], lease.id])
        def final(db):
            owner._verify_pool_link(attempt, action, project_value)
            self._member_current(db, owner.membership)
            original = self._attempts.get(key)
            stopped_retry = (action == 'FIXTURE_STOPPED' and original is not None and
                             self._state(db)[1][claim['slot']] == head(original) and self._point(db, key) == original)
            if stopped_retry:
                # Durable irreversible runtime tombstone precedes partial FD
                # closure. It cannot reopen handoff; retry only remaining FDs.
                slot = self._claim_slots[id(attempt['claim'])]
                if all(fd is not None for fd in slot.fds): slot.check()
            elif action != 'FIXTURE_FREE':
                self._claim_current(db, attempt['claim'], deadline=False, closing=True)
            else:
                slot = self._claim_slots[id(attempt['claim'])]
                if not slot.closed or any(fd is not None for fd in slot.fds):
                    raise Conflict('fixture Runtime original Pool descriptors not all closed')
        with self._lock, self._transaction(final=final) as db:
            original = self._attempts.get(key)
            if original is None:
                if len(self._attempts) >= MAX_EVENTS:
                    raise Conflict('finite original pool attempt capacity reached')
                version, heads = self._state(db); current = heads[claim['slot']]
                payload = {'claim_key': claim['key'], 'claim_hash': digest(claim), 'prior_key': current['key'],
                           'runtime_lease_id': lease.id, 'project_fact_key': project_value['request']['idempotency_key'],
                           'project_fact_hash': digest(project_value)}
                from .hybrid_budget_ledger import entry_key
                payload['project_fact_key'] = entry_key(project_value['request'])
                if action == 'FIXTURE_FREE': payload['close_witness_hash'] = digest(attempt['pool_closed'])
                original = {'pool_id': self.binding['pool_id'], 'action': action, 'key': key,
                            'version': version + 1, 'slot': claim['slot'], 'payload': payload}
                self._attempts[key] = original
            elif original['payload']['project_fact_hash'] != digest(project_value):
                raise Conflict('fixture Runtime original pool phase source differs')
            self._append(db, original)
        return original

    def close_original(self, closing):
        self._actual()
        if type(closing) is not _Closing or self._closings.get(id(closing.claim)) is not closing:
            raise PermissionError('original durable no-handoff closing capability required')
        with self._transaction() as db:
            value = parse(closing.raw.decode()); claim = self._issued_claim(closing.claim)
            if self._point(db, value['key']) != value or self._state(db)[1][claim['slot']] != head(value):
                raise Conflict('original irrevocable no-handoff tombstone missing')
            slot = self._claim_slots[id(closing.claim)]
            if not slot.closed:
                if all(fd is not None for fd in slot.fds): slot.check()
                slot.close()
            original = self._witnesses.get(id(closing))
            if original is None:
                raw = canonical({'pool_id': self.binding['pool_id'], 'closing_hash': digest(value),
                                 'claim_hash': digest(claim), 'owner': self.process,
                                 'slot_identity': self.binding['slot_chains'][claim['slot']][-1],
                                 'all_original_fds_closed': True, 'handoff_enabled': False})
                original = ClosedSlotWitness(closing, raw); self._witnesses[id(closing)] = original
        return original

    def complete_close(self, witness, *, expected_version):
        self._actual()
        if type(witness) is not ClosedSlotWitness or self._witnesses.get(id(witness.closing)) is not witness:
            raise PermissionError('actual original all-FDs-closed slot witness required')
        claim = self._issued_claim(witness.closing.claim); count(expected_version)
        original_slot = self._claim_slots[id(witness.closing.claim)]
        if not original_slot.closed or any(fd is not None for fd in original_slot.fds):
            raise Conflict('original pool slot physical cleanup incomplete')
        key = 'free_' + sha(claim['key'])
        with self._transaction() as db:
            previous = self._attempts.get(key)
            if previous is None:
                version, heads = self._state(db); closing = parse(witness.closing.raw.decode())
                if version != expected_version or heads[claim['slot']] != head(closing):
                    raise Conflict('stale original closed pool slot CAS')
                previous = {'pool_id': self.binding['pool_id'], 'action': 'FREE', 'key': key,
                    'version': expected_version + 1, 'slot': claim['slot'],
                    'payload': {'claim_key': claim['key'], 'claim_hash': digest(claim), 'prior_key': closing['key'],
                                'close_witness_hash': 'sha256:' + _raw_hash(witness.raw)}}
                self._attempts[key] = previous
            elif previous['version'] != expected_version + 1: raise Conflict('original closed pool request differs')
            duplicate = self._append(db, previous)
        return {'version': previous['version'], 'duplicate': duplicate, 'execution_enabled': False}

    def shutdown(self):
        """Explicit owner cleanup, never refund durable occupied exposure."""
        self._actual()
        with _registry_lock, self._lock:
            errors = []
            for slot in self._slots.values():
                try: slot.close()
                except (OSError, Conflict) as error: errors.append(error)
            if errors: raise Conflict('original pool shutdown cleanup remains uncertain') from errors[0]
            for name, fd in tuple(self._pins.items()):
                try:
                    original = {'pool.db': self.binding['database_identity'], 'writer.lock': self.binding['writer_identity'],
                                'descriptor.json': self.descriptor_identity}[name]
                    info = os.fstat(fd)
                    if [info.st_dev, info.st_ino] != original: raise Conflict('pool shutdown descriptor reused')
                    os.close(fd); del self._pins[name]
                except (OSError, Conflict) as error: errors.append(error)
            if errors: raise Conflict('original pool shutdown descriptor cleanup uncertain') from errors[0]
            self._live = False; _owners.pop(id(self), None)

    def start(self, *args, **kwargs):
        raise PermissionError('host pool claims never authorize runtime handoff')


def _file_pair(path):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise Conflict('original private regular pool file required')
    return info.st_dev, info.st_ino


def _raw_hash(raw):
    return hashlib.sha256(raw).hexdigest()
