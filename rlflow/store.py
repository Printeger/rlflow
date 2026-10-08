"""Append-only authoritative events; projections never perform side effects."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
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
PRIVATE_HOT_SECTIONS = frozenset(('tool_sources','tool_receipts','tool_scan'))


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

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextlib.contextmanager
    def lock(self, name="writer", nonblocking=False):
        with (self.root / "runtime" / (name + ".lock")).open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            try:
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
            self._apply(state, payload, db)
            state["version"] = row["new_state_version"]
        validate_runtime_state(state)
        return state

    def _apply(self, state, payload, db):
        if payload.get("format") == 2:
            for section, key, value in sorted(payload["put"], key=lambda row:(row[0],row[1])):
                value = self._decode_value(db, value)
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

    def _commit(self, db, event_type, key, payload, previous, object_id, producer, inputs):
        ver = previous + 1
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

    def transact(self, event_type, key, mutate, *, expected=None, object_id="control", producer="orchestrator", inputs=None):
        """Legacy whole-state callback; new hot paths should use transact_objects."""
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
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

    def transact_objects(self, event_type, key, objects, mutate, *, expected=None, object_id="control", producer="orchestrator", inputs=None):
        """Mutate an explicit object set atomically; omitted objects remain inaccessible.

        Callback receives a partial valid state with only the selected objects.
        Callers must list every object required for authorization and mutation.
        """
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]
            if self._existing(db,key,event_type,object_id): return {"version":previous,"duplicate":True}
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
            ver=self._commit(db,event_type,key,payload,previous,object_id,producer,inputs)
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
            else: state=initial()
            for event in db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq",(state["version"],)):
                validate_runtime_event(dict(event))
                if event["previous_state_version"]!=state["version"]: raise Conflict("event version mismatch")
                self._apply(state,json.loads(event["payload"]),db)
                state["version"]=event["new_state_version"]
            validate_runtime_state(state)
            self._replace_projection(db,state)
            return state

    def snapshot(self):
        with self.lock(), self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state=self.replay(db);raw=canonical(state)
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
