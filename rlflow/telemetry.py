"""Latest-only core telemetry beside, never inside, durable business events."""
import hashlib
import json
import sqlite3
import time
import uuid
from . import telemetry_sources as sources
from .hybrid_protocol import ProtocolError, validate
from .observation import utc
from .store import canonical

ACTIVE = ('START_INTENT','RUNNING','RECONCILE')
FIELDS = ('directory','generation','identity','status','release_binding')
BINDING_FIELDS = ('session','generation','identity','request_sha256','candidate_sha256')


def initialize(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='telemetry_latest'").fetchone()
    if exists:
        if not db.execute('SELECT 1 FROM telemetry_latest WHERE singleton=1').fetchone():
            raise ProtocolError('telemetry slot requires explicit recovery','RESYNC_REQUIRED')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_worker_witness'").fetchone():
            raise ProtocolError('telemetry witnesses require explicit recovery','RESYNC_REQUIRED')
        return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_worker_witness'").fetchone():
        raise ProtocolError('orphan telemetry witnesses require recovery','RESYNC_REQUIRED')
    db.execute('CREATE TABLE telemetry_latest (singleton INTEGER PRIMARY KEY CHECK(singleton=1),sampler_epoch TEXT NOT NULL,sample_seq INTEGER NOT NULL,source_epoch TEXT,boot_id TEXT,monotonic_seconds REAL,body TEXT,digest TEXT,private TEXT NOT NULL)')
    db.execute('INSERT INTO telemetry_latest VALUES(1,?,0,NULL,NULL,NULL,NULL,NULL,?)',
               ('sampler_'+uuid.uuid4().hex,json.dumps(dict(after='',cpu=None,gc_after=''))))
    db.execute('CREATE TABLE telemetry_worker_witness (session_id TEXT PRIMARY KEY,source_epoch TEXT NOT NULL,witness TEXT NOT NULL)')


def _node(db,value):
    if isinstance(value,dict) and set(value)=={'$rlflow_blob'}:
        row = db.execute('SELECT data FROM blobs WHERE digest=?',(value['$rlflow_blob'],)).fetchone()
        if row is None or len(row[0])>65536 or hashlib.sha256(row[0]).hexdigest()!=value['$rlflow_blob']:
            raise ValueError('invalid telemetry source projection')
        return json.loads(row[0])
    return value


def _session(db,raw):
    if len(raw.encode())>65536:raise ValueError('session descriptor exceeds telemetry bound')
    value = _node(db,json.loads(raw))
    if not isinstance(value,dict):raise ValueError('invalid session projection')
    result = {key:_node(db,value.get(key)) for key in FIELDS}
    binding = result['release_binding']
    result['release_binding'] = {key:_node(db,binding.get(key)) for key in BINDING_FIELDS} if isinstance(binding,dict) else None
    return result


def _page(db,after):
    rows = []
    # Three indexed status ranges, each <=33, then bounded merge. No scan of
    # archived sessions or global ORDER BY across their full history.
    for status in ACTIVE:
        for row in db.execute('SELECT object_key,value FROM projection WHERE section=? AND object_status=? AND object_key>? ORDER BY object_key LIMIT 33',('sessions',status,after)):
            rows.append((row['object_key'],_session(db,row['value'])))
    rows.sort(key=lambda row:row[0])
    if not rows and after:return _page(db,'')
    earlier = bool(after) and any(db.execute('SELECT 1 FROM projection WHERE section=? AND object_status=? AND object_key<=? LIMIT 1',
                                            ('sessions',status,after)).fetchone() for status in ACTIVE)
    return rows[:32],len(rows)>32 or earlier


def sample(store):
    """Nonblocking, bounded core sampling. Busy/bad optional sources drop a sample."""
    try:
        with sqlite3.connect(store.db.as_uri()+'?mode=ro',uri=True,timeout=0) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_latest'").fetchone():return False
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_worker_witness'").fetchone():return False
            meta = db.execute('SELECT * FROM observation_meta WHERE singleton=1').fetchone()
            previous = db.execute('SELECT * FROM telemetry_latest WHERE singleton=1').fetchone()
            if meta is None or previous is None:return False
            boot,now = sources.boot_id(),time.monotonic()
            same = previous['boot_id']==boot and previous['source_epoch']==meta['store_epoch']
            if same and previous['monotonic_seconds'] is not None and 0<=now-previous['monotonic_seconds']<1:return False
            private = json.loads(previous['private']) if same else dict(after='',cpu=None,gc_after='')
            rows,truncated = _page(db,private['after'])
            selected = dict(rows)
            witnesses = {}
            for sid in selected:
                row = db.execute('SELECT source_epoch,witness FROM telemetry_worker_witness WHERE session_id=?',(sid,)).fetchone()
                witnesses[sid] = tuple(row) if row else None
            garbage = [r[0] for r in db.execute('SELECT session_id FROM telemetry_worker_witness WHERE session_id>? ORDER BY session_id LIMIT 32',(private['gc_after'],))]
            if not garbage and private['gc_after']:
                garbage = [r[0] for r in db.execute('SELECT session_id FROM telemetry_worker_witness ORDER BY session_id LIMIT 32')]
        host,cpu = sources.host(store.root,private['cpu'])
        workers,checkpoints = [],{}
        for sid,session in rows:
            witness = witnesses[sid]
            if witness and len(witness[1].encode())>4096:raise ValueError('worker witness exceeds bound')
            prior = json.loads(witness[1]) if witness and witness[0]==meta['store_epoch'] and same else None
            value,checkpoint = sources.worker(store.root,sid,session,prior)
            workers.append(value)
            if checkpoint is not None:checkpoints[sid]=checkpoint
        epoch = previous['sampler_epoch'] if same else 'sampler_'+uuid.uuid4().hex
        seq = previous['sample_seq']+1 if same else 1
        value = dict(schema_version='1.0',sample_id=epoch+':'+str(seq),sampler_epoch=epoch,sample_seq=seq,
                     observed_at=utc(),project_id=meta['project_id'],store_epoch=meta['store_epoch'],data_mode=meta['data_mode'],
                     source_state_version=meta['source_version'],
                     source='CORE_OS_SAMPLE',observability='PARTIAL',sample_age_seconds=0,host=host,
                     gpu=dict(scope='GPU',status='UNKNOWN',utilization_percent=None,memory_used_bytes=None),
                     workers=workers,workers_truncated=truncated)
        validate('Telemetry',value)
        encoded = canonical(value).decode()
        if len(encoded.encode())>65536:return False
        private = dict(after=rows[-1][0] if rows else '',cpu=cpu,gc_after=garbage[-1] if garbage else '',
                       bindings={sid:hashlib.sha256(canonical(session)).hexdigest() for sid,session in rows})
        # Same writer lock as authority, acquired without waiting. SQLite also
        # uses zero busy timeout; no Store.connect's 30-second waiting policy.
        with store.lock(nonblocking=True),sqlite3.connect(store.db,timeout=0) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM observation_meta WHERE singleton=1').fetchone()
            slot = db.execute('SELECT * FROM telemetry_latest WHERE singleton=1').fetchone()
            if current is None or slot is None or dict(slot)!=dict(previous) or any(current[k]!=meta[k] for k in ('project_id','store_epoch','data_mode')):return False
            for sid,session in selected.items():
                row = db.execute("SELECT value FROM projection WHERE section='sessions' AND object_key=?",(sid,)).fetchone()
                if row is None or _session(db,row['value'])!=session:return False
                witness = db.execute('SELECT source_epoch,witness FROM telemetry_worker_witness WHERE session_id=?',(sid,)).fetchone()
                if (tuple(witness) if witness else None)!=witnesses[sid]:return False
            for sid,checkpoint in checkpoints.items():
                db.execute('INSERT INTO telemetry_worker_witness VALUES(?,?,?) ON CONFLICT(session_id) DO UPDATE SET source_epoch=excluded.source_epoch,witness=excluded.witness',
                           (sid,meta['store_epoch'],canonical(checkpoint).decode()))
            for sid in garbage:
                row = db.execute("SELECT object_status FROM projection WHERE section='sessions' AND object_key=?",(sid,)).fetchone()
                if row is None or row[0] not in ACTIVE:
                    db.execute('DELETE FROM telemetry_worker_witness WHERE session_id=?',(sid,))
            db.execute('UPDATE telemetry_latest SET sampler_epoch=?,sample_seq=?,source_epoch=?,boot_id=?,monotonic_seconds=?,body=?,digest=?,private=? WHERE singleton=1',
                       (epoch,seq,meta['store_epoch'],boot,now,encoded,hashlib.sha256(encoded.encode()).hexdigest(),canonical(private).decode()))
        return True
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,IndexError,RecursionError,OverflowError):return False


