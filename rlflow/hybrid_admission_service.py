"""Protected same-writer admission observations; BLOCKED only, no release API."""
from contextlib import contextmanager
import json
import threading

from .hybrid_admission import (SECTION,EVENT,REQUEST,fact_key,gates,validate_record,validate_links)
from .hybrid_controller_service import ControllerService
from .hybrid_controller import SECTIONS as CONTROLLER, fact_key as controller_key
from .hybrid_preparation_service import PreparationService
from .hybrid_preparation import SECTIONS as PREPARATION, result_key,source_binding
from .hybrid_preparation_sources import historical_sources,load_sources
from .hybrid_reads import ReadBudget
from .hybrid_registry import Registry
from .hybrid_protocol import validate_schema
from .hybrid_goals import check_bytes,digest
from .hybrid_authority import timestamp
from .store import Store,Conflict,canonical,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,budget,token,witness,record,dependencies):
        self.owner,self.db,self.budget=owner,db,budget
        self.token,self.witness=token,witness;self.raw=canonical(record)
        self.dependencies=dependencies;self.thread=threading.get_ident()

    def check(self):
        self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key:
            return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        if key in self.dependencies.get(section,{}):return self.dependencies[section][key]
        value=self.budget.object(section,key)
        if value is not None:self.dependencies.setdefault(section,{})[key]=value
        return value


