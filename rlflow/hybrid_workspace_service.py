"""Protected PRE_RUNTIME workspace facts. No writer registration or release.

Copy outside writer, persist original-source-bound hold, request close, physically
close, then attest completion. Failed commit retains the actual capability.
Renewal uses original pending objects, held-COMMIT activation and explicit ACK.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
import json
import threading

from .hybrid_workspace import (SECTIONS,EVENT,REQUEST,fact_key,head_key,head,claim_key,claim,
    expected_objects,event_inputs,validate_record,validate_links)
from .hybrid_working_copy import WorkingCopyOwner,WorkingCopyObservation,PendingRenewal
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


@dataclass(frozen=True, eq=False)
class _PlanContext:
    """Actual held writer observation; no DTO adoption or execution permit."""
    owner: object
    db: object
    read: object
    token: object
    observation: object
    material_witness: object
    bootstrap: object
    raw: bytes
    thread: int
    plan_witness: object = None


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
        self._plan_active=None
        store.bind_hybrid_workspace(self)

    def _plan_sources(self, owner, db, read, token, observation, material_witness, bootstrap):
        """Current full original sources in the ONE owned Controller database."""
        from .hybrid_working_plan_service import WorkingPlanService
        active=self.controller._token_active
        if (type(owner) is not WorkingPlanService or owner.workspace is not self or
                self.store._hybrid_working_plan_service is not owner or
                owner.installation.store is not self.store):
            raise PermissionError('fixed actual Working plan owner required')
        if (active is None or active[0] is not db or active[1] is not token or active[2] is not read or
                active[3]!=threading.get_ident() or type(read) is not ReadBudget or read.db is not db or
                not db.in_transaction):
            raise PermissionError('actual owned Controller plan writer required')
        version=self._metadata(db);control=self.controller.check_token_in_transaction(db,token,read)
        slot,record=self._issued(observation)
        if slot['closed'] is not None or self._unresolved_renewal(slot):
            raise Conflict('plan requires original live workspace without pending renewal')
        working_slot,_=self.working._slot(observation)
        self.working.check(observation)
        request={'project_id':self.project_id,'data_mode':self.data_mode,'workspace_id':record['workspace_id']}
        original_claim=read.object(SECTIONS[2],claim_key(request))
        if original_claim is None:raise Conflict('plan original durable workspace claim missing')
        validate_record(SECTIONS[2],claim_key(request),original_claim)
        acquired=self._point(db,original_claim['origin_fact_key'],read)
        if acquired['request']['operation']!='acquire' or claim(acquired)!=original_claim:
            raise Conflict('plan original workspace acquire claim differs')
        current=self._current(db,acquired['request'],read,version)
        if current is None or current['state']!='HELD_PRE_RUNTIME':
            raise Conflict('plan requires current HELD_PRE_RUNTIME workspace head')
        fact=self._point(db,current['fact_key'],read);self._dependencies(db,fact,read)
        if (fact['observation']!=record or fact['observation_issued_monotonic_ns']!=observation.issued_monotonic_ns or
                fact['observation_expires_monotonic_ns']!=observation.expires_monotonic_ns or
                fact['request']['workspace_id']!=record['workspace_id']):
            raise Conflict('plan actual current Working observation differs from durable head')
        sources=source_binding(self.budget._load(db,fact['request']['goal_ref'],read))
        if any(sources[n]!=v for n,v in fact['sources'].items() if n not in ('source_version','evaluated_at')):
            raise Conflict('plan current Goal approval or Registry source changed')
        _,reservation,_=self.budget._heads(db,{**fact['request'],'action':'MARK_UNKNOWN'},read,version)
        if (reservation is None or reservation['status']!='HELD' or
                reservation['runtime_registration']!='NOT_AUTHORIZED' or reservation!=fact['budget_reservation']):
            raise Conflict('plan requires exact current HELD NOT_AUTHORIZED budget reservation')
        entry=self.budget._point(db,reservation['last_entry_key'],read);self.budget._dependencies(db,entry,read)
        ref=fact['preparation']
        intent=self.preparation._original(db,PREPARATION[0],ref['intent_key'],read)
        outcome=self.preparation._original(db,PREPARATION[1],ref['result_key'],read)
        self.preparation._historical(db,ref['intent_key'],intent,outcome,read)
        self.preparation.check_material_witness(material_witness,intent,outcome)
        if (material_witness.materials[0] is not working_slot['base'] or
                json.loads(material_witness.raw)['intent_key']!=ref['intent_key'] or
                reservation['preparation']!=ref):
            raise Conflict('plan fresh original preparation differs from actual Working base')
        bootstrap_ref=owner.installation._bootstrap_point(db,bootstrap,read)
        if bootstrap.material is not owner.material:
            raise Conflict('plan bootstrap differs from original fixed owner material')
        result={'project_id':self.project_id,'data_mode':self.data_mode,'store_epoch':self.store_epoch,
            'sources':sources,'preparation':ref,'workspace_head':current,'workspace_claim':original_claim,
            'budget_reservation':reservation,'controller':{'fact_key':controller_key(control['request']),
                'fact_hash':digest(control),'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
            'observation':record,'observation_issued_monotonic_ns':observation.issued_monotonic_ns,
            'observation_expires_monotonic_ns':observation.expires_monotonic_ns,'bootstrap':bootstrap_ref}
        if self.data_mode=='live':result['domain_profile']=bootstrap_ref['domain_profile']
        return result

    def _check_plan_context(self,context):
        if (type(context) is not _PlanContext or self._plan_active is not context or
                context.owner._context is not context or context.thread!=threading.get_ident()):
            raise PermissionError('actual active original Working plan context required')
        current=self._plan_sources(context.owner,context.db,context.read,context.token,context.observation,
            context.material_witness,context.bootstrap)
        expected=json.loads(context.raw)
        # Evaluation time/version are as-of metadata, not a refreshed lease.
        for value in (current,expected):
            for key in ('source_version','evaluated_at'):value['sources'].pop(key)
        if current!=expected:raise Conflict('original Working plan current context changed')
        if context.plan_witness is not None:context.plan_witness.check()

    @contextmanager
    def _plan_context(self,owner,token,observation,material_witness,bootstrap,*,plan_witness=None):
        """Protected source-only context; fixed owner, no arbitrary callbacks.

        Lock order: Store -> Controller -> Workspace -> Working -> Plan ->
        Installation -> Builder. Every lock covers the actual owned COMMIT.
        No file hash/copy or witness issuance is performed under this writer.
        """
        from .hybrid_working_plan_service import WorkingPlanService
        if (type(owner) is not WorkingPlanService or owner.workspace is not self or
                getattr(self.store,'_hybrid_working_plan_service',None) is not owner):
            raise PermissionError('fixed original Working plan context owner required')
        if plan_witness is not None:
            from .hybrid_working_plan_materials import _WorkingPlanWitness
            if type(plan_witness) is not _WorkingPlanWitness or plan_witness.builder is not owner.builder:
                raise PermissionError('actual original plan material witness required')
            plan_witness.check()
        def before_commit():
            self._check_plan_context(self._plan_active)
            if plan_witness is not None:owner._final_fact(self._plan_active)
        def final_deadlines(now,mono):
            context=self._plan_active;raw=json.loads(context.raw)
            working_now,working_mono=self.working._sample()
            material_now,material_mono=self.preparation._witness_sample()
            witness=context.material_witness;proof=json.loads(witness.raw);observation=context.observation
            final_now=max(now,working_now,material_now)
            if (not timestamp(raw['observation']['checked_at'])<=final_now<timestamp(raw['observation']['expires_at']) or
                    final_now>=timestamp(raw['sources']['expires_at']) or
                    not observation.issued_monotonic_ns<=working_mono<observation.expires_monotonic_ns or
                    not timestamp(proof['checked_at'])<=final_now<timestamp(proof['expires_at']) or
                    not witness.issued_monotonic_ns<=material_mono<witness.expires_monotonic_ns):
                raise Conflict('Working plan sources expired at final owned commit')
            from .hybrid_fixture_materials import _deadline
            _deadline(context.bootstrap.inventory.deadline)
            if context.plan_witness is not None:_deadline(context.plan_witness.deadline)
        def clear():
            self._plan_active=None;owner._context=None
            owner._active=None;owner._publication_pending=None
        def committed():
            owner._publication_committed(self._plan_active)
        @contextmanager
        def held():
            with self._lock,self.working._lock,owner._lock,owner.installation._lock,owner.installation.builder._lock:
                if self._plan_active is not None or owner._context is not None:
                    raise Conflict('nested Working plan context refused')
                yield
        with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                _before_commit=before_commit,_after_final_sample=final_deadlines,_on_exit=clear,
                _commit_context=held,_after_commit=committed) as (db,read,control):
            raw=self._plan_sources(owner,db,read,token,observation,material_witness,bootstrap)
            context=_PlanContext(owner,db,read,token,observation,material_witness,bootstrap,canonical(raw),threading.get_ident(),plan_witness)
            self._plan_active=context;owner._context=context
            yield context

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
            self._slots[value['workspace_id']]={'observation':observation,'witness':witness,'closed':None,
                                                'renewal':None,'renewal_ack':None}
        return observation

    def prepare_renewal(self,observation,*,ttl_seconds=30):
        """Preallocate actual candidate outside writer; no durable/live grant."""
        self.controller._refuse_nested_writer();self.working._ttl(ttl_seconds)
        with self._lock:
            original,_=self._issued(observation)
            intent_key=json.loads(original['witness'].raw)['intent_key']
            existing=original['renewal']
        # Reverify original fixed materials OUTSIDE writer and service/Working
        # locks. A long-running renewal chain cannot reuse stage's30s witness.
        fresh=self.preparation.issue_material_witness(intent_key) if existing is None else None
        with self._lock,self.working._lock:
            slot,_=self._issued(observation)
            if slot['closed'] is not None:raise Conflict('closed workspace cannot renew')
            entry=slot['renewal']
            if entry is None:
                if fresh is None:raise Conflict('pending renewal changed; fresh preparation retry required')
                # Recover ONLY original actual-slot lost-return attachment,
                # never a candidate from an ID/path/JSON/history.
                pending=self.working.pending_renewal(observation)
                if pending is None:pending=self.working.prepare_renewal(observation,ttl_seconds=ttl_seconds)
                entry={'pending':pending,'witness':fresh,'request':None,'fact':None,'committed':False}
                slot['renewal']=entry
            pending=entry['pending'];raw=json.loads(pending.candidate.raw)
            if timestamp(raw['expires_at'])-timestamp(raw['checked_at'])!=timedelta(seconds=ttl_seconds):
                raise Conflict('original pending renewal TTL differs')
            return pending

    def _renewal_slot(self,pending,*,allow_ack=False):
        if type(pending) is not PendingRenewal:raise PermissionError('actual staged pending renewal required')
        slot=next((slot for slot in self._slots.values() if slot['renewal'] is not None and
                   slot['renewal']['pending'] is pending),None)
        if slot is None and allow_ack:
            slot=next((slot for slot in self._slots.values() if slot['renewal'] is None and
                       slot['renewal_ack'] is not None and slot['renewal_ack']['pending'] is pending),None)
            if slot is not None:return slot,slot['renewal_ack']
        if slot is None:raise PermissionError('actual original workspace renewal required')
        return slot,slot['renewal']

    def _unresolved_renewal(self,slot):
        """Working canonical attach may survive a lost Service prepare return."""
        with self._lock,self.working._lock:
            observation=slot['observation']
            return slot['renewal'] is not None or any(
                row['pending'].previous is observation or row['pending'].candidate is observation
                for row in self.working._renewals.values())

    def _activate_renewal(self,slot,entry):
        """Memory-only original candidate swap/ACK; partial return retryable."""
        pending=entry['pending']
        if slot['renewal'] is not None and slot['renewal'] is not entry:
            raise Conflict('another actual renewal is unresolved')
        retained=any(row['pending'] is pending for row in self.working._renewals.values())
        if retained:self.working._activate_renewal(pending)
        else:
            # Prior ACK may have retired Working's SINGLE canonical entry
            # before its return failed. Require actual current candidate.
            working,_=self.working._slot(pending.candidate)
            if self.working._pending_for_slot(working) is not None:raise Conflict('another working renewal is unresolved')
        slot['observation']=pending.candidate
        slot['witness']=entry['witness']
        if retained:self.working._retire_renewal(pending)
        slot['renewal_ack']=entry
        slot['renewal']=None

    def ack_renewal(self,key,pending):
        """Original durable event + original retained pending, never new TTL."""
        self.controller._refuse_nested_writer();validate_schema(ID,key)
        with self.store.lock(),self._lock,self.working._lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');version=self._metadata(db)
            slot,entry=self._renewal_slot(pending,allow_ack=True)
            request=entry['request'];expected=entry['fact']
            if request is None or expected is None or fact_key(request)!=key:
                raise Conflict('renewal original attempted request/fact required')
            read=ReadBudget(db,PREPARATION_READ_BYTES);value=self._point(db,key,read)
            self._dependencies(db,value,read)
            if (value!=expected or value['request']!=request or value['request']['operation']!='renew' or
                    self._current(db,request,read,version)!=head(value) or
                    value['observation']!=json.loads(pending.candidate.raw) or
                    value['observation_issued_monotonic_ns']!=pending.candidate.issued_monotonic_ns or
                    value['observation_expires_monotonic_ns']!=pending.candidate.expires_monotonic_ns):
                raise Conflict('renewal ACK differs from original durable candidate')
            if any(row['pending'] is pending for row in self.working._renewals.values()):
                self.working.check_renewal(pending,live=False)
            else:
                self.working._owner_check();working,_=self.working._slot(pending.candidate)
                self.working._namespace_check()
                if working['hold'].check()!=working['binding']['kernel']:raise Conflict('renewal ACK Kernel changed')
            # Read proof only. No authority write/automatic fresh observation.
            db.rollback();entry['committed']=True;self._activate_renewal(slot,entry)
            return pending.candidate

    def abort_renewal(self,pending):
        """Explicit definite no-COMMIT proof; never abort unknown/durable renew."""
        self.controller._refuse_nested_writer()
        with self.store.lock(),self._lock,self.working._lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');version=self._metadata(db)
            slot,entry=self._renewal_slot(pending);request=entry['request']
            if entry['committed']:raise Conflict('durable renewal cannot abort')
            if request is not None:
                read=ReadBudget(db,PREPARATION_READ_BYTES);key=fact_key(request)
                if db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],key)).fetchone():
                    raise Conflict('renewal event exists; explicit ACK required')
                if db.execute('SELECT 1 FROM events WHERE idempotency_key=?',(key,)).fetchone():
                    raise Conflict('renewal event exists without projection')
                prior=self._current(db,request,read,version)
                if prior is None:raise Conflict('renewal original prior head missing')
                previous=self._point(db,prior['fact_key'],read);self._dependencies(db,previous,read)
                if (previous['observation']!=json.loads(pending.previous.raw) or
                        previous['observation_issued_monotonic_ns']!=pending.previous.issued_monotonic_ns or
                        previous['observation_expires_monotonic_ns']!=pending.previous.expires_monotonic_ns or
                        entry['fact'] is not None and prior!=entry['fact']['prior_head']):
                    raise Conflict('renewal original prior lineage changed')
            db.rollback()
            retained=any(row['pending'] is pending for row in self.working._renewals.values())
            if retained:self.working.abort_renewal(pending)
            else:self.working._slot(pending.previous)
            slot['renewal']=None
            return pending.previous

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
        operation=value['request']['operation']
        if operation!='renew' and self._unresolved_renewal(slot):raise Conflict('workspace has unresolved renewal')
        observation=slot['renewal']['pending'].candidate if operation=='renew' else slot['observation']
        record=json.loads(observation.raw)
        if (value['observation']!=record or value['observation_issued_monotonic_ns']!=observation.issued_monotonic_ns or
                value['observation_expires_monotonic_ns']!=observation.expires_monotonic_ns):
            raise Conflict('workspace differs from actual original observation')
        if operation in ('acquire','renew'):
            if operation=='renew':
                pending=slot['renewal']['pending'];self.working.check_renewal(pending)
                previous=slot['dependencies'][SECTIONS[0]][value['prior_head']['fact_key']]
                if (previous['observation']!=json.loads(pending.previous.raw) or
                        previous['observation_issued_monotonic_ns']!=pending.previous.issued_monotonic_ns or
                        previous['observation_expires_monotonic_ns']!=pending.previous.expires_monotonic_ns):
                    raise Conflict('renewal original actual predecessor differs')
            else:self.working.check(observation)
            witness=slot['renewal']['witness'] if operation=='renew' else slot['witness'];ref=value['preparation']
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
        if request['operation'] in ('acquire','renew'):
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
    def _owned_transaction(self,token,renewal=None):
        def final_check():
            if self._active is None:raise PermissionError('actual final workspace guard missing')
            self._active.check()
        def final_deadlines(now,mono):
            value=json.loads(self._active.raw)
            if now<timestamp(value['recorded_at']):raise Conflict('workspace final clock regressed')
            if value['request']['operation'] in ('acquire','renew'):
                slot=self._active.slot
                observation=slot['renewal']['pending'].candidate if value['request']['operation']=='renew' else slot['observation']
                working_now,elapsed=self.working._sample()
                witness=slot['renewal']['witness'] if value['request']['operation']=='renew' else slot['witness']
                material_now,material_elapsed=self.preparation._witness_sample()
                final_now=max(now,working_now,material_now);material=json.loads(witness.raw)
                if (not timestamp(value['observation']['checked_at'])<=final_now<timestamp(value['observation']['expires_at']) or
                        final_now>=timestamp(value['sources']['expires_at']) or
                        not observation.issued_monotonic_ns<=elapsed<observation.expires_monotonic_ns or
                        not witness.issued_monotonic_ns<=material_elapsed<witness.expires_monotonic_ns or
                        not timestamp(material['checked_at'])<=material_now<timestamp(material['expires_at']) or
                        final_now>=timestamp(material['expires_at'])):
                    raise Conflict('workspace consent/material/hold expired at final owned commit')
                if value['request']['operation']=='renew':
                    previous=slot['renewal']['pending'].previous;old=json.loads(previous.raw)
                    if (not timestamp(old['checked_at'])<=final_now<timestamp(old['expires_at']) or
                            not previous.issued_monotonic_ns<=elapsed<previous.expires_monotonic_ns):
                        raise Conflict('workspace old observation expired at final renewal commit')
        def clear_active():self._active=None
        @contextmanager
        def held_context():
            with self._lock,self.working._lock:
                if self._active is not None:raise Conflict('nested workspace transaction refused')
                yield
        def activate():
            slot,entry=renewal;entry['committed']=True;self._activate_renewal(slot,entry)
        with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                _before_commit=final_check,_after_final_sample=final_deadlines,_on_exit=clear_active,
                _commit_context=held_context,_after_commit=activate if renewal is not None else None) as context:
            yield context

    def record(self,request,token,observation):
        self.controller._refuse_nested_writer();self.controller._issued(token)
        check_bytes(request,8192);validate_schema(REQUEST,request);request=json.loads(canonical(request))
        if (request['project_id'],request['data_mode'],request['store_epoch'])!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('workspace request scope differs')
        existing=self._existing(request)
        if existing is not None:
            if request['operation']=='complete_close':self._retire_completed(existing['fact'],observation)
            if request['operation']=='renew' and type(observation) is PendingRenewal:
                with self._lock:
                    known=any(slot['renewal'] is not None and slot['renewal']['pending'] is observation for slot in self._slots.values())
                if known:self.ack_renewal(fact_key(request),observation)
            return existing # Historical receipt, never current ability.
        renewal=None
        if request['operation']=='renew':
            with self._lock:
                slot,entry=self._renewal_slot(observation)
                if entry['request'] is not None and entry['request']!=request:raise Conflict('pending renewal request reused')
                renewal=slot,entry
                actual=observation.candidate;record=json.loads(actual.raw)
        else:
            slot,record=self._issued(observation);actual=observation
            if self._unresolved_renewal(slot):raise Conflict('workspace has unresolved renewal')
        if request['workspace_id']!=record['workspace_id']:raise Conflict('workspace actual stage differs')
        with self._owned_transaction(token,renewal) as (db,read,control):
            if renewal is not None:
                if self._renewal_slot(observation)!=(slot,renewal[1]):raise Conflict('workspace actual renewal changed')
                if renewal[1]['request'] is not None and renewal[1]['request']!=request:
                    raise Conflict('pending renewal request reused')
            elif self._unresolved_renewal(slot):raise Conflict('workspace has unresolved renewal')
            version=self._metadata(db)
            if version!=request['expected_state_version']:raise Conflict('workspace stale expected version')
            prior=self._current(db,request,read,version)
            if request['operation'] in ('acquire','renew'):
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
                'observation':record,'observation_issued_monotonic_ns':actual.issued_monotonic_ns,
                'observation_expires_monotonic_ns':actual.expires_monotonic_ns,'physical_close':closed,
                'controller_checked_monotonic_ns':mono,'recorded_at':now.isoformat().replace('+00:00','Z'),
                'prior_head':prior,'state':{'acquire':'HELD_PRE_RUNTIME','renew':'HELD_PRE_RUNTIME','request_close':'CLOSE_REQUESTED','complete_close':'CLOSED_PRE_RUNTIME'}[request['operation']],
                'accepted_state_version':version+1,'execution_enabled':False,'release_enabled':False}
            key=fact_key(request);validate_record(SECTIONS[0],key,value)
            dependencies=self._dependencies(db,value,read);slot['dependencies']=dependencies
            if slot['witness'].materials[0].id!=record['base_snapshot_id'] or json.loads(slot['witness'].raw)['intent_key']!=ref['intent_key']:
                raise Conflict('workspace stage belongs to another original preparation')
            payload={'format':2,'put':[[SECTIONS[0],key,value],[SECTIONS[1],head_key(request),head(value)]],'delete':[],'details':None}
            if request['operation']=='acquire':payload['put'].append([SECTIONS[2],claim_key(request),claim(value)])
            payload['put'].extend([s,'',{}] for s in SECTIONS if not db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(s,)).fetchone())
            guard=_Guard(self,db,read,token,value,slot,dependencies);self._active=guard;guard.check()
            if renewal is not None:
                # Bind ONLY after actual candidate/current original lineage,
                # sources/budget/claim/guard proofs. Rejected caller scope
                # must never poison the original pending cleanup/retry path.
                renewal[1]['request']=request;renewal[1]['fact']=value
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
        if self._unresolved_renewal(slot):raise Conflict('workspace has unresolved renewal')
        with self.store.read_connection() as db:
            db.execute('BEGIN');version=self._metadata(db);read=ReadBudget(db,PREPARATION_READ_BYTES)
            value=self._point(db,close_request_key,read);self._dependencies(db,value,read)
            if (value['state']!='CLOSE_REQUESTED' or value['request']['workspace_id']!=record['workspace_id'] or
                    value['observation']!=record or self._current(db,value['request'],read,version)!=head(value)):
                raise Conflict('actual current original CLOSE_REQUESTED required')
        with self._lock:
            if slot['closed'] is None:slot['closed']=self.working.close_pre_runtime(observation)
            return slot['closed']
