"""Protected PRE_RUNTIME workspace facts. No writer registration or release.

Copy outside writer, persist original-source-bound hold, request close, physically
close, then attest completion. Failed commit retains the actual capability.
Renewal is deliberately refused pending transactional observation activation.
"""
from contextlib import contextmanager
import json
import threading

from .hybrid_workspace import (SECTIONS,EVENT,REQUEST,fact_key,head_key,head,claim_key,claim,
    expected_objects,event_inputs,validate_record,validate_links)
from .hybrid_working_copy import WorkingCopyOwner,WorkingCopyObservation
from .hybrid_controller_service import ControllerService
from .hybrid_controller import SECTIONS as CONTROLLER,fact_key as controller_key
from .hybrid_preparation_service import PreparationService
from .hybrid_preparation import SECTIONS as PREPARATION,source_binding
from .hybrid_preparation_sources import historical_sources
from .hybrid_budget_service import BudgetService
from .hybrid_budget_ledger import SECTIONS as BUDGET
from .hybrid_registry import Registry
from .hybrid_reads import ReadBudget
from .hybrid_protocol import validate_schema,ID
from .hybrid_goals import check_bytes,digest
from .hybrid_authority import timestamp
from .store import Store,Conflict,canonical,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,budget,token,value,slot,dependencies):
        self.owner,self.db,self.budget,self.token=owner,db,budget,token
        self.raw=canonical(value);self.slot=slot;self.dependencies=dependencies;self.thread=threading.get_ident()

    def check(self):self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key:return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        # Immutable facts only; mutable heads MUST be read from this writer.
        if key in self.dependencies.get(section,{}):return self.dependencies[section][key]
        return self.budget.object(section,key)


