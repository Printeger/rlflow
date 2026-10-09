"""Append-only authoritative events; projections never perform side effects."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid


class Conflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_stream(path, chunks):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with tmp.open('xb') as stream:
            for chunk in chunks:stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if tmp.exists():tmp.unlink()


def initial():
    return {"version": 0, "paused": False, "enabled": False, "stages": {}, "tasks": {},
            "sessions": {}, "jobs": {}, "proposals": {}, "approvals": {}, "evidence": {},
            "decisions": {}, "historical": {}, "migration": {}}


_UNLOADED = object()
PREPARATION_READ_BYTES = 64*1024**2
BUDGET_RESERVATION_EXPRESSION="CASE WHEN json_valid(input_versions) THEN json_extract(input_versions,'$.budget_reservation_id') END"
BUDGET_INDEXES={
    'events_type_object_tip':'CREATE INDEX IF NOT EXISTS events_type_object_tip ON events(event_type,object_id,seq DESC)',
    'events_budget_reservation_tip':f'CREATE INDEX IF NOT EXISTS events_budget_reservation_tip ON events(event_type,{BUDGET_RESERVATION_EXPRESSION},seq DESC)'}
PRIVATE_HOT_SECTIONS = frozenset(('tool_sources','tool_receipts','tool_scan',
    'hybrid_goal_contracts','hybrid_goal_heads','hybrid_goal_commands',
    'hybrid_approval_facts','hybrid_approval_revocations','hybrid_approval_heads','hybrid_approval_commands',
    'hybrid_preparation_intents','hybrid_preparation_results',
    'hybrid_controller_facts','hybrid_controller_heads','hybrid_admission_facts',
    'hybrid_budget_entries','hybrid_budget_goal_heads','hybrid_budget_reservation_heads','hybrid_budget_project_heads',
    'hybrid_workspace_facts','hybrid_workspace_heads','hybrid_workspace_claims',
    'hybrid_runtime_installation_intents','hybrid_runtime_installation_publications',
    'hybrid_working_plan_intents','hybrid_working_plan_results','hybrid_cpu_trial_assessments',
    'hybrid_candidate_output_intents','hybrid_candidate_output_results'))


class ObjectMap(dict):
    """A transaction-bound object map: key discovery never loads object bodies."""
    def __init__(self, store, db, section):
        self.store, self.db, self.section = store, db, section
        self.original = {}
        keys = [r[0] for r in db.execute("SELECT object_key FROM projection WHERE section=? AND object_key!=''",(section,))]
        self.original_keys = set(keys)
        super().__init__((k,_UNLOADED) for k in keys)

    def __getitem__(self,key):
        value=super().__getitem__(key)
        if value is _UNLOADED:
            row=self.db.execute("SELECT value FROM projection WHERE section=? AND object_key=?",(self.section,key)).fetchone()
            value=self.store._decode_value(self.db,json.loads(row[0]))
            self.original[key]=canonical(value)
            super().__setitem__(key,value)
        return value

    def __iter__(self): return super().__iter__()
    def get(self,key,default=None): return self[key] if key in self else default
    def values(self): return (self[k] for k in self)
    def items(self): return ((k,self[k]) for k in self)
    def copy(self): return dict(self.items())
    def __deepcopy__(self,memo):
        import copy
        return copy.deepcopy(self.copy(),memo)
    def __eq__(self,other): return self.copy()==other
    def __ne__(self,other): return not self==other
    def __repr__(self): return repr(self.copy())
    def setdefault(self,key,default=None):
        if key not in self: self[key]=default
        return self[key]
    def pop(self,key,*default):
        if key in self:
            value=self[key];del self[key];return value
        if default:return default[0]
        raise KeyError(key)
    def popitem(self):
        if not self:raise KeyError('empty object map')
        key=next(reversed(self));return key,self.pop(key)

    def changes(self):
        puts=[]
        for key in self:
            value=dict.__getitem__(self,key)
            if value is _UNLOADED:continue
            if key in self.original_keys and key not in self.original:
                row=self.db.execute("SELECT value FROM projection WHERE section=? AND object_key=?",(self.section,key)).fetchone()
                self.original[key]=canonical(self.store._decode_value(self.db,json.loads(row[0])))
            if key not in self.original or canonical(value)!=self.original[key]: puts.append([self.section,key,value])
        return puts, [[self.section,k] for k in self.original_keys-self.keys()]


class Store:
    def __init__(self, root, *, allow_rebuild=False):
        self._hybrid_auth_owner = None
        self._hybrid_registry = None
        self._hybrid_authority_service = None
        self._hybrid_draft_auth_owner = None
        self._hybrid_draft_service = None
        self._hybrid_preparation_service = None
        self._hybrid_controller_service = None
        self._hybrid_admission_service = None
        self._hybrid_budget_service = None
        self._hybrid_workspace_service = None
        self._hybrid_installation_service = None
        self._hybrid_working_plan_service = None
        self._hybrid_cpu_assessment_service = None
        self._hybrid_candidate_output_service = None
        self._existing_identity = None
        self.root = Path(root).resolve()
        (self.root / "runtime").mkdir(parents=True, exist_ok=True)
        self.db = self.root / "runtime/research.db"
        with self.lock():
            with self.connect() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                  idempotency_key TEXT UNIQUE NOT NULL, event_type TEXT NOT NULL,
                  object_id TEXT NOT NULL, object_version INTEGER NOT NULL,
                  previous_state_version INTEGER NOT NULL, new_state_version INTEGER NOT NULL,
                  producer TEXT NOT NULL, time REAL NOT NULL, input_versions TEXT NOT NULL,
                  payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
                  BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
                  BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TABLE IF NOT EXISTS projection_meta (
                  singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS projection (
                  section TEXT NOT NULL, object_key TEXT NOT NULL, value TEXT NOT NULL,
                  version INTEGER NOT NULL, object_status TEXT, PRIMARY KEY(section,object_key));
                CREATE TABLE IF NOT EXISTS blobs (digest TEXT PRIMARY KEY, data BLOB NOT NULL);
                CREATE TRIGGER IF NOT EXISTS blobs_no_update BEFORE UPDATE ON blobs
                  BEGIN SELECT RAISE(ABORT, 'immutable blob'); END;
                CREATE TRIGGER IF NOT EXISTS blobs_no_delete BEFORE DELETE ON blobs
                  BEGIN SELECT RAISE(ABORT, 'immutable blob'); END;
                CREATE TABLE IF NOT EXISTS snapshots (
                  version INTEGER PRIMARY KEY, state BLOB NOT NULL, sha256 TEXT NOT NULL);
                """)
                if "object_status" not in {r[1] for r in db.execute("PRAGMA table_info(projection)")}:
                    db.execute("ALTER TABLE projection ADD COLUMN object_status TEXT")
                    for section,key,raw in list(db.execute("SELECT section,object_key,value FROM projection")):
                        value=self._decode_value(db,json.loads(raw))
                        status=value.get("status") if isinstance(value,dict) else None
                        db.execute("UPDATE projection SET object_status=? WHERE section=? AND object_key=?",(status,section,key))
                    db.commit()
                db.execute("CREATE INDEX IF NOT EXISTS projection_status ON projection(section,object_status,object_key)")
                db.execute("CREATE INDEX IF NOT EXISTS projection_markers ON projection(section) WHERE object_key=''")
                db.execute('CREATE INDEX IF NOT EXISTS events_type_tip ON events(event_type,seq DESC)')
                for ddl in BUDGET_INDEXES.values():db.execute(ddl)
                maintenance_new=not db.execute("SELECT 1 FROM sqlite_master WHERE name='snapshot_due'").fetchone()
                db.execute('CREATE TABLE IF NOT EXISTS snapshot_due (singleton INTEGER PRIMARY KEY CHECK(singleton=1),due_version INTEGER NOT NULL,last_complete INTEGER NOT NULL)')
                from .observation import initialize_tables
                initialize_tables(db)
                if db.execute("SELECT version FROM projection_meta").fetchone() is None:
                    db.execute("BEGIN IMMEDIATE")
                    state = self.audit(db)
                    self._replace_projection(db, state)
                    db.commit()
                projected=db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]
                latest=db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
                if projected!=latest and not allow_rebuild:raise Conflict("projection version mismatch; explicit offline rebuild required")
                completed=db.execute('SELECT COALESCE(MAX(version),0) FROM snapshots').fetchone()[0]
                due=projected//1000*1000
                if maintenance_new:db.execute('INSERT INTO snapshot_due VALUES(1,?,?)',(due if due>completed else 0,completed))
                maintenance=db.execute('SELECT due_version,last_complete FROM snapshot_due WHERE singleton=1').fetchone()
                if (maintenance is None or any(type(v) is not int or not 0<=v<=projected for v in maintenance)
                        or maintenance['last_complete'] and not db.execute('SELECT 1 FROM snapshots WHERE version=?',(maintenance['last_complete'],)).fetchone()):
                    raise Conflict('snapshot maintenance metadata requires explicit recovery')

    @classmethod
    def attach_existing(cls, root, *, project_id, data_mode):
        """Attach a migrated, registered store without DDL, recovery or creation.

        SQLite may maintain its WAL/SHM sidecars while reading. This is not an
        immutable filesystem snapshot or protection against the trusted OS owner.
        Business connections cannot recreate a missing/replaced main database.
        """
        from .hybrid_protocol import ID, validate_schema
        from .observation import ObservationReader
        validate_schema(ID, project_id)
        if data_mode not in ('live', 'fixture'):
            raise ValueError('invalid existing store mode')
        store = cls.__new__(cls)
        store.root = Path(root).resolve(strict=True)
        store.db = store.root / 'runtime/research.db'
        for directory in (store.root, store.root / 'runtime'):
            directory_info = directory.lstat()
            if (not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != os.geteuid()
                    or directory_info.st_mode & 0o022):
                raise ValueError('existing store requires protected directories')
        info = store.db.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError('existing store requires a regular database')
        store._existing_identity = (info.st_dev, info.st_ino)
        for name in ('_hybrid_auth_owner', '_hybrid_registry', '_hybrid_authority_service',
                     '_hybrid_draft_auth_owner', '_hybrid_draft_service', '_hybrid_preparation_service',
                     '_hybrid_controller_service', '_hybrid_admission_service', '_hybrid_budget_service',
                     '_hybrid_workspace_service', '_hybrid_installation_service', '_hybrid_working_plan_service',
                     '_hybrid_cpu_assessment_service','_hybrid_candidate_output_service'):
            setattr(store, name, None)
        db = sqlite3.connect(store.db.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                raise Conflict('existing store requires explicit WAL migration')
            required = {
                'events': 'seq event_id idempotency_key event_type object_id object_version previous_state_version new_state_version producer time input_versions payload payload_sha256',
                'projection': 'section object_key value version object_status',
                'projection_meta': 'singleton version', 'blobs': 'digest data',
                'snapshots': 'version state sha256', 'snapshot_due': 'singleton due_version last_complete',
                'observation_meta': 'singleton project_id store_epoch data_mode seq floor source_version paused enabled',
                'observation_events': 'seq event_id source_event_id output_index envelope digest',
                'observation_projection': 'kind object_id status summary',
                'observation_counters': 'kind status count',
            }
            integer_columns = {'seq','object_version','previous_state_version','new_state_version','version',
                               'singleton','due_version','last_complete','floor','source_version','paused','enabled','output_index','count'}
            nullable = {('events','seq'),('projection','object_status'),('projection_meta','singleton'),
                        ('blobs','digest'),('snapshots','version'),('snapshot_due','singleton'),
                        ('observation_meta','singleton'),('observation_events','seq')}
            table_infos = {}
            for table, column_names in required.items():
                kind = db.execute('SELECT type,sql FROM sqlite_master WHERE name=?',(table,)).fetchone()
                columns = column_names.split()
                infos = list(db.execute('PRAGMA table_xinfo(' + table + ')'))
                table_infos[table] = infos
                if (kind is None or kind[0] != 'table' or 'WITHOUT ROWID' in kind[1].upper()
                        or [r[1] for r in infos] != columns
                        or any(r[6] or r[2].upper() != ('INTEGER' if r[1] in integer_columns else
                            'REAL' if r[1]=='time' else 'BLOB' if (table,r[1]) in {('blobs','data'),('snapshots','state')} else 'TEXT')
                            or r[3] != int((table,r[1]) not in nullable) for r in infos)):
                    raise Conflict('existing store requires explicit schema migration')
            keys = {'events':('seq',), 'projection':('section','object_key'),
                    'projection_meta':('singleton',), 'blobs':('digest',),
                    'snapshots':('version',), 'snapshot_due':('singleton',),
                    'observation_meta':('singleton',), 'observation_events':('seq',),
                    'observation_projection':('kind','object_id'), 'observation_counters':('kind','status')}
            for table, key in keys.items():
                actual = tuple(r[1] for r in sorted(table_infos[table], key=lambda r:r[5]) if r[5])
                if actual != key: raise Conflict('existing store primary key mismatch')
                # INTEGER PRIMARY KEY DESC has a separate pk index and is NOT
                # the rowid alias used by core automatic event sequence inserts.
                if len(key)==1 and key[0] in integer_columns and any(r[3]=='pk' for r in db.execute('PRAGMA index_list(' + table + ')')):
                    raise Conflict('existing store integer primary key is not a rowid alias')
            for table, keys in {'events':(('event_id',),('idempotency_key',)),
                                'observation_events':(('event_id',),('source_event_id','output_index'))}.items():
                indexes = [r for r in db.execute('PRAGMA index_list(' + table + ')') if r[2] and not r[4]]
                unique = {tuple(r[2] for r in db.execute('PRAGMA index_info("' + index[1].replace('"','""') + '")')) for index in indexes}
                if not set(keys) <= unique: raise Conflict('existing store uniqueness constraints missing')
            import re
            for name, table, action, message in (
                ('no_update','events','UPDATE','append only'), ('no_delete','events','DELETE','append only'),
                ('blobs_no_update','blobs','UPDATE','immutable blob'), ('blobs_no_delete','blobs','DELETE','immutable blob'),
                ('observation_no_update','observation_events','UPDATE','append only observations'),
                ('observation_no_delete','observation_events','DELETE','append only observations')):
                sql = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()
                expected = f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'{message}'); END"
                normalize = lambda value:re.sub(r'\s+','',value).lower().replace('ifnotexists','')
                if sql is None or normalize(sql[0]) != normalize(expected):
                    raise Conflict('existing store immutable constraints missing')
            meta = ObservationReader._meta(db)
            if (meta['project_id'], meta['data_mode']) != (project_id, data_mode):
                raise Conflict('existing store registration mismatch')
            validate_schema(ID, meta['store_epoch'])
            if (any(type(meta[k]) is not int or not 0 <= meta[k] <= 2**63-1 for k in ('seq','floor','source_version'))
                    or meta['floor'] > meta['seq'] or any(type(meta[k]) is not int or meta[k] not in (0,1) for k in ('paused','enabled'))):
                raise Conflict('existing store observation metadata invalid')
            version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
            latest = db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
            if type(version) is not int or not 0 <= version <= 2**63-1 or version != latest:
                raise Conflict('existing store projection requires explicit recovery')
            maintenance = db.execute('SELECT due_version,last_complete FROM snapshot_due WHERE singleton=1').fetchone()
            if (maintenance is None or any(type(v) is not int or not 0 <= v <= version for v in maintenance)
                    or maintenance['last_complete'] and not db.execute('SELECT 1 FROM snapshots WHERE version=?',(maintenance['last_complete'],)).fetchone()):
                raise Conflict('existing store maintenance requires explicit recovery')
            lock = (store.root / 'runtime/writer.lock').lstat()
            if not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid() or lock.st_mode & 0o022:
                raise Conflict('existing store requires an existing writer lock')
            store._existing_lock_identity = (lock.st_dev, lock.st_ino)
            store._check_existing_identity()
            store.store_epoch = meta['store_epoch']
        finally:
            db.close()
        return store

    def _check_existing_identity(self):
        info = self.db.lstat()
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self._existing_identity:
            raise Conflict('existing database identity changed')

    @contextlib.contextmanager
    def read_connection(self):
        """Read existing state without journal migration or database creation."""
        if self._existing_identity is not None:
            self._check_existing_identity()
        db = sqlite3.connect(self.db.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            if self._existing_identity is not None:
                self._check_existing_identity()
            yield db
        finally:
            db.close()

    def connect(self):
        existing = self._existing_identity is not None
        if existing:
            self._check_existing_identity()
        db = sqlite3.connect(self.db.as_uri() + '?mode=rw' if existing else self.db,
                             uri=existing, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            if existing:
                self._check_existing_identity()
                if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                    raise Conflict('existing store journal mode changed')
            else:
                db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
        except BaseException:
            db.close()
            raise
        return db

    @contextlib.contextmanager
    def lock(self, name="writer", nonblocking=False):
        path = self.root / "runtime" / (name + ".lock")
        if self._existing_identity is not None:
            self._check_existing_identity()
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            info = os.fstat(fd)
            expected_identity = getattr(self, '_existing_lock_identities', {'writer': self._existing_lock_identity}).get(name)
            if not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino) != expected_identity:
                os.close(fd)
                raise Conflict('existing writer lock is not regular')
            f = os.fdopen(fd, 'r+')
        else:
            f = path.open('a')
        with f:
            fcntl.flock(f, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            try:
                if self._existing_identity is not None:
                    self._check_existing_identity()
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def audit(self, db=None):
        if db is None:
            with self.connect() as conn:
                return self.audit(conn)
        state = initial()
        from .contracts import validate_runtime_event, validate_runtime_state
        for row in db.execute("SELECT * FROM events ORDER BY seq"):
            validate_runtime_event(dict(row))
            payload = json.loads(row["payload"])
            if sha(payload) != row["payload_sha256"] or row["previous_state_version"] != state["version"]:
                raise Conflict("event integrity/version mismatch")
            self._apply(state, payload, db, row)
            state["version"] = row["new_state_version"]
        validate_runtime_state(state)
        from .hybrid_goals import validate_complete
        validate_complete(state,self._goal_registration(db),lambda k:self._goal_event(db,k),lambda k:self._goal_source(db,k))
        from .hybrid_authority import validate_complete as authority_complete
        authority_complete(state,self._goal_registration(db),lambda k:self._authority_event(db,k))
        self._preparation_complete(db,state)
        return state

    def _apply(self, state, payload, db, event):
        preparation_decoded=False
        from .hybrid_candidate_output import SECTIONS as output_sections,EVENTS as output_events,validate_transition as output_transition
        if (event['event_type'] in output_events or any(s in output_sections for s,k,v in payload.get('put',[])) or
                any(s in output_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(output_sections)):
            from .hybrid_reads import ReadBudget
            read=ReadBudget(db,PREPARATION_READ_BYTES)
            decoded={**payload,'put':[[s,k,read.decode(v)] for s,k,v in payload.get('put',[])]}
            output_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            from .hybrid_candidate_output import event_inputs
            value=next(v for s,k,v in decoded['put'] if k)
            if event['input_versions']!=canonical(event_inputs(value)).decode():raise Conflict('candidate output canonical inputs differ')
            payload=decoded;preparation_decoded=True
        from .hybrid_cpu_assessment import SECTION as cpu_section, EVENT as cpu_event, validate_transition as cpu_transition
        if (event['event_type']==cpu_event or any(s==cpu_section for s,k,v in payload.get('put',[])) or
                any(s==cpu_section for s,k in payload.get('delete',[])) or cpu_section in payload.get('set',{})):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2)
            decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            cpu_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            from .hybrid_cpu_assessment import event_inputs
            value=next(v for s,k,v in decoded['put'] if k)
            if event['input_versions']!=canonical(event_inputs(value)).decode():
                raise Conflict('CPU appraisal original canonical inputs differ')
            payload=decoded;preparation_decoded=True
        from .hybrid_working_plan import SECTIONS as plan_sections, EVENTS as plan_events, validate_transition as plan_transition
        if (event['event_type'] in plan_events or any(s in plan_sections for s,k,v in payload.get('put',[])) or
                any(s in plan_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(plan_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,PREPARATION_READ_BYTES)
            try:decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('Working plan replay decoding exceeds safe envelope') from None
            plan_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_runtime_installation import SECTIONS as installation_sections, EVENTS as installation_events, validate_transition as installation_transition
        if (event['event_type'] in installation_events or any(s in installation_sections for s,k,v in payload.get('put',[])) or
                any(s in installation_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(installation_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2)
            try:decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('installation replay decoding exceeds safe envelope') from None
            installation_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_workspace import SECTIONS as workspace_sections, EVENT as workspace_event, validate_transition as workspace_transition
        if (event['event_type']==workspace_event or any(s in workspace_sections for s,k,v in payload.get('put',[])) or
                any(s in workspace_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(workspace_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,1024**2)
            try:decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('workspace replay decoding exceeds safe envelope') from None
            workspace_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_budget_ledger import SECTIONS as budget_sections, EVENT as budget_event, validate_transition as budget_transition
        if (event['event_type']==budget_event or any(s in budget_sections for s,k,v in payload.get('put',[])) or
                any(s in budget_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(budget_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2)
            try:decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('budget replay decoding exceeds safe envelope') from None
            budget_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_admission import SECTION as admission_section, EVENT as admission_event, validate_transition as admission_transition
        if (event['event_type']==admission_event or any(s==admission_section for s,k,v in payload.get('put',[])) or
                any(s==admission_section for s,k in payload.get('delete',[])) or admission_section in payload.get('set',{})):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2)
            try:
                decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('admission replay decoding exceeds safe envelope') from None
            admission_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_controller import SECTIONS as controller_sections, EVENT as controller_event, validate_transition as controller_transition
        if (event['event_type']==controller_event or any(s in controller_sections for s,k,v in payload.get('put',[])) or
                any(s in controller_sections for s,k in payload.get('delete',[])) or
                set(payload.get('set',{})) & set(controller_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,1024**2)
            try:
                decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('controller replay decoding exceeds safe envelope') from None
            controller_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_preparation import SECTIONS as preparation_sections, EVENTS as preparation_events, validate_transition as preparation_transition
        if (event['event_type'] in preparation_events or
                any(s in preparation_sections for s,k,v in payload.get('put',[])) or
                any(s in preparation_sections for s,k in payload.get('delete',[])) or
                set(payload.get('set',{})) & set(preparation_sections)):
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,PREPARATION_READ_BYTES)
            try:
                decoded={**payload,'put':[[s,k,budget.decode(v)] for s,k,v in payload.get('put',[])]}
            except (ValueError,TypeError,KeyError,RecursionError):
                raise Conflict('preparation replay decoding exceeds safe envelope') from None
            preparation_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
            payload=decoded;preparation_decoded=True
        from .hybrid_authority import SECTIONS as authority_sections, validate_transition as authority_transition
        if (any(s in authority_sections for s,k,v in payload.get('put',[])) or any(s in authority_sections for s,k in payload.get('delete',[])) or set(payload.get('set',{})) & set(authority_sections)):
            decoded={**payload,'put':[[s,k,self._decode_value(db,v)] for s,k,v in payload.get('put',[])]}
            authority_transition(decoded,lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k),
                event_type=event['event_type'],key=event['idempotency_key'],object_id=event['object_id'],producer=event['producer'],
                version=event['new_state_version'],registration=self._goal_registration(db))
        goal_sections = ('hybrid_goal_contracts','hybrid_goal_heads','hybrid_goal_commands')
        if (any(s in goal_sections for s,k,v in payload.get('put', [])) or any(s in goal_sections for s,k in payload.get('delete', [])) or set(payload.get('set', {})) & set(goal_sections)):
            from .hybrid_goals import validate_transition
            decoded = {**payload, 'put': [[s,k,self._decode_value(db,v)] for s,k,v in payload.get('put', [])]}
            validate_transition(decoded, lambda s,k:({} if s in state else None) if k=='' else state.get(s,{}).get(k), event_type=event['event_type'],
                key=event['idempotency_key'], object_id=event['object_id'], producer=event['producer'], version=event['new_state_version'], registration=self._goal_registration(db))
        if payload.get("format") == 2:
            for section, key, value in sorted(payload["put"], key=lambda row:(row[0],row[1])):
                if not preparation_decoded:value = self._decode_value(db, value)
                if key == "": state[section] = value
                else: state.setdefault(section, {})[key] = value
            for section, key in payload["delete"]:
                if key == "": state.pop(section, None)
                else: state.get(section, {}).pop(key, None)
        else:
            state.update(payload["set"])

    @staticmethod
    def _rows(state):
        for section, value in state.items():
            if section == "version": continue
            # A marker preserves empty and optional collections.
            if isinstance(value, dict):
                yield section, "", {}
                for key, obj in value.items():
                    if not key: raise Conflict("empty object key is reserved")
                    yield section, key, obj
            else: yield section, "", value

    def _replace_projection(self, db, state):
        db.execute("DELETE FROM projection")
        db.executemany("INSERT INTO projection(section,object_key,value,version,object_status) VALUES(?,?,?,?,?)",
                       ((s,k,canonical(self._encode_value(db,v)).decode(),state["version"],v.get("status") if isinstance(v,dict) else None) for s,k,v in self._rows(state)))
        db.execute("INSERT OR REPLACE INTO projection_meta VALUES(1,?)", (state["version"],))

    def replay(self, db=None):
        """Compatibility full-state read; does not replay the event history."""
        if db is None:
            with self.connect() as conn:
                conn.execute("BEGIN")
                return self.replay(conn)
        state = {"version": db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]}
        for row in db.execute("SELECT section,object_key,value FROM projection ORDER BY section,object_key"):
            value = self._decode_value(db, json.loads(row["value"]))
            if row["object_key"] == "": state[row["section"]] = value
            else: state.setdefault(row["section"], {})[row["object_key"]] = value
        return state

    def view(self, db=None):
        """Consistent lazy projection snapshot for scheduling and authorization.

        Each view retains its SQLite read snapshot until the view is discarded.
        Callers must not retain views across a scheduling iteration.
        """
        if db is None:
            db=self.connect();db.execute("BEGIN")
        state={"version":db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]}
        for section,value in db.execute("SELECT section,value FROM projection WHERE object_key=''"):
            if section in PRIVATE_HOT_SECTIONS:continue  # Explicit get/keyset; never expand all ledger keys.
            value=self._decode_value(db,json.loads(value))
            state[section]=ObjectMap(self,db,section) if isinstance(value,dict) else value
        return state

    def control_view(self):
        """Closed consistent scalar early gate; never a dispatch authorization.

        No collection keys/bodies are discovered. The owned read transaction is
        closed before returning plain values; real work still uses full view.
        """
        with contextlib.closing(self.connect()) as db:
            db.execute('BEGIN')
            row=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()
            if row is None or type(row[0]) is not int or row[0]<0:raise Conflict('invalid control version')
            state={'version':row[0]}
            for section,raw in db.execute("SELECT section,value FROM projection WHERE object_key='' AND section IN ('paused','enabled','autonomous_tasks')"):
                state[section]=self._decode_value(db,json.loads(raw))
            for field in ('paused','enabled'):
                if type(state.get(field)) is not bool:raise Conflict('invalid control '+field)
            autonomous=state.setdefault('autonomous_tasks',[])
            if type(autonomous) is not list or any(type(key) is not str for key in autonomous):
                raise Conflict('invalid control autonomous_tasks')
            return state

    def get(self, section, key="", default=None):
        """Indexed object query, with no unrelated objects or event payloads."""
        with self.connect() as db:
            row = db.execute("SELECT value FROM projection WHERE section=? AND object_key=?", (section,key)).fetchone()
            return self._decode_value(db,json.loads(row[0])) if row else default

    def objects(self, section, statuses=None, *, pending_event_suffix=None):
        query="SELECT object_key,value FROM projection WHERE section=? AND object_key!=''"
        args=[section]
        if statuses is not None:
            if not statuses:return []
            query+=" AND object_status IN ("+",".join("?" for _ in statuses)+")"
            args.extend(statuses)
        if pending_event_suffix:
            query+=" AND NOT EXISTS (SELECT 1 FROM events WHERE idempotency_key=projection.object_key || ?)"
            args.append(pending_event_suffix)
        with self.connect() as db:
            db.execute("BEGIN")
            return [(key,self._decode_value(db,json.loads(value))) for key,value in db.execute(query,args)]

    def summaries(self, section, fields, db=None):
        """Read selected object fields without expanding unrelated immutable blobs."""
        if db is None:
            with self.connect() as connection:
                connection.execute("BEGIN")
                return self.summaries(section,fields,connection)
        def node(value):
            if isinstance(value,dict) and "$rlflow_blob" in value:
                row=db.execute("SELECT data FROM blobs WHERE digest=?",(value["$rlflow_blob"],)).fetchone()
                if row is None or hashlib.sha256(row[0]).hexdigest()!=value["$rlflow_blob"]:raise Conflict("summary blob integrity mismatch")
                return json.loads(row[0])
            return value
        result={}
        for key,raw in db.execute("SELECT object_key,value FROM projection WHERE section=? AND object_key!=''",(section,)):
            encoded=json.loads(raw);summary={}
            for field in fields:
                value=encoded
                for part in field.split('.'):
                    value=node(value)
                    if not isinstance(value,dict) or part not in value:break
                    value=value[part]
                else:summary[field]=self._decode_value(db,value)
            result[key]=summary
        return result

    def latest_release(self):
        records=self.summaries('releases',('published_sequence','path'))
        candidates=[(r['published_sequence'],rid,r['path']) for rid,r in records.items() if r.get('published_sequence')]
        if not candidates:return None
        _,rid,path=max(candidates)
        return {'id':rid,'path':path}

    def version(self):
        with self.connect() as db:
            return db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]

    def _encode_value(self, db, value):
        literal=isinstance(value,dict) and "$rlflow_blob" in value
        if not literal:
            if isinstance(value,dict):value={k:self._encode_value(db,v) for k,v in value.items()}
            elif isinstance(value,list):value=[self._encode_value(db,v) for v in value]
        raw=canonical(value)
        if len(raw)<65536 and not literal:return value
        digest=hashlib.sha256(raw).hexdigest()
        db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)",(digest,raw))
        return {"$rlflow_blob":digest,**({"literal":True} if literal else {})}

    def _decode_value(self, db, value):
        if isinstance(value,dict) and set(value) in ({"$rlflow_blob"},{"$rlflow_blob","literal"}):
            row=db.execute("SELECT data FROM blobs WHERE digest=?",(value["$rlflow_blob"],)).fetchone()
            if row is None or hashlib.sha256(row[0]).hexdigest()!=value["$rlflow_blob"]:
                raise Conflict("immutable blob missing or corrupt")
            literal=value.get("literal",False);value=json.loads(row[0])
            if literal:return value
        if isinstance(value,dict):return {k:self._decode_value(db,v) for k,v in value.items()}
        if isinstance(value,list):return [self._decode_value(db,v) for v in value]
        return value

    def _commit(self, db, event_type, key, payload, previous, object_id, producer, inputs, *, _authorization=None):
        ver = previous + 1
        from .hybrid_candidate_output import SECTIONS as output_sections,EVENTS as output_events,validate_transition as output_transition
        if (event_type in output_events or any(s in output_sections for s,k,v in payload['put']) or
                any(s in output_sections for s,k in payload['delete'])):
            service=self._check_candidate_output_guard(db,_authorization)
            output_transition(payload,_authorization.lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_cpu_assessment import SECTION as cpu_section, EVENT as cpu_event, validate_transition as cpu_transition
        if (event_type==cpu_event or any(s==cpu_section for s,k,v in payload['put']) or
                any(s==cpu_section for s,k in payload['delete'])):
            service=self._check_cpu_assessment_guard(db,_authorization)
            cpu_transition(payload,_authorization.lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_working_plan import SECTIONS as plan_sections, EVENTS as plan_events, validate_transition as plan_transition
        if (event_type in plan_events or any(s in plan_sections for s,k,v in payload['put']) or
                any(s in plan_sections for s,k in payload['delete'])):
            service=self._check_working_plan_guard(db,_authorization)
            plan_transition(payload,_authorization.lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_runtime_installation import SECTIONS as installation_sections, EVENTS as installation_events, validate_transition as installation_transition
        if (event_type in installation_events or any(s in installation_sections for s,k,v in payload['put']) or
                any(s in installation_sections for s,k in payload['delete'])):
            service=self._check_installation_guard(db,_authorization)
            def installation_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.read.object(section,objkey)
            installation_transition(payload,installation_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_workspace import SECTIONS as workspace_sections, EVENT as workspace_event, validate_transition as workspace_transition
        if (event_type==workspace_event or any(s in workspace_sections for s,k,v in payload['put']) or
                any(s in workspace_sections for s,k in payload['delete'])):
            service=self._check_workspace_guard(db,_authorization)
            def workspace_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.lookup(section,objkey)
            workspace_transition(payload,workspace_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_budget_ledger import SECTIONS as budget_sections, EVENT as budget_event, validate_transition as budget_transition
        if (event_type==budget_event or any(s in budget_sections for s,k,v in payload['put']) or
                any(s in budget_sections for s,k in payload['delete'])):
            service=self._check_budget_guard(db,_authorization)
            def budget_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.budget.object(section,objkey)
            budget_transition(payload,budget_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,inputs,_authorization)
        from .hybrid_admission import SECTION as admission_section, EVENT as admission_event, validate_transition as admission_transition
        if (event_type==admission_event or any(s==admission_section for s,k,v in payload['put']) or
                any(s==admission_section for s,k in payload['delete'])):
            service=self._check_admission_guard(db,_authorization)
            def admission_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.budget.object(section,objkey)
            admission_transition(payload,admission_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,_authorization)
        from .hybrid_controller import SECTIONS as controller_sections, EVENT as controller_event, validate_transition as controller_transition
        if (event_type==controller_event or any(s in controller_sections for s,k,v in payload['put']) or
                any(s in controller_sections for s,k in payload['delete'])):
            service=self._check_controller_guard(db,_authorization)
            def controller_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.budget.object(section,objkey)
            controller_transition(payload,controller_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,_authorization)
        from .hybrid_preparation import SECTIONS as preparation_sections, EVENTS as preparation_events, validate_transition as preparation_transition
        if (event_type in preparation_events or any(s in preparation_sections for s,k,v in payload['put']) or
                any(s in preparation_sections for s,k in payload['delete'])):
            service=self._check_preparation_guard(db,_authorization)
            def preparation_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                return _authorization.budget.object(section,objkey)
            preparation_transition(payload,preparation_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            service.check_live_write(db,payload,_authorization)
        from .hybrid_authority import SECTIONS as authority_sections, validate_transition as authority_transition
        if any(s in authority_sections for s,k,v in payload['put']) or any(s in authority_sections for s,k in payload['delete']):
            access=self._check_hybrid_guard(db,_authorization)
            def authority_lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                row=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,objkey)).fetchone()
                return self._decode_value(db,json.loads(row[0])) if row else None
            authority_transition(payload,authority_lookup,event_type=event_type,key=key,object_id=object_id,
                producer=producer,version=ver,registration=self._goal_registration(db))
            receipt=next(v for s,k,v in payload['put'] if s==authority_sections[3] and k)
            request=receipt['request']
            if request['actor']!={'id':access.principal.id,'kind':'human'}:raise Conflict('authority actor differs from actual session')
            live_fact=next(v for s,k,v in payload['put'] if s==receipt['fact_section'] and k==receipt['fact_key'])
            self._hybrid_authority_service.check_live_write(request,live_fact,_authorization)
            if request['action']=='approve':
                confirm=request['confirmation']
                epoch=db.execute('SELECT store_epoch FROM observation_meta WHERE singleton=1').fetchone()[0]
                fact=next(v for s,k,v in payload['put'] if s==authority_sections[0] and k)
                if confirm['store_epoch']!=epoch or self._hybrid_registry.config_hash!=confirm['config_hash']:
                    raise Conflict('confirmation epoch or registry changed')
                if json.loads(self._hybrid_registry._raw)!=fact['registry_witness']:raise Conflict('registry witness differs from protected owner')
        from .hybrid_goals import validate_transition, SECTIONS as goal_sections
        if any(s in goal_sections for s,k,v in payload['put']) or any(s in goal_sections for s,k in payload['delete']):
            def lookup(section,objkey):
                if objkey=='':return {} if db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
                row=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,objkey)).fetchone()
                return self._decode_value(db,json.loads(row[0])) if row else None
            validate_transition(payload,lookup,event_type=event_type,key=key,object_id=object_id,producer=producer,version=ver,registration=self._goal_registration(db))
            if self._hybrid_draft_auth_owner is not None:
                access=self._check_draft_guard(db,_authorization,object_id)
                receipt=next(v for s,k,v in payload['put'] if s==goal_sections[2] and k)
                if receipt['request']['actor']!={'id':access.principal.id,'kind':access.principal.kind}:
                    raise Conflict('draft actor differs from actual session')
                if 'expected_state_version' not in receipt['request']:raise Conflict('bound draft requires global expected version')
        source_event_id = uuid.uuid4().hex
        timestamp = time.time()
        # Preserve the unencoded patch for the small allowlisted public bridge.
        observation_payload = payload
        statuses={(s,k):v.get("status") if isinstance(v,dict) else None for s,k,v in payload["put"]}
        payload = {**payload, "put": [[s,k,self._encode_value(db,v)] for s,k,v in payload["put"]]}
        db.execute("INSERT INTO events(event_id,idempotency_key,event_type,object_id,object_version,previous_state_version,new_state_version,producer,time,input_versions,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (source_event_id,key,event_type,object_id,ver,previous,ver,producer,timestamp,
                    canonical(inputs or {}).decode(),canonical(payload).decode(),sha(payload)))
        for section, objkey in payload["delete"]:
            db.execute("DELETE FROM projection WHERE section=? AND object_key=?", (section,objkey))
        for section, objkey, value in payload["put"]:
            db.execute("INSERT INTO projection(section,object_key,value,version,object_status) VALUES(?,?,?,?,?) ON CONFLICT(section,object_key) DO UPDATE SET value=excluded.value,version=excluded.version,object_status=excluded.object_status",
                       (section,objkey,canonical(value).decode(),ver,statuses[(section,objkey)]))
        db.execute("UPDATE projection_meta SET version=? WHERE singleton=1", (ver,))
        from .observation import commit as observe
        observe(db,source_event_id,event_type,observation_payload,ver,timestamp)
        if ver % 1000 == 0:
            if db.execute('UPDATE snapshot_due SET due_version=MAX(due_version,?) WHERE singleton=1',(ver,)).rowcount!=1:
                raise Conflict('snapshot maintenance metadata missing')
        return ver

    @staticmethod
    def _existing(db, key, event_type, object_id):
        row = db.execute("SELECT event_type,object_id FROM events WHERE idempotency_key=?", (key,)).fetchone()
        if row and (row["event_type"] != event_type or row["object_id"] != object_id):
            raise Conflict("idempotency key reused for different operation")
        return row is not None

    @staticmethod
    def _goal_registration(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='observation_meta'").fetchone():return None
        row=db.execute('SELECT project_id,data_mode FROM observation_meta WHERE singleton=1').fetchone()
        return tuple(row) if row else None

    def bind_hybrid_authority(self, auth, registry, service):
        """Protected startup binding, never an HTTP/agent operation."""
        from .web_auth import AuthStore
        from .hybrid_registry import Registry
        from .hybrid_authority import ApprovalService
        if type(auth) is not AuthStore or type(registry) is not Registry or type(service) is not ApprovalService:raise TypeError('invalid authority owner')
        with self.lock():
            if self._hybrid_draft_auth_owner is not None and self._hybrid_draft_auth_owner is not auth:
                raise Conflict('draft and approval owners must share AuthStore')
            if self._hybrid_auth_owner is not None and (self._hybrid_auth_owner is not auth or self._hybrid_registry is not registry or self._hybrid_authority_service is not service):
                raise Conflict('authority owner cannot be rebound in-place')
            self._hybrid_auth_owner,self._hybrid_registry=auth,registry
            self._hybrid_authority_service=service

    def bind_hybrid_drafts(self, auth, service):
        """Opt-in protected startup binding; old internal drafts stay compatible."""
        from .web_auth import AuthStore
        from .hybrid_drafts import DraftService
        if type(auth) is not AuthStore or type(service) is not DraftService:raise TypeError('invalid draft owner')
        with self.lock():
            if self._hybrid_auth_owner is not None and self._hybrid_auth_owner is not auth:
                raise Conflict('draft and approval owners must share AuthStore')
            if self._hybrid_draft_auth_owner is not None and (self._hybrid_draft_auth_owner is not auth or self._hybrid_draft_service is not service):
                raise Conflict('draft owner cannot be rebound in-place')
            self._hybrid_draft_auth_owner,self._hybrid_draft_service=auth,service

    def _check_draft_guard(self, db, guard, request_hash):
        registration=self._goal_registration(db);service=self._hybrid_draft_service
        if (self._hybrid_draft_auth_owner is None or service is None
                or registration!=(service.project_id,service.data_mode)):
            raise PermissionError('protected registered draft owner required')
        meta=db.execute('SELECT store_epoch FROM observation_meta WHERE singleton=1').fetchone()
        if meta is None or meta['store_epoch']!=service.store_epoch:raise Conflict('draft service epoch changed')
        access=self._hybrid_draft_auth_owner.check_operator_guard(guard,project_id=registration[0])
        service.check_live_request(request_hash,guard)
        return access

    def _check_hybrid_guard(self, db, guard):
        registration=self._goal_registration(db)
        if self._hybrid_auth_owner is None or registration is None:raise PermissionError('protected authority owner required')
        return self._hybrid_auth_owner.check_approval_guard(guard,project_id=registration[0])

    def bind_hybrid_preparation(self, service):
        from .hybrid_preparation_service import PreparationService
        if type(service) is not PreparationService or service.store is not self:
            raise TypeError('invalid preparation owner')
        with self.lock():
            if self._hybrid_preparation_service not in (None,service):
                raise Conflict('preparation owner cannot be rebound in-place')
            self._hybrid_preparation_service=service

    def _check_preparation_guard(self, db, guard):
        service=self._hybrid_preparation_service
        if service is None:raise PermissionError('protected preparation owner required')
        service.check_guard(db,guard)
        return service

    def _preparation_complete(self, db, state):
        from .hybrid_candidate_output import validate_complete as output_complete
        output_complete(state,self._goal_registration(db),lambda k:self._candidate_output_event(db,k),
            lambda s,v:self._candidate_output_summary(db,s,v))
        from .hybrid_cpu_assessment import validate_complete as cpu_complete
        cpu_complete(state,self._goal_registration(db),lambda k:self._cpu_assessment_event(db,k),
            self._cpu_assessment_summary(db,state['version']))
        from .hybrid_preparation import validate_complete
        validate_complete(state,self._goal_registration(db),lambda k:self._preparation_event(db,k))
        from .hybrid_controller import validate_complete as controller_complete
        controller_complete(state,self._goal_registration(db),lambda k:self._controller_event(db,k),
                            event_tip=self._controller_tip(db,state['version']))
        from .hybrid_admission import validate_complete as admission_complete
        admission_complete(state,self._goal_registration(db),lambda k:self._admission_event(db,k),
                           event_summary=self._admission_summary(db,state['version']))
        from .hybrid_budget_ledger import validate_complete as budget_complete
        budget_complete(state,self._goal_registration(db),lambda k:self._budget_event(db,k),
                        event_summary=self._budget_summary(db,state['version']))
        from .hybrid_workspace import validate_complete as workspace_complete
        workspace_complete(state,self._goal_registration(db),lambda k:self._workspace_event(db,k),
                           event_summary=self._workspace_summary(db,state['version']))
        from .hybrid_runtime_installation import validate_complete as installation_complete
        installation_complete(state,self._goal_registration(db),lambda k:self._installation_event(db,k),
                              event_summary=self._installation_summary(db,state['version']))
        from .hybrid_working_plan import validate_complete as working_plan_complete
        working_plan_complete(state,self._goal_registration(db),lambda k:self._working_plan_event(db,k),
                              event_summary=self._working_plan_summary(db,state['version']))

    def bind_hybrid_working_plan(self,service):
        from .hybrid_working_plan_service import WorkingPlanService
        if type(service) is not WorkingPlanService or service.store is not self:
            raise TypeError('fixed original Working plan owner required')
        with self.lock(),self.read_connection() as db:
            self._require_budget_indices(db)
            if self._hybrid_working_plan_service not in (None,service):raise Conflict('Working plan owner cannot be rebound')
            self._hybrid_working_plan_service=service

    def _check_working_plan_guard(self,db,guard):
        service=self._hybrid_working_plan_service
        if service is None:raise PermissionError('protected actual Working plan owner required')
        service.check_guard(db,guard)
        return service

    def _working_plan_summary(self,db,version):
        from .hybrid_working_plan import EVENTS
        row=db.execute('SELECT CASE WHEN length(CAST(idempotency_key AS BLOB))<=128 THEN idempotency_key END,new_state_version FROM events WHERE event_type IN (?,?) AND seq<=? ORDER BY seq DESC LIMIT 1',(*EVENTS,version)).fetchone()
        count=db.execute('SELECT COUNT(*) FROM events WHERE event_type IN (?,?) AND seq<=?',(*EVENTS,version)).fetchone()[0]
        return tuple(row) if row is not None else None,count

    def _working_plan_event(self,db,key,*,max_bytes=17*1024**2,_parse=None,_decode=None):
        """Indexed complete original metadata/put/marker/inputs, bounded decode."""
        from .hybrid_working_plan import SECTIONS,EVENTS,validate_record,expected_objects,event_inputs
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            read=ReadBudget(db,PREPARATION_READ_BYTES);_parse,_decode=read.parse,read.decode
        row=db.execute('SELECT seq,previous_state_version,new_state_version,object_version,CASE WHEN length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN length(CAST(object_id AS BLOB))<=160 THEN object_id END AS object_id,CASE WHEN length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None or row['event_type'] not in EVENTS:raise Conflict('Working plan original source unavailable or exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256'] or canonical(payload).decode()!=row['payload']:
            raise Conflict('Working plan original source integrity differs')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload['format']) is not int or payload['format']!=2 or type(payload['put']) is not list or
                payload['delete']!=[] or payload['details'] is not None or not 1<=len(payload['put'])<=2):
            raise Conflict('Working plan original source shape differs')
        section=SECTIONS[EVENTS.index(row['event_type'])];objects={};markers={}
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or item[0]!=section or type(item[1]) is not str:
                raise Conflict('Working plan original extra descriptor')
            _,objkey,encoded=item;value=_decode(encoded)
            if objkey:
                if objkey in objects:raise Conflict('Working plan original duplicate descriptor')
                validate_record(section,objkey,value);objects[objkey]=value
            else:
                if section in markers or value!={}:raise Conflict('Working plan original marker differs')
                markers[section]=value
        prior=db.execute('SELECT 1 FROM events WHERE event_type=? AND seq<? LIMIT 1',(row['event_type'],row['seq'])).fetchone()
        if set(objects)!={key} or markers!=({section:{}} if prior is None else {}):
            raise Conflict('Working plan original single fact/first marker differs')
        value=objects[key];version=value['accepted_state_version']
        if (row['seq']!=version or row['new_state_version']!=version or row['previous_state_version']!=version-1 or
                row['object_version']!=version or row['object_id']!=value['request']['plan_id'] or
                row['producer']!='hybrid-core' or row['input_versions']!=canonical(event_inputs(value)).decode()):
            raise Conflict('Working plan original metadata or canonical whole-fact inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],version),expected_objects(section,key,value),event_inputs(value))

    def bind_hybrid_installation(self, service):
        from .hybrid_installation_service import FixtureInstallationService
        if type(service) is not FixtureInstallationService or service.store is not self:
            raise TypeError('invalid actual fixture installation owner')
        with self.lock(),self.read_connection() as db:
            self._require_budget_indices(db)
            if self._hybrid_installation_service not in (None,service):
                raise Conflict('fixture installation owner cannot be rebound in-place')
            self._hybrid_installation_service=service

    def _check_installation_guard(self, db, guard):
        service=self._hybrid_installation_service
        if service is None:raise PermissionError('protected fixture installation owner required')
        service.check_guard(db,guard)
        return service

    def _installation_summary(self, db, version):
        from .hybrid_runtime_installation import EVENTS
        row=db.execute('SELECT CASE WHEN length(CAST(idempotency_key AS BLOB))<=128 THEN idempotency_key END,new_state_version FROM events WHERE event_type IN (?,?) AND seq<=? ORDER BY seq DESC LIMIT 1',(*EVENTS,version)).fetchone()
        count=db.execute('SELECT COUNT(*) FROM events WHERE event_type IN (?,?) AND seq<=?',(*EVENTS,version)).fetchone()[0]
        return tuple(row) if row is not None else None,count

    def _installation_event(self, db, key, *, max_bytes=1024**2, _parse=None, _decode=None):
        from .hybrid_runtime_installation import SECTIONS,EVENTS,validate_record,expected_objects,event_inputs
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            read=ReadBudget(db,4*1024**2);_parse,_decode=read.parse,read.decode
        row=db.execute('SELECT seq,previous_state_version,new_state_version,object_version,CASE WHEN length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN length(CAST(object_id AS BLOB))<=128 THEN object_id END AS object_id,CASE WHEN length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None or row['event_type'] not in EVENTS:
            raise Conflict('installation original source unavailable or exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256'] or canonical(payload).decode()!=row['payload']:
            raise Conflict('installation original source integrity differs')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload['format']) is not int or payload['format']!=2 or payload['details'] is not None or
                type(payload['put']) is not list or payload['delete']!=[] or len(payload['put'])!=2):
            raise Conflict('installation original source shape differs')
        section=SECTIONS[EVENTS.index(row['event_type'])];objects={};markers={}
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or item[0]!=section or type(item[1]) is not str:
                raise Conflict('installation original extra object descriptor')
            _,objkey,encoded=item;value=_decode(encoded)
            if objkey:
                if objkey in objects:raise Conflict('installation original duplicate object')
                validate_record(section,objkey,value);objects[objkey]=value
            else:
                if section in markers or value!={}:raise Conflict('installation original marker differs')
                markers[section]=value
        if set(objects)!={key} or markers!={section:{}}:
            raise Conflict('installation original single fact/marker differs')
        value=objects[key];version=value['accepted_state_version']
        if (row['seq']!=version or row['new_state_version']!=version or row['previous_state_version']!=version-1 or
                row['object_version']!=version or row['object_id']!=value['request']['installation_id'] or
                row['producer']!='hybrid-installer' or row['input_versions']!=canonical(event_inputs(value)).decode()):
            raise Conflict('installation original event metadata or canonical inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),
                expected_objects(section,key,value),event_inputs(value))

    def _require_budget_indices(self, db):
        """Enabled owner requirement; RO attach never installs missing indexes."""
        for name,ddl in BUDGET_INDEXES.items():
            row=db.execute("SELECT type,sql FROM sqlite_master WHERE name=?",(name,)).fetchone()
            # SQLite stores this generated DDL without IF NOT EXISTS. Do not
            # normalize quoted JSON paths: case and inner spaces are semantic.
            if row is None or row['type']!='index' or row['sql']!=ddl.replace(' IF NOT EXISTS',''):
                raise Conflict('budget indexes require explicit schema upgrade')

    def bind_hybrid_budget(self, service):
        from .hybrid_budget_service import BudgetService
        if type(service) is not BudgetService or service.store is not self:raise TypeError('invalid budget owner')
        with self.lock(),self.read_connection() as db:
            self._require_budget_indices(db)
            if self._hybrid_budget_service not in (None,service):raise Conflict('budget owner cannot be rebound in-place')
            self._hybrid_budget_service=service

    def bind_hybrid_workspace(self, service):
        from .hybrid_workspace_service import WorkspaceService
        if type(service) is not WorkspaceService or service.store is not self:raise TypeError('invalid workspace owner')
        with self.lock(),self.read_connection() as db:
            self._require_budget_indices(db)
            if self._hybrid_workspace_service not in (None,service):raise Conflict('workspace owner cannot be rebound in-place')
            self._hybrid_workspace_service=service

    def _check_workspace_guard(self, db, guard):
        service=self._hybrid_workspace_service
        if service is None:raise PermissionError('protected workspace owner required')
        service.check_guard(db,guard)
        return service

    def _workspace_tip(self, db, version, *, reservation_id=None):
        from .hybrid_workspace import EVENT
        sql='SELECT CASE WHEN length(CAST(idempotency_key AS BLOB))<=128 THEN idempotency_key END AS idempotency_key,new_state_version FROM events WHERE event_type=? AND seq<=?'
        values=[EVENT,version]
        if reservation_id is not None:sql+=' AND object_id=?';values.append(reservation_id)
        row=db.execute(sql+' ORDER BY seq DESC LIMIT 1',values).fetchone()
        return tuple(row) if row is not None else None

    def _workspace_summary(self, db, version):
        from .hybrid_workspace import EVENT
        return self._workspace_tip(db,version),db.execute('SELECT COUNT(*) FROM events WHERE event_type=? AND seq<=?',(EVENT,version)).fetchone()[0]

    def _workspace_event(self, db, key, *, max_bytes=1024**2, _parse=None, _decode=None):
        from .hybrid_workspace import (SECTIONS,validate_record,head,head_key,claim,claim_key,event_inputs,expected_objects)
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2);_parse,_decode=budget.parse,budget.decode
        row=db.execute('SELECT CASE WHEN length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN length(CAST(object_id AS BLOB))<=128 THEN object_id END AS object_id,new_state_version,CASE WHEN length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('workspace original source exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('workspace original source integrity differs')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload['format']) is not int or payload['format']!=2 or payload['details'] is not None or
                type(payload['put']) is not list or type(payload['delete']) is not list or payload['delete']):
            raise Conflict('workspace original source shape differs')
        objects={};markers={}
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or not all(type(v) is str for v in item[:2]):
                raise Conflict('workspace original descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in objects or not objkey and section in markers:
                raise Conflict('workspace original extra or duplicate object')
            value=_decode(value)
            if not objkey:
                if value!={}:raise Conflict('workspace original marker differs')
                markers[section]=value
            else:validate_record(section,objkey,value);objects[(section,objkey)]=value
        facts=[(k,v) for (s,k),v in objects.items() if s==SECTIONS[0]]
        if len(facts)!=1 or facts[0][0]!=key:raise Conflict('workspace original single fact differs')
        value=facts[0][1];request=value['request'];expected={(SECTIONS[0],key):value,(SECTIONS[1],head_key(request)):head(value)}
        if request['operation']=='acquire':expected[(SECTIONS[2],claim_key(request))]=claim(value)
        previous=self._workspace_tip(db,row['new_state_version']-1)
        if objects!=expected or markers!=({s:{} for s in SECTIONS} if previous is None else {}):
            raise Conflict('workspace original derived objects/initial markers differ')
        if row['input_versions']!=canonical(event_inputs(value)).decode():
            raise Conflict('workspace original canonical inputs differ')
        if _decode(_parse(row['input_versions'].encode()))!=event_inputs(value):
            raise Conflict('workspace original decoded inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),expected_objects(value))

    def _check_budget_guard(self, db, guard):
        service=self._hybrid_budget_service
        if service is None:raise PermissionError('protected budget owner required')
        service.check_guard(db,guard)
        return service

    def _budget_tip(self, db, version, *, goal_account_key=None, reservation_id=None):
        from .hybrid_budget_ledger import EVENT
        if goal_account_key is not None and reservation_id is not None:raise ValueError('one budget lookup scope required')
        sql='SELECT CASE WHEN length(CAST(idempotency_key AS BLOB))<=128 THEN idempotency_key END AS idempotency_key,new_state_version FROM events WHERE event_type=? AND seq<=?'
        values=[EVENT,version]
        if goal_account_key is not None:sql+=' AND object_id=?';values.append(goal_account_key)
        if reservation_id is not None:sql+=f' AND {BUDGET_RESERVATION_EXPRESSION}=?';values.append(reservation_id)
        row=db.execute(sql+' ORDER BY seq DESC LIMIT 1',values).fetchone()
        return tuple(row) if row is not None else None

    def _budget_summary(self, db, version):
        from .hybrid_budget_ledger import EVENT
        return self._budget_tip(db,version),db.execute('SELECT COUNT(*) FROM events WHERE event_type=? AND seq<=?',(EVENT,version)).fetchone()[0]

    def _budget_event(self, db, key, *, max_bytes=1024*1024, _parse=None, _decode=None):
        from .hybrid_budget_ledger import (SECTIONS,validate_record,derived_heads,event_inputs,expected_objects)
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2);_parse,_decode=budget.parse,budget.decode
        row=db.execute('SELECT CASE WHEN length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN length(CAST(object_id AS BLOB))<=128 THEN object_id END AS object_id,new_state_version,CASE WHEN length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('budget original source exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('budget original source integrity differs')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload['format']) is not int or payload['format']!=2 or payload['details'] is not None or
                type(payload['put']) is not list or type(payload['delete']) is not list or payload['delete']):
            raise Conflict('budget original source shape differs')
        objects={};markers={}
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or not all(type(v) is str for v in item[:2]):
                raise Conflict('budget original descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in objects or not objkey and section in markers:
                raise Conflict('budget original extra or duplicate object')
            value=_decode(value)
            if not objkey:
                if value!={}:raise Conflict('budget original marker differs')
                markers[section]=value
            else:validate_record(section,objkey,value);objects[(section,objkey)]=value
        entries=[(k,v) for (s,k),v in objects.items() if s==SECTIONS[0]]
        if len(entries)!=1 or entries[0][0]!=key:raise Conflict('budget original single entry differs')
        value=entries[0][1];expected={(SECTIONS[0],key):value}
        expected.update({(s,k):v for s,values in derived_heads(value).items() for k,v in values.items()})
        previous=self._budget_tip(db,row['new_state_version']-1)
        if objects!=expected or markers!=({s:{} for s in SECTIONS} if previous is None else {}):
            raise Conflict('budget original derived objects/initial markers differ')
        if row['input_versions']!=canonical(event_inputs(value)).decode():
            raise Conflict('budget original canonical scope inputs differ')
        if _decode(_parse(row['input_versions'].encode()))!=event_inputs(value):
            raise Conflict('budget original decoded scope inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),expected_objects(value))

    def bind_hybrid_candidate_output(self,service):
        from .hybrid_candidate_output_service import CandidateOutputService
        if type(service) is not CandidateOutputService or service.store is not self:
            raise TypeError('invalid original candidate output service')
        with self.lock():
            if self._hybrid_candidate_output_service not in (None,service):raise Conflict('candidate output owner cannot be rebound')
            self._hybrid_candidate_output_service=service

    def _check_candidate_output_guard(self,db,guard):
        service=self._hybrid_candidate_output_service
        if service is None:raise PermissionError('protected candidate output service required')
        service.check_guard(db,guard);return service

    def _candidate_output_summary(self,db,section,version):
        from .hybrid_candidate_output import SECTIONS,EVENTS
        if section not in SECTIONS:raise Conflict('unknown candidate output domain')
        event=EVENTS[SECTIONS.index(section)]
        row=db.execute("SELECT CASE WHEN typeof(idempotency_key)='text' AND length(CAST(idempotency_key AS BLOB))<=160 THEN idempotency_key END,new_state_version FROM events WHERE event_type=? AND seq<=? ORDER BY seq DESC LIMIT 1",(event,version)).fetchone()
        count=db.execute('SELECT COUNT(*) FROM events WHERE event_type=? AND seq<=?',(event,version)).fetchone()[0]
        if row is not None and (row[0] is None or type(row[1]) is not int):raise Conflict('candidate output bounded tip differs')
        return (tuple(row) if row is not None else None),count

    def _candidate_output_event(self,db,key,*,max_bytes=4*1024**2,_parse=None,_decode=None):
        from .hybrid_candidate_output import SECTIONS,EVENTS,validate_record,event_inputs
        from .hybrid_goals import digest
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            read=ReadBudget(db,PREPARATION_READ_BYTES);_parse,_decode=read.parse,read.decode
        row=db.execute("SELECT seq,previous_state_version,new_state_version,object_version,CASE WHEN typeof(event_type)='text' AND length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN typeof(producer)='text' AND length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN typeof(object_id)='text' AND length(CAST(object_id AS BLOB))<=128 THEN object_id END AS object_id,CASE WHEN typeof(payload_sha256)='text' AND length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN typeof(input_versions)='text' AND length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN typeof(payload)='text' AND length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?",(max_bytes,key)).fetchone()
        if row is None:return None
        if (any(row[n] is None for n in ('event_type','producer','object_id','payload_sha256','input_versions','payload')) or
                row['event_type'] not in EVENTS or any(type(row[n]) is not int for n in ('seq','previous_state_version','new_state_version','object_version'))):
            raise Conflict('candidate output original bounded header differs')
        payload=_parse(row['payload'].encode())
        if (type(payload) is not dict or sha(payload)!=row['payload_sha256'] or canonical(payload).decode()!=row['payload'] or
                set(payload)!={'format','put','delete','details'} or type(payload['format']) is not int or payload['format']!=2 or
                type(payload['delete']) is not list or payload['delete']!=[] or payload['details'] is not None or type(payload['put']) is not list):
            raise Conflict('candidate output original integrity/shape differs')
        section=SECTIONS[EVENTS.index(row['event_type'])];rows=[];markers=[];seen=set()
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or item[0]!=section or type(item[1]) is not str or item[1] in seen:
                raise Conflict('candidate output original descriptor differs')
            seen.add(item[1]);value=_decode(item[2])
            if item[1]:validate_record(section,item[1],value);rows.append((item[1],value))
            else:markers.append(value)
        tip,_=self._candidate_output_summary(db,section,row['new_state_version']-1)
        if len(rows)!=1 or rows[0][0]!=key or markers!=([{}] if tip is None else []):raise Conflict('candidate output original fact/marker differs')
        value=rows[0][1];version=value['accepted_state_version']
        if (any(row[n]!=version for n in ('seq','new_state_version','object_version')) or row['previous_state_version']!=version-1 or
                row['object_id']!=digest(value) or row['producer']!='hybrid-core' or
                row['input_versions']!=canonical(event_inputs(value)).decode()):raise Conflict('candidate output original metadata/inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],version),[(section,key,digest(value))])

    def bind_hybrid_cpu_assessment(self, service):
        from .hybrid_cpu_assessment_service import CpuAssessmentService
        if type(service) is not CpuAssessmentService or service.store is not self:
            raise TypeError('invalid original CPU appraisal owner')
        with self.lock():
            if self._hybrid_cpu_assessment_service not in (None,service):
                raise Conflict('CPU appraisal owner cannot be rebound')
            self._hybrid_cpu_assessment_service=service

    def _check_cpu_assessment_guard(self,db,guard):
        service=self._hybrid_cpu_assessment_service
        if service is None: raise PermissionError('protected CPU appraisal owner required')
        service.check_guard(db,guard);return service

    def _cpu_assessment_summary(self,db,version):
        from .hybrid_cpu_assessment import EVENT
        row=db.execute('SELECT CASE WHEN typeof(idempotency_key)=\'text\' AND length(CAST(idempotency_key AS BLOB))<=160 THEN idempotency_key END AS idempotency_key,new_state_version FROM events WHERE event_type=? AND seq<=? ORDER BY seq DESC LIMIT 1',
            (EVENT,version)).fetchone()
        count=db.execute('SELECT COUNT(*) FROM events WHERE event_type=? AND seq<=?',(EVENT,version)).fetchone()[0]
        if row is not None and (row[0] is None or type(row[1]) is not int):
            raise Conflict('CPU appraisal original bounded tip differs')
        return (tuple(row) if row is not None else None),count

    def _cpu_assessment_event(self,db,key,*,max_bytes=256*1024,_parse=None,_decode=None):
        from .hybrid_cpu_assessment import SECTION,EVENT,validate_record,event_inputs
        from .hybrid_goals import digest
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            read=ReadBudget(db,4*1024**2);_parse,_decode=read.parse,read.decode
        row=db.execute('SELECT CASE WHEN typeof(event_type)=\'text\' AND length(CAST(event_type AS BLOB))<=64 THEN event_type END AS event_type,CASE WHEN typeof(producer)=\'text\' AND length(CAST(producer AS BLOB))<=64 THEN producer END AS producer,CASE WHEN typeof(object_id)=\'text\' AND length(CAST(object_id AS BLOB))<=128 THEN object_id END AS object_id,new_state_version,CASE WHEN typeof(payload_sha256)=\'text\' AND length(CAST(payload_sha256 AS BLOB))<=64 THEN payload_sha256 END AS payload_sha256,CASE WHEN typeof(input_versions)=\'text\' AND length(CAST(input_versions AS BLOB))<=4096 THEN input_versions END AS input_versions,CASE WHEN typeof(payload)=\'text\' AND length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',
            (max_bytes,key)).fetchone()
        if row is None:return None
        if any(row[n] is None for n in ('event_type','producer','object_id','payload_sha256','input_versions','payload')) or type(row['new_state_version']) is not int:
            raise Conflict('CPU appraisal source exceeds bound or header type differs')
        payload=_parse(row['payload'].encode())
        if (sha(payload)!=row['payload_sha256'] or type(payload) is not dict or
                set(payload)!={'format','put','delete','details'} or type(payload['format']) is not int or
                payload['format']!=2 or payload['delete']!=[] or payload['details'] is not None or type(payload['put']) is not list):
            raise Conflict('CPU appraisal original source integrity/shape differs')
        rows=[];markers=[];seen=set()
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or item[0]!=SECTION or type(item[1]) is not str or item[1] in seen:
                raise Conflict('CPU appraisal original descriptor differs')
            seen.add(item[1]);value=_decode(item[2])
            if not item[1]:markers.append(value)
            else:validate_record(item[1],value);rows.append((item[1],value))
        tip,_=self._cpu_assessment_summary(db,row['new_state_version']-1)
        if len(rows)!=1 or rows[0][0]!=key or markers!=([{}] if tip is None else []):
            raise Conflict('CPU appraisal original single fact/marker differs')
        if row['input_versions']!=canonical(event_inputs(rows[0][1])).decode():
            raise Conflict('CPU appraisal original canonical inputs differ')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),
            [(SECTION,key,digest(rows[0][1]))])

    def bind_hybrid_admission(self, service):
        from .hybrid_admission_service import AdmissionService
        if type(service) is not AdmissionService or service.store is not self:
            raise TypeError('invalid admission owner')
        with self.lock():
            if self._hybrid_admission_service not in (None,service):
                raise Conflict('admission owner cannot be rebound in-place')
            self._hybrid_admission_service=service

    def _check_admission_guard(self, db, guard):
        service=self._hybrid_admission_service
        if service is None:raise PermissionError('protected admission owner required')
        service.check_guard(db,guard)
        return service

    def _admission_tip(self, db, version):
        from .hybrid_admission import EVENT
        row=db.execute('SELECT idempotency_key,new_state_version FROM events WHERE event_type=? AND seq<=? ORDER BY seq DESC LIMIT 1',
                       (EVENT,version)).fetchone()
        return tuple(row) if row is not None else None

    def _admission_summary(self, db, version):
        from .hybrid_admission import EVENT
        count=db.execute('SELECT COUNT(*) FROM events WHERE event_type=? AND seq<=?',(EVENT,version)).fetchone()[0]
        return self._admission_tip(db,version),count

    def _admission_event(self, db, key, *, max_bytes=256*1024, _parse=None, _decode=None):
        """Closed original BLOCKED fact, including legal first-event marker."""
        from .hybrid_admission import SECTION, EVENT, validate_record
        from .hybrid_goals import check_bytes,digest
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,4*1024**2);_parse,_decode=budget.parse,budget.decode
        row=db.execute('SELECT event_type,producer,object_id,new_state_version,payload_sha256,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('admission source exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('admission source integrity mismatch')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload.get('format')) is not int or payload['format']!=2 or payload['details'] is not None or
                type(payload['put']) is not list or type(payload['delete']) is not list or payload['delete']):
            raise Conflict('admission original source shape mismatch')
        decoded=[];seen=set();markers=[]
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or not all(type(v) is str for v in item[:2]):
                raise Conflict('admission original descriptor invalid')
            section,objkey,value=item
            if section!=SECTION or objkey in seen:raise Conflict('admission original extra or duplicate object')
            seen.add(objkey);value=_decode(value);check_bytes(value,128*1024)
            if not objkey:
                if value!={}:raise Conflict('admission original marker differs')
                markers.append(value)
            else:
                validate_record(objkey,value);decoded.append((section,objkey,digest(value)))
        previous=self._admission_tip(db,row['new_state_version']-1)
        if len(decoded)!=1 or markers!=([{}] if previous is None else []):
            raise Conflict('admission original single fact/initial marker differs')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),decoded)

    def _controller_tip(self, db, version):
        from .hybrid_controller import EVENT
        row=db.execute('SELECT idempotency_key,new_state_version FROM events WHERE event_type=? AND seq<=? ORDER BY seq DESC LIMIT 1',
                       (EVENT,version)).fetchone()
        return tuple(row) if row is not None else None

    def bind_hybrid_controller(self, service):
        from .hybrid_controller_service import ControllerService
        if type(service) is not ControllerService or service.store is not self:
            raise TypeError('invalid controller owner')
        with self.lock():
            if self._hybrid_controller_service not in (None,service):
                raise Conflict('controller owner cannot be rebound in-place')
            self._hybrid_controller_service=service

    def _check_controller_guard(self, db, guard):
        service=self._hybrid_controller_service
        if service is None:raise PermissionError('protected controller owner required')
        service.check_guard(db,guard)
        return service

    def _controller_event(self, db, key, *, max_bytes=256*1024, _parse=None, _decode=None):
        """Bounded original controller fact/head pair, not a projection self-hash."""
        from .hybrid_controller import SECTIONS, validate_record, head
        from .hybrid_goals import check_bytes,digest
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            budget=ReadBudget(db,1024**2);_parse,_decode=budget.parse,budget.decode
        row=db.execute('SELECT event_type,producer,object_id,new_state_version,payload_sha256,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('controller source exceeds bound')
        payload=_parse(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('controller source integrity mismatch')
        if (type(payload) is not dict or set(payload)!={'format','put','delete','details'} or
                type(payload.get('format')) is not int or payload['format']!=2 or payload['details'] is not None or type(payload['put']) is not list or
                type(payload['delete']) is not list or payload['delete']):
            raise Conflict('controller original source shape mismatch')
        decoded=[];seen=set();markers=set();values={}
        for item in payload['put']:
            if type(item) is not list or len(item)!=3 or not all(type(v) is str for v in item[:2]):
                raise Conflict('controller original descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in seen:
                raise Conflict('controller original extra or duplicate object')
            seen.add((section,objkey));value=_decode(value);check_bytes(value,64*1024)
            if not objkey:
                if value!={}:raise Conflict('controller original marker differs')
                markers.add(section)
            else:
                validate_record(section,objkey,value);values[section]=value
                decoded.append((section,objkey,digest(value)))
        if len(decoded)!=2 or {s for s,k,h in decoded}!=set(SECTIONS):
            raise Conflict('controller original fact/head pair required')
        initial=values[SECTIONS[0]]['request']['previous_fact_key'] is None
        if markers!=(set(SECTIONS) if initial else set()) or values[SECTIONS[1]]!=head(values[SECTIONS[0]]):
            raise Conflict('controller original markers or derived head differ')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),sorted(decoded))

    def _preparation_event(self, db, key, *, max_bytes=5*1024**2, _parse=None, _decode=None):
        """Indexed closed original single-object preparation event proof."""
        from .hybrid_preparation import SECTIONS
        from .hybrid_goals import check_bytes,digest
        if _parse is None and _decode is None:
            from .hybrid_reads import ReadBudget
            # A <=4MiB decoded record can expand to >16MiB encoded descriptors
            # for inert marker-looking literal values. Match the live envelope.
            budget=ReadBudget(db,PREPARATION_READ_BYTES);_parse,_decode=budget.parse,budget.decode
        row=db.execute('SELECT event_type,producer,object_id,new_state_version,payload_sha256,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('preparation source exceeds bound')
        payload=(_parse or json.loads)(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('preparation source integrity mismatch')
        if (not isinstance(payload,dict) or set(payload)!={'format','put','delete','details'} or
                payload.get('format')!=2 or not isinstance(payload['put'],list) or
                not isinstance(payload['delete'],list) or payload['delete']):
            raise Conflict('preparation original source shape mismatch')
        decoded=[];seen=set()
        for item in payload['put']:
            if not isinstance(item,list) or len(item)!=3 or not all(isinstance(v,str) for v in item[:2]):
                raise Conflict('preparation original descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in seen:
                raise Conflict('preparation original duplicate or extra object')
            seen.add((section,objkey));value=_decode(value) if _decode else self._decode_value(db,value)
            check_bytes(value,4*1024**2)
            if not objkey:
                if value!={}:raise Conflict('preparation original marker differs')
            else:decoded.append((section,objkey,digest(value)))
        if len(decoded)!=1:raise Conflict('preparation original single object required')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),decoded)

    def _authority_event(self, db, key, *, max_bytes=3*1024*1024, _parse=None, _decode=None):
        """Indexed original fact/receipt/head witness, not snapshot self-hashes."""
        from .hybrid_authority import SECTIONS, digest
        row=db.execute('SELECT event_type,producer,object_id,new_state_version,payload_sha256,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('authority source exceeds bounded witness')
        payload=(_parse or json.loads)(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('authority source payload integrity mismatch')
        if (not isinstance(payload,dict) or set(payload)!={'format','put','delete','details'}
                or payload.get('format')!=2 or not isinstance(payload['put'],list)
                or not isinstance(payload['delete'],list) or payload['delete']):
            raise Conflict('authority original source shape mismatch')
        decoded=[];seen=set()
        for item in payload['put']:
            if not isinstance(item,list) or len(item)!=3 or not all(isinstance(v,str) for v in item[:2]):
                raise Conflict('authority original object descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in seen:
                raise Conflict('authority original source duplicate or extra object')
            seen.add((section,objkey))
            value=_decode(value) if _decode else self._decode_value(db,value)
            from .hybrid_goals import check_bytes
            check_bytes(value,1024*1024)
            if not objkey:
                if value!={}:raise Conflict('authority original collection marker mismatch')
            else:decoded.append((section,objkey,digest(value)))
        if len(decoded)!=3 or {s for s,k,h in decoded} not in (
                {SECTIONS[0],SECTIONS[2],SECTIONS[3]},{SECTIONS[1],SECTIONS[2],SECTIONS[3]}):
            raise Conflict('authority original source requires three objects')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),sorted(decoded))

    @staticmethod
    def _goal_event(db,key):
        row=db.execute('SELECT event_type,producer,object_id,new_state_version FROM events WHERE idempotency_key=?',(key,)).fetchone()
        return tuple(row) if row else None

    def _goal_source(self, db, key, *, max_bytes=16*1024*1024, _parse=None, _decode=None):
        """PK source proof for original full draft records, not row versions."""
        from .hybrid_goals import SECTIONS, check_bytes, digest
        row=db.execute('SELECT event_type,producer,object_id,new_state_version,payload_sha256,CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload FROM events WHERE idempotency_key=?',(max_bytes,key)).fetchone()
        if row is None:return None
        if row['payload'] is None:raise Conflict('draft source exceeds bounded witness')
        payload=(_parse or json.loads)(row['payload'].encode())
        if sha(payload)!=row['payload_sha256']:raise Conflict('draft source payload integrity mismatch')
        if (not isinstance(payload,dict) or set(payload)!={'format','put','delete','details'}
                or payload.get('format')!=2 or not isinstance(payload['put'],list)
                or not isinstance(payload['delete'],list) or payload['delete']):
            raise Conflict('draft original source shape mismatch')
        decoded=[];seen=set();markers=set()
        for item in payload['put']:
            if not isinstance(item,list) or len(item)!=3 or not all(isinstance(v,str) for v in item[:2]):
                raise Conflict('draft original object descriptor invalid')
            section,objkey,value=item
            if section not in SECTIONS or (section,objkey) in seen:
                raise Conflict('draft original source duplicate or extra object')
            seen.add((section,objkey))
            value=_decode(value) if _decode else self._decode_value(db,value)
            check_bytes(value,1024*1024)
            if not objkey:
                if value!={}:raise Conflict('draft original collection marker mismatch')
                markers.add(section)
            else:decoded.append((section,objkey,digest(value)))
        if len(decoded)!=3 or {s for s,k,h in decoded}!=set(SECTIONS):
            raise Conflict('draft original source requires three objects')
        return ((row['event_type'],row['producer'],row['object_id'],row['new_state_version']),sorted(decoded))

    def transact(self, event_type, key, mutate, *, expected=None, object_id="control", producer="orchestrator", inputs=None):
        """Legacy whole-state callback; new hot paths should use transact_objects."""
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            from .hybrid_authority import EVENTS as authority_events
            from .hybrid_preparation import EVENTS as preparation_events
            from .hybrid_controller import EVENT as controller_event
            from .hybrid_admission import EVENT as admission_event
            from .hybrid_budget_ledger import EVENT as budget_event
            from .hybrid_workspace import EVENT as workspace_event
            from .hybrid_runtime_installation import EVENTS as installation_events
            from .hybrid_working_plan import EVENTS as working_plan_events
            from .hybrid_cpu_assessment import EVENT as cpu_event
            from .hybrid_candidate_output import EVENTS as output_events
            if event_type in output_events:raise PermissionError('candidate output requires actual guarded object writer')
            if event_type==cpu_event or event_type in working_plan_events or event_type in installation_events or event_type in (controller_event,admission_event,budget_event,workspace_event) or event_type in preparation_events or event_type in authority_events.values() or (event_type=='HYBRID_GOAL_DRAFTED' and self._hybrid_draft_auth_owner is not None):
                raise PermissionError('Hybrid service events require guarded object transactions')
            if self._existing(db,key,event_type,object_id):
                db.commit()
                return self.view()
            after = self.view(db)
            previous = after["version"]
            if expected is not None and previous != expected: raise Conflict("stale state version")
            maps={k:v for k,v in after.items() if isinstance(v,ObjectMap)}
            scalars={k:canonical(v) for k,v in after.items() if not isinstance(v,ObjectMap) and k!="version"}
            details = mutate(after)
            if PRIVATE_HOT_SECTIONS.intersection(after):
                raise Conflict('Private tool ledger requires explicit object transaction')
            if after.get("version")!=previous:raise Conflict("state version is controller-owned")
            puts=[];deletes=[]
            partial=initial()
            for section,value in after.items():
                if section=="version":continue
                if isinstance(value,ObjectMap) and value is maps.get(section):
                    changed,removed=value.changes();puts.extend(changed);deletes.extend(removed)
                    partial[section]={k:v for _,k,v in changed}
                elif isinstance(value,dict):
                    old=maps.get(section)
                    before=old.copy() if old is not None else {}
                    puts.extend([[section,k,v] for k,v in value.items() if k not in before or v!=before[k]])
                    deletes.extend([[section,k] for k in before if k not in value])
                    if old is None:puts.append([section,"",{}])
                    partial[section]=value
                else:
                    if section in maps:
                        deletes.extend([[section,k] for k in maps[section]])
                    if scalars.get(section)!=canonical(value):puts.append([section,"",value])
                    partial[section]=value
            for section in (maps.keys()|scalars.keys())-after.keys():
                deletes.append([section,""])
                if section in maps:deletes.extend([[section,k] for k in maps[section]])
                partial.pop(section,None)
            from .contracts import validate_runtime_state
            validate_runtime_state(partial)
            for section,value in after.items():
                if isinstance(value,dict) and ("" in value or any(not isinstance(k,str) for k in value)):
                    raise Conflict("object keys must be nonempty strings")
            payload={"format":2,"put":puts,"delete":deletes,"details":details}
            self._commit(db,event_type,key,payload,previous,object_id,producer,inputs)
            db.commit()
            return self.view()

    def transact_objects(self, event_type, key, objects, mutate, *, expected=None, object_id="control", producer="orchestrator", inputs=None, _authorization=None):
        """Mutate an explicit object set atomically; omitted objects remain inaccessible.

        Callback receives a partial valid state with only the selected objects.
        Callers must list every object required for authorization and mutation.
        Optional protected-service guard factory is entered AFTER writer/BEGIN,
        checked at entry and directly before commit, and held through commit.
        Never accept this factory or an Access/Principal proof from request JSON.
        """
        objects=tuple(objects)
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            with _authorization() if _authorization is not None else contextlib.nullcontext() as authorization:
                if _authorization is not None and (authorization is None or not callable(getattr(authorization, 'check', None))):
                    raise Conflict('authorization guard unavailable')
                if authorization is not None:authorization.check()
                from .hybrid_authority import EVENTS as authority_events
                from .hybrid_preparation import EVENTS as preparation_events
                from .hybrid_controller import EVENT as controller_event
                from .hybrid_admission import EVENT as admission_event
                from .hybrid_budget_ledger import EVENT as budget_event, SECTIONS as budget_sections
                from .hybrid_workspace import EVENT as workspace_event, SECTIONS as workspace_sections
                from .hybrid_runtime_installation import EVENTS as installation_events, SECTIONS as installation_sections
                from .hybrid_working_plan import EVENTS as working_plan_events, SECTIONS as working_plan_sections
                from .hybrid_cpu_assessment import EVENT as cpu_event, SECTION as cpu_section
                from .hybrid_candidate_output import EVENTS as output_events,SECTIONS as output_sections
                if event_type in output_events or any(s in output_sections for s,k in objects):
                    self._check_candidate_output_guard(db,authorization)
                if event_type==cpu_event or any(s==cpu_section for s,k in objects):
                    self._check_cpu_assessment_guard(db,authorization)
                if event_type in working_plan_events or any(s in working_plan_sections for s,k in objects):
                    self._check_working_plan_guard(db,authorization)
                if event_type in installation_events or any(s in installation_sections for s,k in objects):
                    self._check_installation_guard(db,authorization)
                if event_type==workspace_event or any(s in workspace_sections for s,k in objects):
                    self._check_workspace_guard(db,authorization)
                if event_type==budget_event or any(s in budget_sections for s,k in objects):
                    self._check_budget_guard(db,authorization)
                if event_type==admission_event:self._check_admission_guard(db,authorization)
                if event_type==controller_event:self._check_controller_guard(db,authorization)
                if event_type in preparation_events:self._check_preparation_guard(db,authorization)
                if event_type in authority_events.values():self._check_hybrid_guard(db,authorization)
                if event_type=='HYBRID_GOAL_DRAFTED' and self._hybrid_draft_auth_owner is not None:
                    self._check_draft_guard(db,authorization,object_id)
                previous = db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]
                if self._existing(db,key,event_type,object_id):
                    if authorization is not None:
                        authorization.check()
                        db.commit()  # Close even the read-only retry while the guard is held.
                    return {"version":previous,"duplicate":True}
                if expected is not None and previous != expected: raise Conflict("stale state version")
                state=initial();state["version"]=previous
                selected=set(map(tuple,objects));before={}
                for section,objkey in selected:
                    if not objkey: raise Conflict("object transaction requires an object key")
                    row=db.execute("SELECT value FROM projection WHERE section=? AND object_key=?",(section,objkey)).fetchone()
                    if row:
                        value=self._decode_value(db,json.loads(row[0]));state.setdefault(section,{})[objkey]=value;before[(section,objkey)]=canonical(value)
                details=mutate(state)
                if state.get("version")!=previous:raise Conflict("state version is controller-owned")
                from .contracts import validate_runtime_state
                validate_runtime_state(state)
                current={(s,k):v for s,k,v in self._rows(state) if k}
                if set(current)-selected: raise Conflict("mutation outside selected objects")
                if any(state.get(k)!=v for k,v in initial().items() if not isinstance(v,dict) and k!="version"):
                    raise Conflict("control mutation outside selected objects")
                puts=[[s,k,v] for (s,k),v in current.items() if before.get((s,k))!=canonical(v)]
                for section in {s for s,k,v in puts}:
                    if not db.execute("SELECT 1 FROM projection WHERE section=? AND object_key=''",(section,)).fetchone():
                        puts.append([section,"",{}])
                payload={"format":2,"put":puts,"delete":[[s,k] for s,k in before if (s,k) not in current],"details":details}
                if authorization is None:ver=self._commit(db,event_type,key,payload,previous,object_id,producer,inputs)
                else:ver=self._commit(db,event_type,key,payload,previous,object_id,producer,inputs,_authorization=authorization)
                if authorization is not None:authorization.check()
                db.commit()
                return {"version":ver,"duplicate":False}

    def recover(self):
        """Validate the newest snapshot and replay only its tail into projections."""
        from .contracts import validate_runtime_event, validate_runtime_state
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM snapshots ORDER BY version DESC LIMIT 1").fetchone()
            if row:
                if hashlib.sha256(row["state"]).hexdigest()!=row["sha256"]: raise Conflict("snapshot integrity mismatch")
                state=json.loads(row["state"])
                if state["version"]!=row["version"]: raise Conflict("snapshot version mismatch")
                validate_runtime_state(state)
                from .hybrid_goals import validate_complete
                validate_complete(state,self._goal_registration(db),lambda k:self._goal_event(db,k),lambda k:self._goal_source(db,k))
                from .hybrid_authority import validate_complete as authority_complete
                authority_complete(state,self._goal_registration(db),lambda k:self._authority_event(db,k))
                self._preparation_complete(db,state)
            else: state=initial()
            for event in db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq",(state["version"],)):
                validate_runtime_event(dict(event))
                if event["previous_state_version"]!=state["version"]: raise Conflict("event version mismatch")
                self._apply(state,json.loads(event["payload"]),db,event)
                state["version"]=event["new_state_version"]
            validate_runtime_state(state)
            from .hybrid_goals import validate_complete
            validate_complete(state,self._goal_registration(db),lambda k:self._goal_event(db,k),lambda k:self._goal_source(db,k))
            from .hybrid_authority import validate_complete as authority_complete
            authority_complete(state,self._goal_registration(db),lambda k:self._authority_event(db,k))
            self._preparation_complete(db,state)
            self._replace_projection(db,state)
            return state

    def snapshot(self):
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state=self.replay(db);raw=canonical(state)
            from .hybrid_goals import validate_complete
            validate_complete(state,self._goal_registration(db),lambda k:self._goal_event(db,k),lambda k:self._goal_source(db,k))
            from .hybrid_authority import validate_complete as authority_complete
            authority_complete(state,self._goal_registration(db),lambda k:self._authority_event(db,k))
            self._preparation_complete(db,state)
            db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?)",(state["version"],raw,hashlib.sha256(raw).hexdigest()))
            db.execute('UPDATE snapshot_due SET due_version=CASE WHEN due_version<=? THEN 0 ELSE due_version END,last_complete=MAX(last_complete,?) WHERE singleton=1',(state['version'],state['version']))
            return {"version":state["version"],"sha256":hashlib.sha256(raw).hexdigest()}

    def export(self):
        with self.lock(), self.connect() as db:
            db.execute("BEGIN")
            state=self.replay(db)
            self._export(db,state)
            atomic(self.root/"state/export-version.json",canonical({"version":state["version"]}))
            return {"version":state["version"]}

    def _export(self, db, state):
        atomic(self.root / "state/RESEARCH_STATE.json", canonical(state) + b"\n")
        atomic_stream(self.root / "events/events.jsonl", (canonical(dict(r)) + b"\n" for r in db.execute("SELECT * FROM events ORDER BY seq")))
        for digest,data in db.execute("SELECT digest,data FROM blobs"):
            target=self.root/"events/blobs"/digest
            if not target.exists():atomic(target,data)
        atomic(self.root / "registry/objects.json", canonical({k: v for k, v in state.items() if isinstance(v, dict)}))

    def rebuild(self):
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self.audit(db)
            self._replace_projection(db, state)
            db.commit()
            return state