class AdmissionService:
    def __init__(self,store,registry,controller,preparation):
        if (type(store) is not Store or type(registry) is not Registry or
                type(controller) is not ControllerService or type(preparation) is not PreparationService or
                controller.store is not store or preparation.store is not store or
                controller.registry is not registry or preparation.registry is not registry):
            raise TypeError('fixed actual admission components required')
        self.store,self.registry,self.controller,self.preparation=store,registry,controller,preparation
        self.project_id,self.data_mode,self.store_epoch=controller.project_id,controller.data_mode,controller.store_epoch
        if (preparation.project_id,preparation.data_mode,preparation.store_epoch)!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('admission fixed owner scope differs')
        self._config_hash=registry.config_hash;self._active=None;self._lock=threading.RLock()
        store.bind_hybrid_admission(self)

    def _metadata(self,db):
        if self.store._hybrid_admission_service is not self or self.registry.config_hash!=self._config_hash:
            raise PermissionError('actual bound admission owner required')
        version=self.controller._metadata(db)
        if self.preparation._metadata(db)!=version:raise Conflict('admission owner versions differ')
        return version

    def _dependencies(self,db,value,budget):
        ref=value['preparation'];intent=self.preparation._original(db,PREPARATION[0],ref['intent_key'],budget)
        outcome=self.preparation._original(db,PREPARATION[1],ref['result_key'],budget)
        state=historical_sources(self.store,db,intent['sources'],budget)
        state[PREPARATION[0]]={ref['intent_key']:intent};state[PREPARATION[1]]={ref['result_key']:outcome}
        ck=value['controller']['fact_key'];control=self.controller._original(db,ck,budget)
        state[CONTROLLER[0]]={ck:control}
        validate_links(value,lambda s,k:state.get(s,{}).get(k))
        return state

    def _original(self,db,key,budget):
        value=budget.object(SECTION,key)
        if value is None:raise Conflict('admission original fact missing')
        validate_record(key,value)
        proof=self.store._admission_event(db,key,max_bytes=min(budget.remaining,256*1024),
                                         _parse=budget.parse,_decode=budget.decode)
        if proof!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(SECTION,key,digest(value))]):
            raise Conflict('admission original event differs')
        self._dependencies(db,value,budget)
        return value

    def _existing(self,request):
        key=fact_key(request)
        with self.store.read_connection() as db:
            db.execute('BEGIN');self._metadata(db)
            if not db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTION,key)).fetchone():return None
            value=self._original(db,key,ReadBudget(db,PREPARATION_READ_BYTES))
            if value['request']!=request:raise Conflict('admission idempotency key reused')
            return {'fact':value,'duplicate':True,'execution_enabled':False}

    def _load(self,db,goal_ref,budget):
        now,_=self.controller._sample()
        return source_binding(load_sources(self.store,db,self.registry,project_id=self.project_id,
            data_mode=self.data_mode,store_epoch=self.store_epoch,goal_ref=goal_ref,now=now,_budget=budget))

    def check_guard(self,db,guard):
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.budget.db is not db or guard.thread!=threading.get_ident()):
            raise PermissionError('actual active admission owner guard required')
        self._metadata(db)
        control=self.controller.check_token_in_transaction(db,guard.token,guard.budget)
        value=json.loads(guard.raw);expected={'fact_key':controller_key(control['request']),
            'fact_hash':digest(control),'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}
        if value['controller']!=expected:raise Conflict('admission differs from actual current controller token')
        ref=value['preparation'];intent=guard.lookup(PREPARATION[0],ref['intent_key']);outcome=guard.lookup(PREPARATION[1],ref['result_key'])
        observation=self.preparation.check_material_witness(guard.witness,intent,outcome)
        if (value['material_observation']!=observation or value['material_observation_monotonic']!={
                'boot_id':guard.witness.boot_id,'issued_ns':guard.witness.issued_monotonic_ns,
                'expires_ns':guard.witness.expires_monotonic_ns}):
            raise Conflict('admission differs from actual material observation')
        now,_=self.controller._sample()
        if not timestamp(value['sources']['evaluated_at'])<=now<timestamp(value['sources']['expires_at']):
            raise Conflict('admission consent expired or clock regressed before commit')

    def check_live_write(self,db,payload,guard):
        self.check_guard(db,guard);value=json.loads(guard.raw);key=fact_key(value['request'])
        if [(s,k,v) for s,k,v in payload['put'] if k]!=[(SECTION,key,value)]:
            raise Conflict('admission mutation differs from issued owner context')
        if value['request']['expected_state_version']!=self._metadata(db):raise Conflict('admission stale writer source version')
        current=self._load(db,value['sources']['goal_ref'],guard.budget)
        if any(current[n]!=v for n,v in value['sources'].items() if n!='evaluated_at'):
            raise Conflict('admission current source changed inside writer')
        validate_links(value,guard.lookup,current=True);guard.check()

    def admit(self,request,token,*,witness=None):
        """Actual checks and durable refusal, not an executable candidate lease."""
        self.controller._refuse_nested_writer();self.controller._issued(token)
        check_bytes(request,4096);validate_schema(REQUEST,request);request=json.loads(canonical(request))
        if (request['project_id'],request['data_mode'],request['store_epoch'])!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('admission request scope differs')
        if type(request['expected_state_version']) is not int:raise Conflict('actual admission version required')
        with self._lock:
            existing=self._existing(request)
            if existing is not None:return existing
            # Full file IO and Prep owner lock are outside the fixed writer.
            if witness is None:witness=self.preparation.issue_material_witness(request['preparation_intent_key'])
            # Keep the exact Admission guard active through the owned COMMIT.
            # This callback is internal Python, never an incoming authority field.
            with self._owned_transaction(token) as (db,budget,control):
                version=self._metadata(db)
                if request['expected_state_version']!=version:raise Conflict('admission stale expected version')
                tip=self.store._admission_tip(db,version)
                present=db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(SECTION,)).fetchone() is not None
                if present!=(tip is not None):raise Conflict('admission domain differs from original tip')
                ik=request['preparation_intent_key'];rk=result_key(ik)
                intent=self.preparation._original(db,PREPARATION[0],ik,budget)
                outcome=self.preparation._original(db,PREPARATION[1],rk,budget)
                observation=self.preparation.check_material_witness(witness,intent,outcome)
                sources=self._load(db,intent['sources']['goal_ref'],budget);_,mono=self.controller._sample()
                value={'schema_version':'1.0','request':request,'request_hash':digest(request),
                    'preparation':{'intent_key':ik,'intent_hash':digest(intent),'result_key':rk,'result_hash':digest(outcome)},
                    'controller':{'fact_key':controller_key(control['request']),'fact_hash':digest(control),
                        'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
                    'material_observation':observation,'material_observation_monotonic':{'boot_id':witness.boot_id,
                        'issued_ns':witness.issued_monotonic_ns,'expires_ns':witness.expires_monotonic_ns},
                    'sources':sources,'recorded_at':sources['evaluated_at'],'controller_checked_monotonic_ns':mono,
                    'accepted_state_version':version+1,'status':'BLOCKED','reason':'EXECUTION_GATES_UNVERIFIED',
                    'gates':gates(),'candidate_write_enabled':False,'release_enabled':False,'execution_enabled':False}
                key=fact_key(request);validate_record(key,value);dependencies=self._dependencies(db,value,budget)
                payload={'format':2,'put':[[SECTION,key,value]],'delete':[],'details':None}
                if not present:payload['put'].append([SECTION,'',{}])
                if self._active is not None:raise Conflict('nested admission transaction refused')
                guard=_Guard(self,db,budget,token,witness,value,dependencies);self._active=guard
                guard.check()
                self.store._commit(db,EVENT,key,payload,version,digest(value),'hybrid-core',{},_authorization=guard)
                guard.check()
                # token_transaction final check and owned COMMIT occur here;
                # no manual commit can release this owner/context prematurely.
            return {'fact':value,'duplicate':False,'execution_enabled':False}

    @contextmanager
    def _owned_transaction(self,token):
        def final_check():
            if self._active is None:raise PermissionError('actual final admission guard missing')
            self._active.check()
        if self._active is not None:raise Conflict('nested admission owner transaction refused')
        try:
            with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                                                   _before_commit=final_check) as context:
                yield context
        finally:self._active=None
