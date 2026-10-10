"""Actual original native Reviewer -> guarded condition acceptance CAS."""
from contextlib import contextmanager
import json
import threading

from .hybrid_a_condition_acceptance import (SECTION,EVENT,REQUEST,fact_key,event_inputs,
    validate_record,validate_links,original_event)
from .hybrid_a_condition_rules import derive
from .hybrid_a_workflow_accounting import check_window
from .hybrid_budget_ledger import SECTIONS as BUDGET,entry_key,derived_heads,scope
from .hybrid_budget import account_key
from .hybrid_budget_service import BudgetService
from .hybrid_controller import fact_key as control_key
from .hybrid_preparation import source_binding
from .hybrid_preparation_sources import historical_sources
from .hybrid_reads import ReadBudget
from .hybrid_goals import digest,check_bytes
from .hybrid_protocol import validate_schema
from .hybrid_authority import timestamp
from .store import Conflict,canonical,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,read,token,lease,value,head):
        self.owner,self.db,self.read,self.token,self.lease=owner,db,read,token,lease
        self.raw=canonical(value);self.thread=threading.get_ident()
        self.workflow_raw=canonical(head['workflow'])
    def check(self):self.owner.check_guard(self.db,self)
    def lookup(self,section,key):
        if not key:return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        return self.owner._lookup(self.db,self.read,section,key)


