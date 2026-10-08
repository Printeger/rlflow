"""Committed CORE_STATUS logs. No model files, prose, paths or execution claims."""
import hashlib
import json
import re
from .hybrid_protocol import ProtocolError, validate, validate_event


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def initialize(db, coverage):
    expected = {"public_log_meta","public_logs","public_log_refs"}
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('public_log_meta','public_logs','public_log_refs')")}
    if present and present != expected:
        raise ProtocolError("partial public log schema requires explicit recovery", "RESYNC_REQUIRED")
    for sql in (
        "CREATE TABLE IF NOT EXISTS public_log_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1),coverage INTEGER NOT NULL,last_seq INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS public_logs (seq INTEGER PRIMARY KEY,log_id TEXT UNIQUE NOT NULL,event_id TEXT UNIQUE NOT NULL,event_digest TEXT NOT NULL,severity TEXT NOT NULL,summary TEXT NOT NULL,summary_digest TEXT NOT NULL,body TEXT NOT NULL,body_digest TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS public_log_refs (kind TEXT NOT NULL,object_id TEXT NOT NULL,seq INTEGER NOT NULL,severity TEXT NOT NULL,PRIMARY KEY(kind,object_id,seq))",
        "CREATE INDEX IF NOT EXISTS public_logs_severity ON public_logs(severity,seq)",
        "CREATE INDEX IF NOT EXISTS public_log_refs_severity ON public_log_refs(kind,object_id,severity,seq)",
        "CREATE TRIGGER IF NOT EXISTS public_logs_no_update BEFORE UPDATE ON public_logs BEGIN SELECT RAISE(ABORT,'append only public logs'); END",
        "CREATE TRIGGER IF NOT EXISTS public_logs_no_delete BEFORE DELETE ON public_logs BEGIN SELECT RAISE(ABORT,'append only public logs'); END",
        "CREATE TRIGGER IF NOT EXISTS public_log_refs_no_update BEFORE UPDATE ON public_log_refs BEGIN SELECT RAISE(ABORT,'append only public log refs'); END",
        "CREATE TRIGGER IF NOT EXISTS public_log_refs_no_delete BEFORE DELETE ON public_log_refs BEGIN SELECT RAISE(ABORT,'append only public log refs'); END",
        "CREATE TRIGGER IF NOT EXISTS public_log_refs_insert_guard BEFORE INSERT ON public_log_refs BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM public_logs l,json_each(l.body,'$.refs') r WHERE l.seq=NEW.seq AND l.severity=NEW.severity AND json_extract(r.value,'$.kind')=NEW.kind AND json_extract(r.value,'$.id')=NEW.object_id) THEN RAISE(ABORT,'public log reference source mismatch') END; END",
    ): db.execute(sql)
    db.execute("INSERT OR IGNORE INTO public_log_meta VALUES(1,?,?)", (coverage,coverage))


def build(event):
    from .observation import counted_status
    validate_event(event, data_mode=event["data_mode"])
    refs, lines, states = {}, [], []
    for row in event["payload"]["upsert"]:
        status = counted_status(row.get("state")); states.append(status)
        refs[(row["kind"],row["id"])] = dict(kind=row["kind"],id=row["id"],version=row["version"])
        if row.get("task_id"):
            refs.setdefault(("task",row["task_id"]),dict(kind="task",id=row["task_id"],version=None))
        lines.append(f'{row["kind"]} {row["id"]} v{row["version"]}: observed state {status}')
    for row in event["payload"]["removed"]:
        refs.setdefault((row["kind"],row["id"]),dict(kind=row["kind"],id=row["id"],version=None))
        lines.append(f'{row["kind"]} {row["id"]}: removed from public projection')
    if any(re.fullmatch(r'ref_[0-9a-f]{64}',r["id"]) is None for r in refs.values()):
        raise ProtocolError("public log references must be opaque")
    severity = "ERROR" if any(s in {"FAILED","REJECTED","INVALID","ROLE_ERROR","INFRASTRUCTURE_ERROR"} for s in states) else "WARNING" if any(s in {"UNKNOWN","BLOCKED","RECONCILE","INCONCLUSIVE","BUDGET_EXHAUSTED"} for s in states) else "INFO"
    summary = dict(schema_version="1.0", id="log_"+digest(event["event_id"]), project_id=event["project_id"],
                   store_epoch=event["store_epoch"],data_mode=event["data_mode"],source="CORE_STATUS",template_version=1,
                   event_id=event["event_id"],seq=event["seq"],occurred_at=event["occurred_at"],severity=severity,
                   object_count=len(event["payload"]["upsert"])+len(event["payload"]["removed"]))
    body = dict(summary=summary,text=f'Core committed public observation #{event["seq"]}.\n'+"\n".join(lines),
                refs=list(refs.values()),raw_logs="PRIVATE_ONLY",tool_metadata="UNAVAILABLE")
    validate("LogSummary",summary); validate("LogBody",body)
    return summary,body


