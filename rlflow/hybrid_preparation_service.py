"""Protected non-executing preparation owner; no HTTP, lease or worker API.

Copies and native metadata IO occur outside the business writer. Immutable intent
records the original seal BEFORE publication. Restart reconciliation deliberately
records UNKNOWN rather than trusting a disk manifest or automatically regenerating
material. PREPARED remains a historical observation, never execution authority.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
import uuid
import weakref

from .execution_adapter import CodexExecAdapter
from .files import relative_name
from .hybrid_goals import check_bytes, digest
from .hybrid_preparation import (REQUEST, SECTIONS, EVENTS, intent_key, result_key,
    source_binding, validate_record, validate_complete, MATERIAL_OBSERVATION)
from .hybrid_preparation_sources import load_sources, historical_sources
from .hybrid_reads import ReadBudget
from .hybrid_protocol import validate_schema, ID
from .hybrid_registry import Registry
from .hybrid_snapshot import SnapshotBuilder
from .hybrid_authority import timestamp
from .jobs import identity
from .store import Store, Conflict, canonical, PREPARATION_READ_BYTES

# Includes repeated projection/source expansion of two <=4MiB prep records,
# original Goal/Authority point proofs, and both live-source validations.
TRANSACTION_BYTES=PREPARATION_READ_BYTES


@dataclass(frozen=True,eq=False)
class MaterialWitness:
    """Actual as-of observation, not an immutable filesystem or execution lease."""
    id: str
    raw: bytes
    materials: tuple
    boot_id: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int


class _Guard:
    def __init__(self, owner, section, key, record, materials):
        self.owner, self.section, self.key = owner, section, key
        self.raw = canonical(record); self.materials = materials
        self.budget=None

    def check(self):
        self.owner._check_active(self)


class PreparationService:
    def __init__(self, store, registry, builder, adapter, *, project_id, data_mode,
                 store_epoch, clock=lambda: datetime.now(timezone.utc),monotonic_ns=time.monotonic_ns):
        if (type(store) is not Store or type(registry) is not Registry or
                type(builder) is not SnapshotBuilder or type(adapter) is not CodexExecAdapter or
                adapter.registry is not registry):
            raise TypeError('fixed actual preparation components required')
        config=json.loads(registry._raw)
        if (config['project_id'],config['data_mode']) != (project_id,data_mode):
            raise Conflict('preparation owner scope differs')
        self.store, self.registry, self.builder, self.adapter = store, registry, builder, adapter
        self.project_id, self.data_mode, self.store_epoch = project_id, data_mode, store_epoch
        self.clock=clock; self._active=None; self._materials={}; self._lock=threading.RLock()
        self._witnesses=weakref.WeakValueDictionary()
        self._witness_monotonic_ns=monotonic_ns;self._witness_last_sample=None
        process=identity(os.getpid())
        if process is None:raise Conflict('actual material observation process unavailable')
        self._witness_boot_id=process['boot_id'];self._witness_sample_lock=threading.Lock()
        store.bind_hybrid_preparation(self)

    def _observation(self,witness_id,key,intent,outcome,now):
        if outcome['status']!='PREPARED' or outcome['material'] is None:
            raise Conflict('material witness requires original PREPARED fact')
        return {'witness_id':witness_id,'intent_key':key,'intent_hash':digest(intent),
            'result_key':result_key(key),'result_hash':digest(outcome),'snapshot_id':intent['snapshot_id'],
            'snapshot_hash':intent['snapshot']['tree_hash'],'plan_hash':intent['bundle']['plan_hash'],
            'manifest_hash':intent['bundle']['seal']['manifest_hash'],
            'checked_at':now.isoformat().replace('+00:00','Z'),
            'expires_at':(now+timedelta(seconds=30)).isoformat().replace('+00:00','Z'),
            'state':'VERIFIED_AS_OF','execution_enabled':False}

    def _witness_sample(self):
        # Independent short clock mutex: never acquires Prep owner/writer locks
        # and never verifies files while held; serialize high-water updates.
        with self._witness_sample_lock:
            now=self._now();mono=self._witness_monotonic_ns()
            if type(mono) is not int or not 0<=mono<=2**63-1-30*10**9:
                raise Conflict('material observation requires actual monotonic clock')
            old=self._witness_last_sample
            if old is not None and (now<old[0] or mono<old[1]):
                raise Conflict('material observation clock regressed')
            self._witness_last_sample=(now,mono)
            return now,mono

    def issue_material_witness(self,key):
        """Actual finite file verification OUTSIDE the business writer.

        Never call while holding Store writer: prepare uses owner->writer order.
        Result is an as-of observation only; no filesystem freeze is claimed.
        """
        validate_schema(ID,key)
        with self._lock:
            if len(self._witnesses)>=128:raise Conflict('material witness capacity reached')
            with self.store.read_connection() as db:
                db.execute('BEGIN');budget=ReadBudget(db,TRANSACTION_BYTES);self._metadata(db)
                intent=self._original(db,SECTIONS[0],key,budget)
                outcome=self._original(db,SECTIONS[1],result_key(key),budget)
                self._historical(db,key,intent,outcome,budget)
            material=self._materials.get(key)
            if material is None:raise PermissionError('actual original issued preparation materials required')
            snapshot,plan,bundle=material
            if (intent['snapshot_id']!=snapshot.id or intent['snapshot']!=json.loads(snapshot.raw) or
                    intent['plan']!=json.loads(plan.raw) or intent['bundle']!=json.loads(bundle.raw)):
                raise Conflict('material witness original issued bytes differ')
            self.builder.verify(snapshot);self.adapter.verify_bundle(bundle)
            wid='material_witness_'+uuid.uuid4().hex
            # Completion timestamp after sequential checks, NOT a claim that
            # both file trees were atomically frozen at this instant.
            now,mono=self._witness_sample()
            record=self._observation(wid,key,intent,outcome,now)
            check_bytes(record,4096);validate_schema(MATERIAL_OBSERVATION,record)
            witness=MaterialWitness(wid,canonical(record),material,self._witness_boot_id,mono,mono+30*10**9);self._witnesses[wid]=witness
            return witness

    def check_material_witness(self,witness,intent,outcome):
        """No IO/owner lock acquisition: use original same-DB facts in writer.

        Issued material slots are append-only; this check never calls prepare,
        source readers or full-file verification under a business writer.
        """
        if (type(witness) is not MaterialWitness or self._witnesses.get(witness.id) is not witness or
                self.store._hybrid_preparation_service is not self or witness.boot_id!=self._witness_boot_id):
            raise PermissionError('actual issued material witness required')
        record=json.loads(witness.raw);validate_schema(MATERIAL_OBSERVATION,record)
        now,mono=self._witness_sample();checked=timestamp(record['checked_at'])
        if (not checked<=now<timestamp(record['expires_at']) or
                not witness.issued_monotonic_ns<=mono<witness.expires_monotonic_ns):
            raise Conflict('material observation expired or clock regressed')
        expected=self._observation(witness.id,record['intent_key'],intent,outcome,checked)
        if record!=expected or self._materials.get(record['intent_key']) is not witness.materials:
            raise Conflict('material observation differs from original issued facts')
        snapshot,plan,bundle=witness.materials
        if (intent['snapshot_id']!=snapshot.id or intent['snapshot']!=json.loads(snapshot.raw) or
                intent['plan']!=json.loads(plan.raw) or intent['bundle']!=json.loads(bundle.raw)):
            raise Conflict('material observation original bytes changed')
        return record

    def _now(self):
        now=self.clock()
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset().total_seconds()!=0:
            raise Conflict('preparation requires actual UTC clock')
        return now

    def _load(self, db, goal_ref, budget=None):
        return load_sources(self.store,db,self.registry,project_id=self.project_id,
            data_mode=self.data_mode,store_epoch=self.store_epoch,goal_ref=goal_ref,now=self._now(),_budget=budget)

    def _check_active(self, guard):
        if type(guard) is not _Guard or guard.owner is not self or self._active is not guard:
            raise PermissionError('actual active preparation owner guard required')
        record=json.loads(guard.raw)
        sources=record['sources']
        if sources is not None:
            now=self._now()
            if not timestamp(sources['evaluated_at'])<=now<timestamp(sources['expires_at']):
                raise Conflict('preparation consent expired or clock regressed')

    def check_guard(self, db, guard):
        self._check_active(guard)
        self._metadata(db)
        if self.store._hybrid_preparation_service is not self:
            raise PermissionError('actual bound preparation owner required')
        if guard.budget is None:guard.budget=ReadBudget(db,TRANSACTION_BYTES)
        if guard.budget.db is not db or not db.in_transaction:
            raise Conflict('actual preparation writer transaction required')

    def _metadata(self,db):
        meta=db.execute('SELECT project_id,data_mode,store_epoch,source_version FROM observation_meta WHERE singleton=1').fetchone()
        if meta is None or tuple(meta[:3])!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('preparation owner registration or epoch changed')
        version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
        if (type(version) is not int or not 0<=version<=2**63-1 or version!=meta['source_version'] or
                version!=db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]):
            raise Conflict('preparation owner source version invalid')
        return version

    @contextmanager
    def _authorization(self, section, key, record, materials):
        if self._active is not None:raise Conflict('nested preparation transaction refused')
        guard=_Guard(self,section,key,record,materials);self._active=guard
        try:
            guard.check();yield guard
        finally:self._active=None

    def check_live_write(self, db, payload, guard):
        self.check_guard(db,guard)
        rows=[(s,k,v) for s,k,v in payload['put'] if k]
        record=json.loads(guard.raw)
        if rows!=[(guard.section,guard.key,record)]:
            raise Conflict('preparation mutation differs from issued owner context')
        if guard.section==SECTIONS[0] or record['status']=='PREPARED':
            material=guard.materials
            if material is None or self._materials.get(
                    guard.key if guard.section==SECTIONS[0] else record['intent_key']) is not material:
                raise PermissionError('actual issued preparation materials required')
            snapshot,plan,bundle=material
            intent=record if guard.section==SECTIONS[0] else self._original(db,SECTIONS[0],record['intent_key'],guard.budget)
            if (intent['snapshot_id']!=snapshot.id or intent['snapshot']!=json.loads(snapshot.raw) or
                    intent['plan']!=json.loads(plan.raw) or intent['bundle']!=json.loads(bundle.raw)):
                raise Conflict('preparation facts differ from actual issued materials')
            current=source_binding(self._load(db,record['sources']['goal_ref'],guard.budget))
            if any(current[k]!=v for k,v in record['sources'].items() if k!='evaluated_at'):
                raise Conflict('preparation source changed inside writer')
        if guard.section==SECTIONS[1]:
            original=self._original(db,SECTIONS[0],record['intent_key'],guard.budget)
            self._historical(db,record['intent_key'],original,None,guard.budget)
            if record['intent_hash']!=digest(original):raise Conflict('preparation original intent differs')
        guard.check()

    def _original(self, db, section, key, budget):
        value=budget.object(section,key)
        if value is None:raise Conflict('preparation original fact missing')
        validate_record(section,key,value)
        # Original event proof is mandatory even for indexed retries/completion.
        proof=self.store._preparation_event(db,key,max_bytes=min(budget.remaining,5*1024**2),
                                           _parse=budget.parse,_decode=budget.decode)
        if proof!=((EVENTS[SECTIONS.index(section)],'hybrid-core',digest(value),value['accepted_state_version']),
                   [(section,key,digest(value))]):raise Conflict('preparation original event differs')
        return value

    def _historical(self,db,key,intent,outcome,budget):
        state=historical_sources(self.store,db,intent['sources'],budget)
        state['version']=self._metadata(db)
        state[SECTIONS[0]]={key:intent}
        if outcome is not None:state[SECTIONS[1]]={result_key(key):outcome}
        validate_complete(state,(self.project_id,self.data_mode),lambda k:self.store._preparation_event(
            db,k,max_bytes=min(budget.remaining,5*1024**2),_parse=budget.parse,_decode=budget.decode))

    def _existing(self, key, request):
        with self.store.read_connection() as db:
            db.execute('BEGIN')
            budget=ReadBudget(db,TRANSACTION_BYTES)
            self._metadata(db)
            if not db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],key)).fetchone():
                return None
            intent=self._original(db,SECTIONS[0],key,budget)
            if intent['request']!=request:raise Conflict('preparation idempotency key reused')
            rk=result_key(key)
            outcome=self._original(db,SECTIONS[1],rk,budget) if db.execute(
                'SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[1],rk)).fetchone() else None
            self._historical(db,key,intent,outcome,budget)
            return {'intent':intent,'result':outcome,'duplicate':True,'execution_enabled':False}

    def _append(self, section, key, record, materials):
        validate_record(section,key,record)
        def mutate(state):
            state.setdefault(section,{})[key]=json.loads(canonical(record))
        self.store.transact_objects(EVENTS[SECTIONS.index(section)],key,[(section,key)],mutate,
            expected=record['accepted_state_version']-1,object_id=digest(record),producer='hybrid-core',
            _authorization=lambda:self._authorization(section,key,record,materials))

    @staticmethod
    def _write_roots(proposal, snapshot, role):
        if role!='Engineer':return []
        def name(value):
            result=value[:-1] if value.endswith('/') else value
            relative_name(result)
            if '\x00' in result:raise Conflict('invalid preparation scope path')
            return result
        writes=[name(v) for v in proposal['scope']['writable_paths']]
        protected=[name(v) for v in proposal['scope']['protected_paths']]
        if len(writes)>128 or len(set(writes))!=len(writes):raise Conflict('bounded unique writes required')
        for writable in writes:
            if any(writable==p or writable.startswith(p+'/') or p.startswith(writable+'/') for p in protected):
                raise Conflict('preparation write scope intersects protected path')
        return [snapshot.path/v for v in writes]

    def prepare(self, request):
        check_bytes(request,256*1024);validate_schema(REQUEST,request)
        request=json.loads(canonical(request))
        if (request['project_id'],request['data_mode'])!=(self.project_id,self.data_mode):
            raise Conflict('preparation request scope differs')
        key=intent_key(request)
        with self._lock:
            existing=self._existing(key,request)
            if existing is not None:return existing
            if len(self._materials)>=128:raise Conflict('preparation owner capacity reached')
            with self.store.read_connection() as db:
                db.execute('BEGIN');loaded=self._load(db,request['goal_ref'])
            sources=source_binding(loaded);proposal=loaded['record']['contract']['proposal']
            snapshot=self.builder.build()
            packet={'schema_version':'1.0','project_id':self.project_id,'data_mode':self.data_mode,
                'store_epoch':self.store_epoch,'goal_id':proposal['goal_id'],
                'contract_revision':sources['contract_revision'],'proposal_hash':sources['proposal_hash'],
                'approval_key':sources['approval_key'],'candidate_snapshot_hash':json.loads(snapshot.raw)['tree_hash'],
                'role':request['role'],'context':request['context']}
            plan=self.adapter.plan_preparation(packet,candidate=snapshot.path,
                write_roots=self._write_roots(proposal,snapshot,request['role']))
            bundle=self.adapter.build_preparation(plan)
            self.builder.verify(snapshot);self.adapter.verify_bundle(bundle)
            material=(snapshot,plan,bundle);self._materials[key]=material
            intent={'request':request,'request_hash':digest(request),'sources':sources,'plan':json.loads(plan.raw),
                'snapshot':json.loads(snapshot.raw),'snapshot_id':snapshot.id,'bundle':json.loads(bundle.raw),
                'created_at':sources['evaluated_at'],'accepted_state_version':sources['source_version']+1,
                'state':'INTENT','execution_enabled':False}
            self._append(SECTIONS[0],key,intent,material)
            self.adapter.publish_preparation(bundle)
            return self._finish(key,intent,material)

    def _finish(self,key,intent,material):
        snapshot,plan,bundle=material
        self.builder.verify(snapshot);self.adapter.verify_bundle(bundle)
        with self.store.read_connection() as db:
            db.execute('BEGIN');sources=source_binding(self._load(db,intent['sources']['goal_ref']))
        outcome={'intent_key':key,'intent_hash':digest(intent),'status':'PREPARED','reason':'MATERIAL_VERIFIED',
            'material':{'preparation_id':plan.id,'plan_hash':intent['bundle']['plan_hash'],
                        'manifest_hash':intent['bundle']['seal']['manifest_hash'],'execution_enabled':False},
            'sources':sources,'recorded_at':sources['evaluated_at'],'expected_state_version':sources['source_version'],
            'accepted_state_version':sources['source_version']+1,'execution_enabled':False}
        self._append(SECTIONS[1],result_key(key),outcome,material)
        return {'intent':intent,'result':outcome,'duplicate':False,'execution_enabled':False}

    def reconcile(self,request):
        """Explicit point retry. Unknown restart material is not adopted/rebuilt."""
        check_bytes(request,256*1024);validate_schema(REQUEST,request);request=json.loads(canonical(request))
        with self._lock:
            key=intent_key(request);existing=self._existing(key,request)
            if existing is None:raise Conflict('preparation intent missing; reconcile never builds')
            if existing['result'] is not None:return existing
            intent=existing['intent'];now=self._now().isoformat().replace('+00:00','Z')
            version=self.store.version()
            outcome={'intent_key':key,'intent_hash':digest(intent),'status':'UNKNOWN','reason':'RECONCILE_UNKNOWN',
                'material':None,'sources':None,'recorded_at':now,'expected_state_version':version,
                'accepted_state_version':version+1,'execution_enabled':False}
            self._append(SECTIONS[1],result_key(key),outcome,None)
            return {'intent':intent,'result':outcome,'duplicate':False,'execution_enabled':False}
