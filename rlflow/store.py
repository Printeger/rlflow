"""Append-only authoritative events; projections never perform side effects."""
from __future__ import annotations

import contextlib
import copy
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


def initial():
    return {"version": 0, "paused": False, "enabled": False, "stages": {}, "tasks": {},
            "sessions": {}, "jobs": {}, "proposals": {}, "approvals": {}, "evidence": {},
            "decisions": {}, "historical": {}, "migration": {}}


class Store:
    def __init__(self, root):
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
                """)

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

    def replay(self, db=None):
        if db is None:
            with self.connect() as conn:
                return self.replay(conn)
        state = initial()
        from .contracts import validate_runtime_event, validate_runtime_state
        for row in db.execute("SELECT * FROM events ORDER BY seq"):
            validate_runtime_event(dict(row))
            payload = json.loads(row["payload"])
            if sha(payload) != row["payload_sha256"] or row["previous_state_version"] != state["version"]:
                raise Conflict("event integrity/version mismatch")
            for key, value in payload["set"].items():
                state[key] = value
            state["version"] = row["new_state_version"]
        validate_runtime_state(state)
        return state

    def transact(self, event_type, key, mutate, *, expected=None, object_id="control", producer="orchestrator", inputs=None):
        with self.lock():
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT * FROM events WHERE idempotency_key=?", (key,)).fetchone()
                if existing:
                    if existing["event_type"] != event_type or existing["object_id"] != object_id:
                        raise Conflict("idempotency key reused for different operation")
                    return self.replay(db)
                before = self.replay(db)
                if expected is not None and before["version"] != expected:
                    raise Conflict("stale state version")
                after = copy.deepcopy(before)
                details = mutate(after)
                from .contracts import validate_runtime_state
                validate_runtime_state(after)
                changed = {k: v for k, v in after.items() if k != "version" and (k not in before or v != before[k])}
                payload = {"set": changed, "details": details}
                ver = before["version"] + 1
                db.execute("INSERT INTO events(event_id,idempotency_key,event_type,object_id,object_version,previous_state_version,new_state_version,producer,time,input_versions,payload,payload_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, key, event_type, object_id, ver, before["version"], ver,
                            producer, time.time(), json.dumps(inputs or {}), canonical(payload).decode(), sha(payload)))
                db.commit()
                state = self.replay(db)
                self._export(db, state)
                return state

    def _export(self, db, state):
        atomic(self.root / "state/RESEARCH_STATE.json", canonical(state) + b"\n")
        rows = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY seq")]
        atomic(self.root / "events/events.jsonl", b"".join(canonical(r) + b"\n" for r in rows))
        atomic(self.root / "registry/objects.json", canonical({k: v for k, v in state.items() if isinstance(v, dict)}))

    def rebuild(self):
        with self.lock(), self.connect() as db:
            state = self.replay(db)
            self._export(db, state)
            return state