def commit(db, event, event_digest):
    # Old, not explicitly upgraded observers remain functional, without fake coverage.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_log_meta'").fetchone(): return
    meta = db.execute("SELECT * FROM public_log_meta WHERE singleton=1").fetchone()
    if meta is None: return
    if event["seq"] != meta["last_seq"]+1: raise ProtocolError("public log coverage gap", "RESYNC_REQUIRED")
    summary,body = build(event); encoded_summary,encoded_body = encode(summary),encode(body)
    db.execute("INSERT INTO public_logs VALUES(?,?,?,?,?,?,?,?,?)", (event["seq"],summary["id"],event["event_id"],event_digest,
               summary["severity"],encoded_summary,digest(encoded_summary),encoded_body,digest(encoded_body)))
    db.executemany("INSERT INTO public_log_refs VALUES(?,?,?,?)",[(r["kind"],r["id"],event["seq"],summary["severity"]) for r in body["refs"]])
    db.execute("UPDATE public_log_meta SET last_seq=? WHERE singleton=1",(event["seq"],))


def checked(db, reader):
    meta = reader._checked_meta(db)
    expected = {"public_log_meta","public_logs","public_log_refs"}
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('public_log_meta','public_logs','public_log_refs')")}
    if not present:
        raise ProtocolError("public logs require trusted prepare", "UNSUPPORTED_CAPABILITY")
    if present != expected:
        raise ProtocolError("partial public log schema requires explicit recovery", "RESYNC_REQUIRED")
    logs = db.execute("SELECT * FROM public_log_meta WHERE singleton=1").fetchone()
    if logs is None: raise ProtocolError("public logs unavailable", "UNSUPPORTED_CAPABILITY")
    last = db.execute("SELECT MAX(seq) FROM public_logs").fetchone()[0]
    if logs["last_seq"] != meta["seq"] or (last if last is not None else logs["coverage"]) != logs["last_seq"]:
        raise ProtocolError("public log coverage mismatch", "RESYNC_REQUIRED")
    return meta,logs


def row_summary(row, meta):
    if digest(row["summary"]) != row["summary_digest"] or row["event_digest"] != row["source_digest"]:
        raise ProtocolError("public log integrity mismatch", "RESYNC_REQUIRED")
    value = json.loads(row["summary"]); validate("LogSummary",value)
    if (value["project_id"],value["data_mode"],value["store_epoch"],value["seq"],value["id"],value["event_id"],value["severity"]) != (meta["project_id"],meta["data_mode"],meta["store_epoch"],row["seq"],row["log_id"],row["event_id"],row["severity"]):
        raise ProtocolError("public log identity mismatch", "RESYNC_REQUIRED")
    return value


