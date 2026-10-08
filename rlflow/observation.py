"""Transactional, opt-in public observations of the existing control store.

Append-only observations are also the durable outbox. This bridge never grants
authority, interprets model prose, reads files or starts external work.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .hybrid_protocol import ATTEMPT_STATES, GOAL_STATES, TASK_STATES, ProtocolError, parse_cursor, validate, validate_event

SECTIONS = {"stages": "stage", "tasks": "task", "sessions": "execution", "jobs": "job",
            "proposals": "proposal", "approvals": "approval", "experiments": "experiment",
            "evidence": "evidence", "hypotheses": "hypothesis", "decisions": "decision",
            "usage": "usage", "packages": "package", "authorizations": "authorization"}
MAX_PAGE = 200
COUNTED_STATUSES = frozenset((*ATTEMPT_STATES,*GOAL_STATES,*TASK_STATES,
    "DONE","WAITING","HOLD","AUTHORIZED","REVOKED","PENDING","APPROVED","REJECTED",
    "ACCEPTED","NOT_STARTED","INCOMPLETE","COMPLETE","VALID","INVALID","INCONCLUSIVE"))


def counted_status(value):
    return value if value in COUNTED_STATUSES else "UNKNOWN"


def utc(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def public_id(value):
    # Even syntactically valid source IDs may contain a credential. Opaque stable
    # references also avoid revealing private paths encoded as object keys.
    return "ref_" + hashlib.sha256(str(value).encode()).hexdigest()


def valid_id(value):
    return isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}",value) is not None


def public_text(value):
    if not isinstance(value, str):
        return ""
    value = value[:4000]
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
    # Consume whole quoted values, including spaces and escaped quotes. Also
    # cover a value truncated at our text boundary rather than leaking its tail.
    value = re.sub(r'''(?i)["']?\b(api[_-]?key|access[_-]?token|password|secret|token)["']?\s*[=:]\s*(?:"(?:\\.|[^"\\])*(?:"|\\?$)|'(?:\\.|[^'\\])*(?:'|\\?$))''', r"\1=[REDACTED]", value)
    value = re.sub(r'''(?i)["']?\b(api[_-]?key|access[_-]?token|password|secret|token)["']?\s*[=:]\s*["']?[^\s,;}"']+''', r"\1=[REDACTED]", value)
    value = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s]+", "[REDACTED_CONNECTION]", value)
    value = re.sub(r'''(?<![:A-Za-z0-9/])/(?!/)[^\s,;"'<>]+''', "[PRIVATE_PATH]", value)
    return value


def summary(section, key, value, version):
    kind = SECTIONS[section]
    raw = value if isinstance(value, dict) else {}
    result = {"id": public_id(key), "kind": kind, "version": version,
              "source_status": public_text(raw.get("status")) or None, "observability": "PARTIAL"}
    for target, field in (("description", "description"), ("reason", "reason"), ("role", "role"), ("launch_phase", "launch_phase")):
        if isinstance(raw.get(field), str): result[target] = public_text(raw[field])
    if "description" not in result:
        for name in ("objective", "title", "summary", "text"):
            if isinstance(raw.get(name), str):
                result["description"] = public_text(raw[name]); break
    for field in ("task_id", "parent_id"):
        if isinstance(raw.get(field), str): result[field] = public_id(raw[field])
    compute = raw.get("compute") if isinstance(raw.get("compute"), dict) else {}
    model = raw.get("model", compute.get("model"))
    if isinstance(model, str): result["model_id"] = public_text(model)
    candidate = raw.get("candidate")
    if isinstance(candidate, str) and re.fullmatch("[0-9a-f]{64}", candidate):
        result["candidate_hash"] = "sha256:" + candidate
    # ROLE_IDENTITY is recorded before release; it is NOT model execution proof.
    if kind == "execution":
        result["state"] = "STARTING" if raw.get("status") == "RUNNING" else result["source_status"]
        result["usage_status"] = "UNKNOWN"
        proof = raw.get("startup_observation")
        valid_proof = False
        if isinstance(proof, dict):
            try:
                validate("StartupObservation", proof)
                valid_proof = (isinstance(raw.get("generation"), str) and proof["generation"] == raw["generation"]
                               and proof["observed_at"].endswith("Z") and proof["released_at"].endswith("Z"))
            except ProtocolError:
                pass  # Malformed optional observations cannot block core writes.
        if valid_proof:
            result["startup_observation"] = "CLI_RELEASE_ACK"
            result["startup_observed_at"] = proof["observed_at"]
            result["startup_released_at"] = proof["released_at"]
            result["launch_phase"] = "START_ACK"
    else:
        result["state"] = result["source_status"]
    if kind == "usage":
        for name in ("input_tokens", "output_tokens", "cached_tokens"):
            value = raw.get(name)
            result[name] = value if type(value) is int and value >= 0 else None
        fields = ("input_tokens", "output_tokens", "cached_tokens")
        valid = all(result[k] is not None for k in fields)
        valid = valid and result["cached_tokens"] <= result["input_tokens"]
        result["usage_status"] = "KNOWN" if raw.get("complete") is True and valid else "PARTIAL" if any(result[k] is not None for k in fields) else "UNKNOWN"
        result["actual_cost_status"] = "UNKNOWN"  # subscription usage is not a paid invoice
        result["actual_cost"] = None
    if kind == "stage":
        budget = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
        for target, source in (("used_calls", "used_calls"), ("reserved_calls", "reserved_calls")):
            number = raw.get(source)
            result[target] = number if type(number) is int and number >= 0 else None
        for target, source in (("used_seconds", "used_seconds"), ("reserved_seconds", "reserved_seconds")):
            number = raw.get(source)
            result[target] = number if type(number) in (int, float) and number >= 0 else None
        for target, source in (("limit_calls", "role_calls"), ("limit_seconds", "wall_seconds")):
            number = budget.get(source)
            result[target] = number if type(number) is int and number >= 0 else None
    validate("PublicObject", result)
    return result


def initialize_tables(db):
    # Individual execute calls preserve the caller's transaction (executescript
    # would implicitly commit and break atomic event+projection updates).
    statements = [
        "CREATE TABLE IF NOT EXISTS observation_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), project_id TEXT NOT NULL, store_epoch TEXT NOT NULL, data_mode TEXT NOT NULL, seq INTEGER NOT NULL, floor INTEGER NOT NULL, source_version INTEGER NOT NULL, paused INTEGER NOT NULL, enabled INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS observation_events (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, source_event_id TEXT NOT NULL, output_index INTEGER NOT NULL, envelope TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(source_event_id,output_index))",
        "CREATE TABLE IF NOT EXISTS observation_projection (kind TEXT NOT NULL, object_id TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL, PRIMARY KEY(kind,object_id))",
        "CREATE TABLE IF NOT EXISTS observation_counters (kind TEXT NOT NULL, status TEXT NOT NULL, count INTEGER NOT NULL CHECK(count>=0), PRIMARY KEY(kind,status))",
        "CREATE INDEX IF NOT EXISTS observation_projection_status ON observation_projection(kind,status,object_id)",
        "CREATE TRIGGER IF NOT EXISTS observation_no_update BEFORE UPDATE ON observation_events BEGIN SELECT RAISE(ABORT,'append only observations'); END",
        "CREATE TRIGGER IF NOT EXISTS observation_no_delete BEFORE DELETE ON observation_events BEGIN SELECT RAISE(ABORT,'append only observations'); END",
    ]
    for sql in statements: db.execute(sql)


def _counter(db, kind, status, delta):
    if delta > 0:
        db.execute("INSERT INTO observation_counters VALUES(?,?,1) ON CONFLICT(kind,status) DO UPDATE SET count=count+1", (kind,status))
    else:
        db.execute("UPDATE observation_counters SET count=count-1 WHERE kind=? AND status=?", (kind,status))
        db.execute("DELETE FROM observation_counters WHERE kind=? AND status=? AND count=0", (kind,status))


def commit(db, source_event_id, event_type, payload, source_version, timestamp):
    meta = db.execute("SELECT * FROM observation_meta WHERE singleton=1").fetchone()
    if meta is None: return
    upsert, removed, touched = [], [], set()
    for section, key, value in payload["put"]:
        if section not in SECTIONS or not key: continue
        kind, identity = SECTIONS[section], public_id(key)
        old = db.execute("SELECT status,summary FROM observation_projection WHERE kind=? AND object_id=?", (kind,identity)).fetchone()
        version = json.loads(old["summary"])["version"] + 1 if old else 1
        row = summary(section, key, value, version)
        status = counted_status(row.get("state"))
        if old:
            _counter(db,kind,old["status"],-1); touched.add((kind,old["status"]))
        _counter(db,kind,status,1)
        touched.add((kind,status))
        db.execute("INSERT INTO observation_projection VALUES(?,?,?,?) ON CONFLICT(kind,object_id) DO UPDATE SET status=excluded.status,summary=excluded.summary", (kind,identity,status,json.dumps(row,sort_keys=True,separators=(",",":"))))
        upsert.append(row)
    for section, key in payload["delete"]:
        if section not in SECTIONS: continue
        kind = SECTIONS[section]
        if key:
            identities = [public_id(key)]
        else:
            # Collection deletion is a rare explicit bulk operation, not a hot query.
            identities = [r[0] for r in db.execute("SELECT object_id FROM observation_projection WHERE kind=?", (kind,))]
        for identity in identities:
            old = db.execute("SELECT status FROM observation_projection WHERE kind=? AND object_id=?", (kind,identity)).fetchone()
            if old:
                _counter(db,kind,old["status"],-1); touched.add((kind,old["status"]))
            db.execute("DELETE FROM observation_projection WHERE kind=? AND object_id=?", (kind,identity))
            removed.append({"kind": kind, "id": identity})
    flags = {"paused": bool(meta["paused"]), "enabled": bool(meta["enabled"])}
    for section, key, value in payload["put"]:
        if section in flags and not key and type(value) is bool: flags[section] = value
    seq = meta["seq"]
    counters = [dict(row) for row in db.execute("SELECT kind,status,count FROM observation_counters ORDER BY kind,status LIMIT 1001")]
    present = {(row["kind"],row["status"]) for row in counters}
    counters += [{"kind":kind,"status":status,"count":0} for kind,status in sorted(touched-present)]
    if len(counters) > 1000: raise ProtocolError("observation counters exceed contract bound")
    # Keep every public object change; split oversized commits rather than drop facts.
    batches = max(1, (max(len(upsert),len(removed)) + MAX_PAGE - 1)//MAX_PAGE)
    for index in range(batches):
        seq += 1
        event = {"schema_version": "1.0", "store_epoch": meta["store_epoch"], "project_id": meta["project_id"],
                 "seq": seq, "event_id": "evt_" + uuid.uuid4().hex, "type": "legacy.observed",
                 "occurred_at": utc(timestamp), "recorded_at": utc(timestamp),
                 "entity": {"kind": "control", "id": "legacy_observer", "version": seq},
                 "correlation_id": public_id(source_event_id), "causation_id": None,
                 "source": {"kind": "core", "id": "legacy_bridge_v1"}, "data_mode": meta["data_mode"],
                 "payload": {"source_event_id": public_id(source_event_id), "source_event_type": public_text(event_type),
                             "source_state_version": source_version, **flags,
                             "counters": counters,
                             "upsert": upsert[index*MAX_PAGE:(index+1)*MAX_PAGE],
                             "removed": removed[index*MAX_PAGE:(index+1)*MAX_PAGE]}}
        validate_event(event, data_mode=meta["data_mode"])
        encoded = json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
        if len(encoded.encode()) > 2*1024*1024: raise ProtocolError("observation exceeds bounded event size")
        db.execute("INSERT INTO observation_events VALUES(?,?,?,?,?,?)", (seq,event["event_id"],source_event_id,index,encoded,hashlib.sha256(encoded.encode()).hexdigest()))
    db.execute("UPDATE observation_meta SET seq=?,source_version=?,paused=?,enabled=? WHERE singleton=1", (seq,source_version,flags["paused"],flags["enabled"]))


def enable(store, project_id, *, data_mode="live"):
    if not valid_id(project_id) or public_text(project_id) != project_id or data_mode not in ("live", "fixture"):
        raise ProtocolError("invalid observer identity or mode")
    with store.lock(), store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        initialize_tables(db)
        existing = db.execute("SELECT * FROM observation_meta").fetchone()
        if existing:
            if existing["project_id"] != project_id or existing["data_mode"] != data_mode:
                raise ProtocolError("observer identity is immutable")
            return existing["store_epoch"]
        version = db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()[0]
        epoch = "store_" + uuid.uuid4().hex
        db.execute("INSERT INTO observation_meta VALUES(1,?,?,?,0,0,?,1,0)", (project_id,epoch,data_mode,version))
        # One-time, explicit observation migration. Subsequent writes are incremental.
        rows = []
        for row in db.execute("SELECT section,object_key,value FROM projection"):
            if row["section"] in SECTIONS or row["section"] in ("paused", "enabled"):
                rows.append([row["section"],row["object_key"],store._decode_value(db,json.loads(row["value"]))])
        commit(db, "baseline_" + uuid.uuid4().hex, "OBSERVATION_BASELINE", {"put": rows,"delete": []}, version, time.time())
        return epoch


class ObservationReader:
    """Read-only queries; construction never creates or migrates a state store."""
    def __init__(self, root, *, expected_project_id=None, expected_data_mode=None):
        self.db = Path(root).resolve() / "runtime" / "research.db"
        self.expected_project_id, self.expected_data_mode = expected_project_id, expected_data_mode

    def connect(self):
        db = sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return db

    @staticmethod
    def _meta(db):
        row = db.execute("SELECT * FROM observation_meta WHERE singleton=1").fetchone()
        if row is None: raise ProtocolError("observation not initialized", "UNSUPPORTED_CAPABILITY")
        source = db.execute("SELECT version FROM projection_meta WHERE singleton=1").fetchone()
        if source is None or source[0] != row["source_version"]:
            raise ProtocolError("observation/source projection mismatch", "RESYNC_REQUIRED")
        last = db.execute("SELECT COALESCE(MAX(seq),0) FROM observation_events").fetchone()[0]
        if last != row["seq"]: raise ProtocolError("outbox/meta sequence mismatch", "RESYNC_REQUIRED")
        return row

    def _checked_meta(self, db):
        meta = self._meta(db)
        if ((self.expected_project_id is not None and meta["project_id"] != self.expected_project_id)
                or (self.expected_data_mode is not None and meta["data_mode"] != self.expected_data_mode)):
            raise ProtocolError("observation identity mismatch", "RESYNC_REQUIRED")
        return meta

    @staticmethod
    def _page(db, *, limit, kind=None, after=""):
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE: raise ProtocolError("invalid page limit")
        if kind is not None and kind not in SECTIONS.values(): raise ProtocolError("unknown object kind")
        # Keyset ordering includes kind so equal IDs in different sections do not collide.
        if after:
            if "/" not in after: raise ProtocolError("invalid object page cursor")
            after_kind, after_id = after.split("/",1)
            if after_kind not in SECTIONS.values() or not valid_id(after_id):
                raise ProtocolError("invalid object page cursor")
        else:
            after_kind, after_id = "", ""
        query = "SELECT kind,object_id,summary FROM observation_projection WHERE (kind,object_id) > (?,?)"
        args = [after_kind, after_id]
        if kind:
            query += " AND kind=?"; args.append(kind)
        query += " ORDER BY kind,object_id LIMIT ?"; args.append(limit+1)
        rows = db.execute(query,args).fetchall()
        total = db.execute("SELECT COALESCE(SUM(count),0) FROM observation_counters" + (" WHERE kind=?" if kind else ""), (kind,) if kind else ()).fetchone()[0]
        return {"items": [json.loads(row["summary"]) for row in rows[:limit]],
                "next_cursor": rows[limit-1]["kind"]+"/"+rows[limit-1]["object_id"] if len(rows)>limit else None, "total": total}

    def snapshot(self, *, limit=30):
        with self.connect() as db:
            db.execute("BEGIN")
            meta = self._checked_meta(db)
            counters = [dict(row) for row in db.execute("SELECT kind,status,count FROM observation_counters WHERE count>0 ORDER BY kind,status LIMIT 1000")]
            value = {"schema_version": "1.0", "project_id": meta["project_id"], "store_epoch": meta["store_epoch"],
                     "cursor": f'{meta["store_epoch"]}:{meta["seq"]}', "server_time": utc(), "data_mode": meta["data_mode"],
                     "projection": {"source_state_version": meta["source_version"], "paused": bool(meta["paused"]),
                                    "enabled": bool(meta["enabled"]), "counters": counters,
                                    "objects": self._page(db,limit=limit), "observability": "PARTIAL"}}
            validate("Snapshot", value)
            return value

    def page(self, *, kind=None, after="", limit=50, include_cursor=False):
        with self.connect() as db:
            db.execute("BEGIN")
            meta = self._checked_meta(db)
            result = self._page(db,kind=kind,after=after,limit=limit)
            if include_cursor:
                result.update(project_id=meta["project_id"], data_mode=meta["data_mode"], cursor=f'{meta["store_epoch"]}:{meta["seq"]}')
                validate("ObjectPage", result)
            return result

    def event(self, event_id):
        """One public event by opaque ID, no path access or unbounded history."""
        if not valid_id(event_id): raise ProtocolError("invalid public event ID")
        with self.connect() as db:
            db.execute("BEGIN")
            meta = self._checked_meta(db)
            row = db.execute("SELECT seq,envelope,digest FROM observation_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None or row["seq"] <= meta["floor"]:
                raise ProtocolError("public event not found", "NOT_FOUND")
            if hashlib.sha256(row["envelope"].encode()).hexdigest() != row["digest"]:
                raise ProtocolError("event integrity mismatch", "RESYNC_REQUIRED")
            event = json.loads(row["envelope"])
            if event["project_id"] != meta["project_id"] or event["store_epoch"] != meta["store_epoch"] or event["seq"] != row["seq"] or event["event_id"] != event_id:
                raise ProtocolError("public event identity mismatch", "RESYNC_REQUIRED")
            validate_event(event,data_mode=meta["data_mode"])
            return event

    def head(self):
        """Small consistent metadata read; no projection scan or process probes."""
        with self.connect() as db:
            db.execute("BEGIN")
            meta = self._checked_meta(db)
            return {"project_id": meta["project_id"], "data_mode": meta["data_mode"],
                    "cursor": f'{meta["store_epoch"]}:{meta["seq"]}', "server_time": utc()}

    def events(self, cursor, *, limit=200):
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE: raise ProtocolError("invalid event limit")
        with self.connect() as db:
            db.execute("BEGIN")
            meta = self._checked_meta(db)
            seq = parse_cursor(cursor,meta["store_epoch"])
            if seq < meta["floor"] or seq > meta["seq"]: raise ProtocolError("cursor outside retained range", "RESYNC_REQUIRED")
            result = []
            for row in db.execute("SELECT seq,envelope,digest FROM observation_events WHERE seq>? ORDER BY seq LIMIT ?", (seq,limit)):
                if hashlib.sha256(row["envelope"].encode()).hexdigest() != row["digest"]:
                    raise ProtocolError("event integrity mismatch", "RESYNC_REQUIRED")
                event = json.loads(row["envelope"])
                if row["seq"] != seq+1 or event["seq"] != row["seq"]:
                    raise ProtocolError("durable sequence gap or mismatch", "RESYNC_REQUIRED")
                # An explicit epoch rotation requires a fresh snapshot, not rewritten history.
                if event["project_id"] != meta["project_id"] or event["store_epoch"] != meta["store_epoch"]: raise ProtocolError("restored history requires snapshot", "RESYNC_REQUIRED")
                validate_event(event,data_mode=meta["data_mode"])
                result.append(event)
                seq = row["seq"]
            if not result and seq < meta["seq"]: raise ProtocolError("missing durable events", "RESYNC_REQUIRED")
            return result


def rotate_epoch(store):
    """Explicit offline restore boundary. Keeps source IDs, budgets and event bytes."""
    with store.lock(), store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        meta = ObservationReader._meta(db)
        epoch = "store_"+uuid.uuid4().hex
        db.execute("UPDATE observation_meta SET store_epoch=?,floor=? WHERE singleton=1", (epoch,meta["seq"]))
        return epoch