class WorkspaceService:
    def __init__(self,store,registry,controller,preparation,budget,working):
        if (type(store) is not Store or type(registry) is not Registry or
                type(controller) is not ControllerService or type(preparation) is not PreparationService or
                type(budget) is not BudgetService or type(working) is not WorkingCopyOwner or
                controller.store is not store or preparation.store is not store or budget.store is not store or
                controller.registry is not registry or preparation.registry is not registry or budget.registry is not registry or
                budget.controller is not controller or budget.preparation is not preparation or working.builder is not preparation.builder or
                working._owner!=controller.owner['process']):
            raise TypeError('fixed actual workspace components required')
        self.store,self.registry,self.controller,self.preparation,self.budget,self.working=store,registry,controller,preparation,budget,working
        self.project_id,self.data_mode,self.store_epoch=controller.project_id,controller.data_mode,controller.store_epoch
        self._config_hash=registry.config_hash;self._active=None;self._slots={};self._lock=threading.RLock()
        store.bind_hybrid_workspace(self)

    def _metadata(self,db):
        if self.store._hybrid_workspace_service is not self or self.registry.config_hash!=self._config_hash:
            raise PermissionError('actual bound workspace owner required')
        return self.budget._metadata(db)

    def stage(self,intent_key,*,ttl_seconds=30):
        """Actual material/copy IO OUTSIDE Store writer; not execution authority."""
        self.controller._refuse_nested_writer();validate_schema(ID,intent_key)
        witness=self.preparation.issue_material_witness(intent_key)
        observation=self.working.acquire(witness.materials[0],ttl_seconds=ttl_seconds)
        value=json.loads(observation.raw)
        with self._lock:
            self._slots[value['workspace_id']]={'observation':observation,'witness':witness,'closed':None}
        return observation

    def _issued(self,observation):
        if type(observation) is not WorkingCopyObservation:raise PermissionError('actual staged working observation required')
        with self._lock:
            slot=next((slot for slot in self._slots.values() if slot['observation'] is observation),None)
            if slot is None:raise PermissionError('actual original workspace stage required')
            return slot,json.loads(observation.raw)

    def _point(self,db,key,budget):
        value=budget.object(SECTIONS[0],key)
        if value is None:raise Conflict('workspace original fact missing')
        validate_record(SECTIONS[0],key,value)
        proof=self.store._workspace_event(db,key,max_bytes=min(budget.remaining,1024**2),_parse=budget.parse,_decode=budget.decode)
        if proof!=((EVENT,'hybrid-core',value['request']['reservation_id'],value['accepted_state_version']),expected_objects(value)):
            raise Conflict('workspace original event differs')
        return value

    def _current(self,db,request,budget,version):
        tip=self.store._workspace_tip(db,version,reservation_id=request['reservation_id'])
        current=budget.object(SECTIONS[1],head_key(request))
        if (current is None)!=(tip is None):raise Conflict('workspace current head missing or unexpected')
        if current is not None:
            validate_record(SECTIONS[1],head_key(request),current)
            if (current['fact_key'],current['accepted_state_version'])!=tip or head(self._point(db,tip[0],budget))!=current:
                raise Conflict('workspace current head differs from indexed original tip')
        global_tip=self.store._workspace_tip(db,version)
        if any((db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(s,)).fetchone() is not None)!=(global_tip is not None) for s in SECTIONS):
            raise Conflict('workspace domain differs from original tip')
        return current

    def _dependencies(self,db,value,budget):
        state=historical_sources(self.store,db,value['sources'],budget)
        reservation=value['budget_reservation'];original=self.budget._point(db,reservation['last_entry_key'],budget)
        for section,objects in self.budget._dependencies(db,original,budget).items():state.setdefault(section,{}).update(objects)
        state.setdefault(BUDGET[0],{})[reservation['last_entry_key']]=original
        cr=value['controller'];state.setdefault(CONTROLLER[0],{})[cr['fact_key']]=self.controller._original(db,cr['fact_key'],budget)
        prior=value['prior_head']
        if prior is not None:state.setdefault(SECTIONS[0],{})[prior['fact_key']]=self._point(db,prior['fact_key'],budget)
        original_claim=budget.object(SECTIONS[2],claim_key(value['request']))
        if original_claim is not None:
            validate_record(SECTIONS[2],claim_key(value['request']),original_claim)
            acquired=self._point(db,original_claim['origin_fact_key'],budget)
            if claim(acquired)!=original_claim:raise Conflict('workspace original claim differs')
            state.setdefault(SECTIONS[2],{})[claim_key(value['request'])]=original_claim
            state.setdefault(SECTIONS[0],{})[original_claim['origin_fact_key']]=acquired
        validate_links(value,lambda s,k:state.get(s,{}).get(k))
        return state

    def _existing(self,request):
        key=fact_key(request)
        with self.store.read_connection() as db:
            db.execute('BEGIN');self._metadata(db)
            if not db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],key)).fetchone():return None
            budget=ReadBudget(db,PREPARATION_READ_BYTES);value=self._point(db,key,budget);self._dependencies(db,value,budget)
            if value['request']!=request:raise Conflict('workspace idempotency key reused')
            return {'fact':value,'duplicate':True,'execution_enabled':False,'release_enabled':False}

    def _actual(self,value,slot):
        observation=slot['observation'];record=json.loads(observation.raw)
        if (value['observation']!=record or value['observation_issued_monotonic_ns']!=observation.issued_monotonic_ns or
                value['observation_expires_monotonic_ns']!=observation.expires_monotonic_ns):
            raise Conflict('workspace differs from actual original observation')
        operation=value['request']['operation']
        if operation=='acquire':
            self.working.check(observation)
            witness=slot['witness'];ref=value['preparation']
            intent=slot['dependencies'][PREPARATION[0]][ref['intent_key']]
            outcome=slot['dependencies'][PREPARATION[1]][ref['result_key']]
            self.preparation.check_material_witness(witness,intent,outcome)
            if witness.materials[0].id!=record['base_snapshot_id']:raise Conflict('workspace actual material snapshot differs')
        elif operation=='request_close':
            # Cleanup need not grant a currently-live TTL/path. Identity of
            # the original no-handoff slot remains mandatory.
            self.working._owner_check();self.working._slot(observation)
        elif operation=='complete_close':
            witness=slot['closed']
            if witness is None or witness.observation is not observation or self.working.check_closed_witness(witness)!=value['physical_close']:
                raise PermissionError('actual original physical close success required')
        else:raise Conflict('workspace renewal not yet enabled')

    def check_guard(self,db,guard):
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.budget.db is not db or guard.thread!=threading.get_ident()):
            raise PermissionError('actual active workspace owner guard required')
        version=self._metadata(db);control=self.controller.check_token_in_transaction(db,guard.token,guard.budget)
        value=json.loads(guard.raw);request=value['request']
        if version not in (request['expected_state_version'],value['accepted_state_version']):raise Conflict('workspace writer version changed')
        if value['controller']!={'fact_key':controller_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}:
            raise Conflict('workspace differs from actual current controller')
        if request['operation']=='acquire':
            current=source_binding(self.budget._load(db,request['goal_ref'],guard.budget))
            if any(current[n]!=v for n,v in value['sources'].items() if n not in ('source_version','evaluated_at')):
                raise Conflict('workspace current consent changed')
            _,reservation,_=self.budget._heads(db,{**request,'action':'MARK_UNKNOWN'},guard.budget,version)
            if reservation!=value['budget_reservation']:raise Conflict('workspace current budget reservation changed')
        self._actual(value,guard.slot)
        if version==value['accepted_state_version']:
            if self._point(db,fact_key(request),guard.budget)!=value or self._current(db,request,guard.budget,version)!=head(value):
                raise Conflict('workspace final fact/head changed')
            original_claim=guard.budget.object(SECTIONS[2],claim_key(request))
            acquired=value if request['operation']=='acquire' else self._point(db,original_claim['origin_fact_key'],guard.budget)
            if original_claim!=claim(acquired):raise Conflict('workspace final immutable claim changed')

    def check_live_write(self,db,payload,inputs,guard):
        self.check_guard(db,guard);value=json.loads(guard.raw);request=value['request']
        expected={(SECTIONS[0],fact_key(request)):value,(SECTIONS[1],head_key(request)):head(value)}
        if request['operation']=='acquire':expected[(SECTIONS[2],claim_key(request))]=claim(value)
        if {(s,k):v for s,k,v in payload['put'] if k}!=expected or inputs!=event_inputs(value):raise Conflict('workspace mutation differs from issued context')
        version=self._metadata(db)
        if version!=request['expected_state_version'] or self._current(db,request,guard.budget,version)!=value['prior_head']:
            raise Conflict('workspace stale prior version/head')
        validate_links(value,guard.lookup,current=True)

    @contextmanager
    def _owned_transaction(self,token):
        def final_check():
            if self._active is None:raise PermissionError('actual final workspace guard missing')
            self._active.check()
        def final_deadlines(now,mono):
            value=json.loads(self._active.raw)
            if now<timestamp(value['recorded_at']):raise Conflict('workspace final clock regressed')
            if value['request']['operation']=='acquire':
                observation=self._active.slot['observation'];working_now,elapsed=self.working._sample()
                witness=self._active.slot['witness'];material_now,material_elapsed=self.preparation._witness_sample()
                final_now=max(now,working_now,material_now);material=json.loads(witness.raw)
                if (not timestamp(value['observation']['checked_at'])<=final_now<timestamp(value['observation']['expires_at']) or
                        final_now>=timestamp(value['sources']['expires_at']) or
                        not observation.issued_monotonic_ns<=elapsed<observation.expires_monotonic_ns or
                        not witness.issued_monotonic_ns<=material_elapsed<witness.expires_monotonic_ns or
                        not timestamp(material['checked_at'])<=material_now<timestamp(material['expires_at']) or
                        final_now>=timestamp(material['expires_at'])):
                    raise Conflict('workspace consent/material/hold expired at final owned commit')
        def clear_active():self._active=None
        with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                _before_commit=final_check,_after_final_sample=final_deadlines,_on_exit=clear_active) as context:
            # Lock AFTER actual writer acquisition; stage/copy never waits
            # for Store while holding this lock or WorkingCopyOwner lock.
            with self._lock:
                if self._active is not None:raise Conflict('nested workspace transaction refused')
                yield context

    def record(self,request,token,observation):
        self.controller._refuse_nested_writer();self.controller._issued(token)
        check_bytes(request,8192);validate_schema(REQUEST,request);request=json.loads(canonical(request))
        if (request['project_id'],request['data_mode'],request['store_epoch'])!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('workspace request scope differs')
        if request['operation']=='renew':raise Conflict('workspace renewal not yet enabled')
        existing=self._existing(request)
        if existing is not None:
            if request['operation']=='complete_close':self._retire_completed(existing['fact'],observation)
            return existing # Historical receipt, never current ability.
        slot,record=self._issued(observation)
        if request['workspace_id']!=record['workspace_id']:raise Conflict('workspace actual stage differs')
        with self._owned_transaction(token) as (db,read,control):
            version=self._metadata(db)
            if version!=request['expected_state_version']:raise Conflict('workspace stale expected version')
            prior=self._current(db,request,read,version)
            if request['operation']=='acquire':
                sources=source_binding(self.budget._load(db,request['goal_ref'],read))
                _,reservation,_=self.budget._heads(db,{**request,'action':'MARK_UNKNOWN'},read,version)
                if reservation is None:raise Conflict('workspace requires original HELD reservation')
                ref=reservation['preparation'];closed=None
            else:
                if prior is None:raise Conflict('workspace original head required')
                previous=self._point(db,prior['fact_key'],read)
                sources,reservation,ref=previous['sources'],previous['budget_reservation'],previous['preparation']
                closed=self.working.check_closed_witness(slot['closed']) if request['operation']=='complete_close' and slot['closed'] is not None else None
            now,mono=self.controller._sample()
            value={'request':request,'request_hash':digest(request),'sources':sources,'preparation':ref,
                'budget_reservation':reservation,'controller':{'fact_key':controller_key(control['request']),
                    'fact_hash':digest(control),'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
                'observation':record,'observation_issued_monotonic_ns':observation.issued_monotonic_ns,
                'observation_expires_monotonic_ns':observation.expires_monotonic_ns,'physical_close':closed,
                'controller_checked_monotonic_ns':mono,'recorded_at':now.isoformat().replace('+00:00','Z'),
                'prior_head':prior,'state':{'acquire':'HELD_PRE_RUNTIME','request_close':'CLOSE_REQUESTED','complete_close':'CLOSED_PRE_RUNTIME'}[request['operation']],
                'accepted_state_version':version+1,'execution_enabled':False,'release_enabled':False}
            key=fact_key(request);validate_record(SECTIONS[0],key,value)
            dependencies=self._dependencies(db,value,read);slot['dependencies']=dependencies
            if slot['witness'].materials[0].id!=record['base_snapshot_id'] or json.loads(slot['witness'].raw)['intent_key']!=ref['intent_key']:
                raise Conflict('workspace stage belongs to another original preparation')
            payload={'format':2,'put':[[SECTIONS[0],key,value],[SECTIONS[1],head_key(request),head(value)]],'delete':[],'details':None}
            if request['operation']=='acquire':payload['put'].append([SECTIONS[2],claim_key(request),claim(value)])
            payload['put'].extend([s,'',{}] for s in SECTIONS if not db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(s,)).fetchone())
            guard=_Guard(self,db,read,token,value,slot,dependencies);self._active=guard;guard.check()
            self.store._commit(db,EVENT,key,payload,version,request['reservation_id'],'hybrid-core',event_inputs(value),_authorization=guard)
            guard.check()
        if request['operation']=='complete_close':
            self._retire_completed(value,observation)
        return {'fact':value,'duplicate':False,'execution_enabled':False,'release_enabled':False}

    def _retire_completed(self,value,observation):
        """Retry memory ACK after durable CLOSED; never rebuild a capability.

        Historical duplicate without the actual retained slot remains ONLY a
        receipt. A failure before/after witness retirement must not permanently
        exhaust bounded owner slots after successful physical/durable close.
        """
        with self._lock:
            if type(observation) is not WorkingCopyObservation:return
            slot=next((slot for slot in self._slots.values() if slot['observation'] is observation),None)
            if slot is None:return
            witness=slot['closed']
            if (value['state']!='CLOSED_PRE_RUNTIME' or witness is None or witness.observation is not observation or
                    value['observation']!=json.loads(observation.raw) or value['physical_close']!=json.loads(witness.raw)):
                raise Conflict('durable close memory acknowledgement differs from actual retained witness')
            self.working._owner_check()
            retained=self.working._closed_witnesses.get(witness.id)
            if retained is not None:
                if retained is not witness:raise Conflict('actual closed witness identity changed')
                self.working.retire_closed_witness(witness)
            # Absence here means a previous ACK retired THIS already-known
            # service witness; it never means a JSON/disk witness was adopted.
            self._slots.pop(value['request']['workspace_id'],None)

    def close_physical_pre_runtime(self,close_request_key,observation):
        """Durable CLOSE_REQUESTED first; finite physical cleanup outside writer."""
        self.controller._refuse_nested_writer();validate_schema(ID,close_request_key)
        slot,record=self._issued(observation)
        with self.store.read_connection() as db:
            db.execute('BEGIN');version=self._metadata(db);read=ReadBudget(db,PREPARATION_READ_BYTES)
            value=self._point(db,close_request_key,read);self._dependencies(db,value,read)
            if (value['state']!='CLOSE_REQUESTED' or value['request']['workspace_id']!=record['workspace_id'] or
                    value['observation']!=record or self._current(db,value['request'],read,version)!=head(value)):
                raise Conflict('actual current original CLOSE_REQUESTED required')
        with self._lock:
            if slot['closed'] is None:slot['closed']=self.working.close_pre_runtime(observation)
            return slot['closed']