def page(reader, *, severity=None, kind=None, object_id=None, after="", limit=50):
    from .observation import valid_id
    if type(limit) is not int or not 1 <= limit <= 200 or severity not in (None,"INFO","WARNING","ERROR"):
        raise ProtocolError("invalid log filter or limit")
    if (kind is None) != (object_id is None) or kind not in (None,"task","execution","experiment") or object_id is not None and not valid_id(object_id):
        raise ProtocolError("invalid log reference filter")
    filter_hash = digest(encode([severity,kind,object_id]))
    with reader.connect() as db:
        db.execute("BEGIN"); meta,logs = checked(db,reader)
        high,position = meta["seq"],meta["seq"]+1
        if after:
            if len(after)>1000: raise ProtocolError("log cursor too long")
            match = re.fullmatch(r'logpage/([A-Za-z0-9_.:-]+)/(0|[1-9][0-9]*)/(0|[1-9][0-9]*)/([0-9a-f]{64})',after)
            if not match or match[1] != meta["store_epoch"] or match[4] != filter_hash: raise ProtocolError("log cursor scope mismatch", "RESYNC_REQUIRED")
            high,position = int(match[2]),int(match[3])
            if not 0 <= high <= meta["seq"] or not 0 < position <= high: raise ProtocolError("log cursor position mismatch", "RESYNC_REQUIRED")
        floor = max(meta["floor"],logs["coverage"])
        where,args = ["l.seq>?","l.seq<=?","l.seq<?"],[floor,high,position]
        source = "public_logs l"
        order = "l.seq"
        if kind:
            source = "public_log_refs r LEFT JOIN public_logs l ON l.seq=r.seq"
            where,args = ["r.seq>?","r.seq<=?","r.seq<?"],[floor,high,position]
            order = "r.seq"
            where += ["r.kind=?","r.object_id=?"]; args += [kind,object_id]
            if severity: where.append("r.severity=?"); args.append(severity)
        elif severity: where.append("l.severity=?"); args.append(severity)
        # Filtered index hits must prove membership in their source event. Fetch
        # envelopes one at a time, never a page of up to 200 maximum-size events.
        extra = ",e.envelope" if kind else ""
        rows = db.execute("SELECT l.seq,l.log_id,l.event_id,l.event_digest,l.severity,l.summary,l.summary_digest,e.digest AS source_digest"+extra+" FROM "+source+
                          " LEFT JOIN observation_events e ON e.seq=l.seq AND e.event_id=l.event_id WHERE "+" AND ".join(where)+f" ORDER BY {order} DESC LIMIT ?",args+[limit+1])
        items,has_more = [],False
        expected = min(high,position-1)
        for row in rows:
            if row["log_id"] is None:
                raise ProtocolError("missing indexed public log", "RESYNC_REQUIRED")
            if kind is None and severity is None:
                if row["seq"] != expected: raise ProtocolError("public log sequence gap", "RESYNC_REQUIRED")
                expected -= 1
            summary = row_summary(row,meta)
            if kind:
                if digest(row["envelope"]) != row["source_digest"]:
                    raise ProtocolError("public log reference source integrity mismatch", "RESYNC_REQUIRED")
                event = json.loads(row["envelope"]); validate_event(event,data_mode=meta["data_mode"])
                if (event["project_id"],event["store_epoch"],event["seq"],event["event_id"]) != (meta["project_id"],meta["store_epoch"],row["seq"],row["event_id"]):
                    raise ProtocolError("public log reference source identity mismatch", "RESYNC_REQUIRED")
                candidates = event["payload"]["upsert"]+event["payload"]["removed"]
                member = any(r["kind"]==kind and r["id"]==object_id for r in candidates)
                member = member or kind=="task" and any(r.get("task_id")==object_id for r in event["payload"]["upsert"])
                if not member or severity is not None and summary["severity"] != severity:
                    raise ProtocolError("public log reference mismatch", "RESYNC_REQUIRED")
            if len(items)==limit: has_more=True;break
            items.append(summary)
        if kind is None and severity is None and not has_more and expected>floor:
            raise ProtocolError("missing public log history", "RESYNC_REQUIRED")
        following = f'logpage/{meta["store_epoch"]}/{high}/{items[-1]["seq"]}/{filter_hash}' if has_more else None
        value = dict(items=items,next_cursor=following,high_water=f'{meta["store_epoch"]}:{high}',coverage_after_seq=floor,project_id=meta["project_id"],data_mode=meta["data_mode"])
        validate("LogPage",value); return value


def body(reader, log_id):
    from .observation import valid_id
    if not valid_id(log_id): raise ProtocolError("invalid log ID")
    with reader.connect() as db:
        db.execute("BEGIN"); meta,logs = checked(db,reader)
        row = db.execute("SELECT l.*,e.digest AS source_digest,e.envelope FROM public_logs l JOIN observation_events e ON e.seq=l.seq AND e.event_id=l.event_id WHERE l.log_id=? AND l.seq>?",(log_id,max(meta["floor"],logs["coverage"]))).fetchone()
        if row is None: raise ProtocolError("public log not found", "NOT_FOUND")
        summary = row_summary(row,meta)
        if digest(row["body"]) != row["body_digest"] or digest(row["envelope"]) != row["source_digest"]:
            raise ProtocolError("public log body integrity mismatch", "RESYNC_REQUIRED")
        value = json.loads(row["body"]); validate("LogBody",value)
        event = json.loads(row["envelope"])
        if build(event) != (summary,value): raise ProtocolError("public log source mismatch", "RESYNC_REQUIRED")
        return value