class ConditionAcceptanceService:
    def __init__(self,budget):
        if type(budget) is not BudgetService:raise TypeError('original Budget owner required')
        self.budget=budget;self.store=budget.store;self.controller=budget.controller;self.registry=budget.registry
        self._binding=(budget,self.store,self.controller,self.registry,self.registry._raw)
        self._active=None;self._lock=threading.RLock()
        self.store.bind_hybrid_a_conditions(self)
        self._runtime()

    def _runtime(self):
        from .hybrid_native_model_runtime import NativeModelOwner
        budget,store,controller,registry,raw=self._binding
        if (self.budget is not budget or self.store is not store or self.controller is not controller or
                self.registry is not registry or registry._raw!=raw or
                store._hybrid_a_condition_service is not self or budget.store is not store or
                budget.controller is not controller or budget.registry is not registry):
            raise PermissionError('original condition acceptance component binding required')
        runtime=budget._fixture_runtime
        if type(runtime) is not NativeModelOwner or runtime.budget is not budget:
            raise PermissionError('original current native Reviewer owner required')
        runtime._actual();return runtime

    def _review(self,lease):
        runtime=self._runtime();attempt=runtime._issued(lease)
        workflow=attempt['origin']['native_model'].get('workflow',{})
        if workflow.get('stage')!='INDEPENDENT_REVIEW':raise Conflict('original independent Reviewer lease required')
        issued=runtime.sources._model_results.get(id(attempt['source']))
        if issued is None:raise Conflict('original complete Reviewer Source result required')
        runtime._workflow_native_completion(attempt,issued[2])
        return runtime,attempt,attempt['entries']['FIXTURE_SCOPE_STOPPED']

    def _graph(self,db,read,reviewer):
        parents={'reviewer':reviewer}
        refs=reviewer['request']['fixture_runtime']['origin']['native_model']['workflow']['parents']
        for name,ref in refs.items():
            value=self.budget._point(db,ref['key'],read)
            if digest(value)!=ref['hash']:raise Conflict('condition acceptance original parent changed')
            parents[name]=value
        for parent in parents.values():
            if self.budget._point(db,entry_key(parent['request']),read)!=parent:
                raise Conflict('condition acceptance whole parent event differs')
        return parents

    def _lookup(self,db,read,section,key):
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        from .hybrid_controller import SECTIONS as CONTROL
        from .hybrid_fixture_runtime_ledger import dependency_lookup
        # Current authorization/account heads are NEVER historical cache data.
        if section in (*BUDGET[1:],GOALS[1],AUTHORITY[2],CONTROL[1]):return read.object(section,key)
        proof=getattr(read,'_a_condition_proof',None)
        if proof is None:raise PermissionError('original condition dependency closure required')
        return dependency_lookup(self.store,db,read,proof[1])(section,key)

    def _dependencies(self,db,value,read,*,current=False):
        identity=canonical({k:value[k] for k in ('parents','sources','controller')})
        proof=getattr(read,'_a_condition_proof',None)
        if proof is None:
            state={}
            def merge(objects):
                for section,rows in objects.items():
                    target=state.setdefault(section,{})
                    for key,item in rows.items():
                        if key in target and target[key]!=item:raise Conflict('condition original dependencies disagree')
                        target[key]=item
            for ref in value['parents'].values():
                parent=self.budget._point(db,ref['key'],read)
                merge(self.budget._dependencies(db,parent,read));merge({BUDGET[0]:{ref['key']:parent}})
            merge(historical_sources(self.store,db,value['sources'],read))
            from .hybrid_controller import SECTIONS as CONTROL
            key=value['controller']['fact_key'];merge({CONTROL[0]:{key:self.controller._original(db,key,read)}})
            read._a_condition_proof=(identity,state)
        elif proof[0]!=identity:raise Conflict('condition original transaction dependency identity changed')
        validate_links(value,lambda s,k:self._lookup(db,read,s,k),current=current)

    def _point(self,db,key,read):
        value=read.object(SECTION,key)
        if value is None:raise Conflict('condition acceptance fact missing')
        validate_record(key,value)
        if original_event(self.store,db,key,read)!=value:raise Conflict('condition acceptance original event differs')
        self._dependencies(db,value,read);return value

    def check_guard(self,db,guard):
        runtime=self._runtime()
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.read.db is not db or guard.thread!=threading.get_ident() or
                not db.in_transaction):raise PermissionError('actual active condition acceptance guard required')
        _,attempt,reviewer=self._review(guard.lease);runtime._unit_check(attempt)
        if runtime._safety_freeze or attempt.get('physical_safety_freeze'):
            raise Conflict('condition acceptance frozen for cleanup')
        value=json.loads(guard.raw)
        head=derived_heads(reviewer)[BUDGET[1]][account_key(scope(value['request']))]
        if guard.workflow_raw!=canonical(head['workflow']):raise Conflict('condition original workflow head differs')
        now,_=self.controller._sample()
        check_window(head['workflow'],attempt['origin']['native_model']['workflow'],now)
        if value['parents']['reviewer']!={'key':entry_key(reviewer['request']),'hash':digest(reviewer)}:
            raise Conflict('condition acceptance original Reviewer differs')
        control=self.controller.check_token_in_transaction(db,guard.token,guard.read)
        if value['controller']!={'fact_key':control_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}:
            raise Conflict('condition acceptance current Controller changed')
        loaded=self.budget._load(db,value['request']['goal_ref'],guard.read)
        current=source_binding(loaded)
        if any(current[k]!=v for k,v in value['sources'].items() if k not in ('source_version','evaluated_at')):
            raise Conflict('condition acceptance current approval changed')
        self._dependencies(db,value,guard.read,current=True)
        version=self.budget._metadata(db)
        if version==value['accepted_state_version']:
            if guard.read.object(SECTION,fact_key(value['request']))!=value:
                raise Conflict('condition acceptance committed fact changed')
        elif version!=value['request']['expected_state_version']:
            raise Conflict('condition acceptance writer version changed')

    def check_live_write(self,db,payload,inputs,guard):
        guard.check();value=json.loads(guard.raw);key=fact_key(value['request'])
        if ([(s,k,v) for s,k,v in payload['put'] if k]!=[(SECTION,key,value)] or
                inputs!=event_inputs(value) or self.budget._metadata(db)!=value['request']['expected_state_version']):
            raise Conflict('condition acceptance mutation differs from original guard')

    @contextmanager
    def _transaction(self,token):
        def final():
            if self._active is None:raise PermissionError('original final condition acceptance guard missing')
            self._active.check()
        def deadlines(now,mono):
            guard=self._active;value=json.loads(guard.raw);runtime=self.budget._fixture_runtime
            attempt=runtime._leases[id(guard.lease)]
            if (not timestamp(value['recorded_at'])<=now<timestamp(value['sources']['expires_at']) or
                    runtime._safety_freeze or attempt.get('physical_safety_freeze')):
                raise Conflict('condition acceptance expired or stopped before COMMIT')
            check_window(json.loads(guard.workflow_raw),attempt['origin']['native_model']['workflow'],now)
            runtime._unit_effect_check(attempt)
        if self._active is not None:raise Conflict('nested condition acceptance transaction refused')
        runtime=self._runtime()
        try:
            with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                    _commit_context=runtime._held if runtime._control_service is not None else None,
                    _before_commit=final,_after_final_sample=deadlines) as context:yield context
        finally:self._active=None

    def accept(self,lease,token,*,idempotency_key,expected_state_version):
        """No caller evidence/verdict/results; current original facts only."""
        runtime=self._runtime();self.controller._refuse_nested_writer();self.controller._issued(token)
        runtime,attempt,reviewer=self._review(lease)
        request={k:reviewer['request'][k] for k in ('project_id','data_mode','store_epoch','goal_ref')}
        request.update(idempotency_key=idempotency_key,expected_state_version=expected_state_version,
            reviewer_terminal_key=entry_key(reviewer['request']))
        check_bytes(request,4096);validate_schema(REQUEST,request);key=fact_key(request)
        with runtime._workflow_cpu_admission_lock,runtime.pool._lock,self._lock:
            with self.store.read_connection() as db:
                db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
                if read.object(SECTION,key) is not None:
                    value=self._point(db,key,read)
                    if value['request']!=request:raise Conflict('condition acceptance original key reused')
                    return {'fact':value,'duplicate':True,'current_activation':'NOT_RECHECKED'}
            with self._transaction(token) as (db,read,control):
                version=self.budget._metadata(db)
                if version!=expected_state_version:raise Conflict('condition acceptance stale expected version')
                parents=self._graph(db,read,reviewer)
                loaded=self.budget._load(db,request['goal_ref'],read)
                sources=source_binding(loaded);_,mono=self.controller._sample()
                result=derive(loaded['record']['contract']['proposal'],json.loads(self.registry._raw),
                    parents['cpu'],parents['engineer'],parents['reviewer'])
                head=derived_heads(reviewer)[BUDGET[1]][account_key(scope(request))]
                value={'schema_version':'1.0','request':request,'request_hash':digest(request),
                    'sources':sources,'controller':{'fact_key':control_key(control['request']),'fact_hash':digest(control),
                        'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
                    'recorded_at':sources['evaluated_at'],'controller_checked_monotonic_ns':mono,
                    'accepted_state_version':version+1,'budget_head_sha256':digest(head),
                    'goal_completed':False,'dispatch_enabled':False,**result}
                validate_record(key,value);self._dependencies(db,value,read,current=True)
                payload={'format':2,'put':[[SECTION,key,value]],'delete':[],'details':None}
                present=read.object(SECTION,'') is not None
                tip=db.execute('SELECT 1 FROM events WHERE event_type=? LIMIT 1',(EVENT,)).fetchone()
                if present!=(tip is not None):raise Conflict('condition acceptance domain original marker differs')
                if not present:payload['put'].append([SECTION,'',{}])
                guard=_Guard(self,db,read,token,lease,value,head);self._active=guard;guard.check()
                self.store._commit(db,EVENT,key,payload,version,digest(value),'hybrid-core',event_inputs(value),_authorization=guard)
                guard.check()
            return {'fact':value,'duplicate':False,'current_activation':'ORIGINAL_CONDITIONS_CURRENT_AS_OF'}