def latest(reader):
    with reader.connect() as db:
        db.execute('BEGIN');meta = reader._checked_meta(db)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_latest'").fetchone():return None
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_worker_witness'").fetchone():return None
        row = db.execute('SELECT * FROM telemetry_latest WHERE singleton=1').fetchone()
        if row is None:raise ProtocolError('telemetry slot requires recovery','RESYNC_REQUIRED')
        if row['body'] is None or row['source_epoch']!=meta['store_epoch']:return None
        try:
            if row['boot_id']!=sources.boot_id():return None
            age = time.monotonic()-row['monotonic_seconds']
            if not sources.number(age):return None
        except (OSError,ValueError,TypeError):return None
        if len(row['body'].encode())>65536 or hashlib.sha256(row['body'].encode()).hexdigest()!=row['digest']:raise ProtocolError('telemetry integrity mismatch','RESYNC_REQUIRED')
        value = json.loads(row['body'])
        value.setdefault('source_state_version',None)  # Old slot has no causal witness.
        validate('Telemetry',value)
        if any(value[k]!=meta[k] for k in ('project_id','store_epoch','data_mode')) or value['sampler_epoch']!=row['sampler_epoch'] or value['sample_seq']!=row['sample_seq'] or value['sample_id']!=row['sampler_epoch']+':'+str(row['sample_seq']):
            raise ProtocolError('telemetry scope mismatch','RESYNC_REQUIRED')
        value['sample_age_seconds']=age
        try:
            if len(row['private'].encode())>65536:raise ValueError('private telemetry exceeds bound')
            bindings = json.loads(row['private']).get('bindings',{})
            if not isinstance(bindings,dict) or len(bindings)>32:raise ValueError('invalid telemetry bindings')
            retained = set()
            for sid,binding in bindings.items():
                if not sources.valid_id(sid):continue
                current = db.execute("SELECT value FROM projection WHERE section='sessions' AND object_key=?",(sid,)).fetchone()
                if current and hashlib.sha256(canonical(_session(db,current[0]))).hexdigest()==binding:
                    retained.add(sources.public_id(sid))
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
            retained = set()
        for worker in value['workers']:
            if value['source_state_version'] is None or worker['execution_id'] not in retained:
                worker['process'].update(status='UNKNOWN',cpu_seconds=None,rss_bytes=None)
                worker['heartbeat'].update(status='UNKNOWN',counter=None,age_seconds=None)
        for worker in value['workers']:
            heartbeat = worker['heartbeat']
            if heartbeat['status']!='UNKNOWN':
                heartbeat['age_seconds']+=age
                heartbeat['status']='FRESH' if heartbeat['age_seconds']<=15 else 'STALE'
        validate('Telemetry',value)
        return value
