"""Protected cumulative budget owner. Reservations never authorize execution."""
from contextlib import contextmanager
import json
import threading

from .hybrid_budget import account_key,balances,zero,rebase,reserve
from .hybrid_budget_ledger import (SECTIONS,EVENT,REQUEST,scope,entry_key,_keys,
    policy_limits,derived_heads,expected_objects,event_inputs,validate_record,validate_links)
from .hybrid_controller_service import ControllerService
from .hybrid_controller import SECTIONS as CONTROLLER,fact_key as controller_key
from .hybrid_preparation_service import PreparationService
from .hybrid_preparation import SECTIONS as PREPARATION,result_key,source_binding
from .hybrid_preparation_sources import historical_sources,load_sources
from .hybrid_reads import ReadBudget
from .hybrid_registry import Registry
from .hybrid_protocol import validate_schema
from .hybrid_goals import check_bytes,digest
from .hybrid_authority import timestamp
from .store import Store,Conflict,canonical,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,budget,token,value,dependencies):
        self.owner,self.db,self.budget,self.token=owner,db,budget,token
        self.raw=canonical(value);self.dependencies=dependencies;self.thread=threading.get_ident()

    def check(self):self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key:
            return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        # Only original immutable dependencies are cached; all mutable heads
        # are re-read in the actual writer, including after projection update.
        if key in self.dependencies.get(section,{}):return self.dependencies[section][key]
        return self.budget.object(section,key)


class BudgetService:
    def __init__(self,store,registry,controller,preparation):
        if (type(store) is not Store or type(registry) is not Registry or
                type(controller) is not ControllerService or type(preparation) is not PreparationService or
                controller.store is not store or preparation.store is not store or
                controller.registry is not registry or preparation.registry is not registry):
            raise TypeError('fixed actual budget components required')
        self.store,self.registry,self.controller,self.preparation=store,registry,controller,preparation
        self.project_id,self.data_mode,self.store_epoch=controller.project_id,controller.data_mode,controller.store_epoch
        if (preparation.project_id,preparation.data_mode,preparation.store_epoch)!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('budget fixed owner scope differs')
        self._config_hash=registry.config_hash;self._active=None;self._lock=threading.RLock()
        store.bind_hybrid_budget(self)

    def _metadata(self,db):
        if self.store._hybrid_budget_service is not self or self.registry.config_hash!=self._config_hash:
            raise PermissionError('actual bound budget owner required')
        self.store._require_budget_indices(db)
        version=self.controller._metadata(db)
        if self.preparation._metadata(db)!=version:raise Conflict('budget owner versions differ')
        return version

    def _point(self,db,key,budget):
        value=budget.object(SECTIONS[0],key)
        if value is None:raise Conflict('budget original entry missing')
        validate_record(SECTIONS[0],key,value)
        proof=self.store._budget_event(db,key,max_bytes=min(budget.remaining,1024*1024),
                                      _parse=budget.parse,_decode=budget.decode)
        if proof!=((EVENT,'hybrid-core',account_key(scope(value['request'])),value['accepted_state_version']),expected_objects(value)):
            raise Conflict('budget original event differs')
        return value

    def _dependencies(self,db,value,budget):
        state=historical_sources(self.store,db,value['policy_source'],budget)
        ref=value['preparation'];intent=self.preparation._original(db,PREPARATION[0],ref['intent_key'],budget)
        outcome=self.preparation._original(db,PREPARATION[1],ref['result_key'],budget)
        for section,objects in historical_sources(self.store,db,intent['sources'],budget).items():
            state.setdefault(section,{}).update(objects)
        state[PREPARATION[0]]={ref['intent_key']:intent};state[PREPARATION[1]]={ref['result_key']:outcome}
        ck=value['controller']['fact_key'];state[CONTROLLER[0]]={ck:self.controller._original(db,ck,budget)}
        entries={};state[SECTIONS[0]]=entries
        for name in ('prior_goal','prior_reservation','prior_project'):
            head=value[name]
            if head is not None and head['last_entry_key'] not in entries:
                key=head['last_entry_key'];entries[key]=self._point(db,key,budget)
        if value['request']['action']!='RESERVE':
            key=value['prior_reservation']['origin_entry_key']
            if key not in entries:entries[key]=self._point(db,key,budget)
        validate_links(value,lambda s,k:state.get(s,{}).get(k))
        return state

    def _existing(self,request):
        key=entry_key(request)
        with self.store.read_connection() as db:
            db.execute('BEGIN');self._metadata(db)
            if not db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],key)).fetchone():return None
            budget=ReadBudget(db,PREPARATION_READ_BYTES);value=self._point(db,key,budget)
            self._dependencies(db,value,budget)
            if value['request']!=request:raise Conflict('budget idempotency key reused')
            # Historical receipt, not a current reservation lease or refund.
            return {'entry':value,'duplicate':True,'execution_enabled':False}

    def _heads(self,db,request,budget,version):
        keys=_keys(request);global_tip=self.store._budget_tip(db,version)
        present=[db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(s,)).fetchone() is not None for s in SECTIONS]
        if any(p!=(global_tip is not None) for p in present):raise Conflict('budget domain differs from original tip')
        tips=(self.store._budget_tip(db,version,goal_account_key=keys[0]),
              self.store._budget_tip(db,version,reservation_id=keys[1]),global_tip)
        result=[];originals={}
        for section,key,tip in zip(SECTIONS[1:],keys,tips):
            head=budget.object(section,key)
            if (head is None)!=(tip is None):raise Conflict('budget current head missing or unexpected')
            if head is not None:
                validate_record(section,key,head)
                if (head['last_entry_key'],head['accepted_state_version'])!=tip:
                    raise Conflict('budget current head differs from indexed tip')
                original=originals.get(tip[0])
                if original is None:original=self._point(db,tip[0],budget);originals[tip[0]]=original
                if derived_heads(original).get(section,{}).get(key)!=head:
                    raise Conflict('budget current head is not original derived head')
            result.append(head)
        return tuple(result)

    def _load(self,db,goal_ref,budget):
        now,_=self.controller._sample()
        return load_sources(self.store,db,self.registry,project_id=self.project_id,data_mode=self.data_mode,
            store_epoch=self.store_epoch,goal_ref=goal_ref,now=now,_budget=budget)

    def check_guard(self,db,guard):
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.budget.db is not db or guard.thread!=threading.get_ident()):
            raise PermissionError('actual active budget owner guard required')
        version=self._metadata(db);control=self.controller.check_token_in_transaction(db,guard.token,guard.budget)
        value=json.loads(guard.raw);request=value['request']
        if value['controller']!={'fact_key':controller_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}:
            raise Conflict('budget differs from actual current controller token')
        if version not in (request['expected_state_version'],value['accepted_state_version']):
            raise Conflict('budget writer version changed')
        now,_=self.controller._sample()
        if now<timestamp(value['recorded_at']):raise Conflict('budget clock regressed before commit')
        if request['action']=='RESERVE':
            current=source_binding(self._load(db,request['goal_ref'],guard.budget))
            if (now>=timestamp(value['policy_source']['expires_at']) or
                    any(current[n]!=v for n,v in value['policy_source'].items() if n not in ('source_version','evaluated_at'))):
                raise Conflict('budget current consent changed or expired')
        if version==value['accepted_state_version']:
            if self._point(db,entry_key(request),guard.budget)!=value:raise Conflict('budget committed entry changed')
            for section,values in derived_heads(value).items():
                for key,head in values.items():
                    if guard.budget.object(section,key)!=head:raise Conflict('budget final derived head changed')
        elif guard.budget.object(SECTIONS[0],entry_key(request)) is not None:
            raise Conflict('budget new entry already present')
        # Re-sample after the last potentially large source/head read. The
        # Controller owned context additionally checks Kernel/STOP/dual TTL
        # after this callback and immediately before COMMIT.
        final_now,_=self.controller._sample()
        if (final_now<timestamp(value['recorded_at']) or request['action']=='RESERVE' and
                final_now>=timestamp(value['policy_source']['expires_at'])):
            raise Conflict('budget consent expired or clock regressed after final reads')

    def check_live_write(self,db,payload,inputs,guard):
        self.check_guard(db,guard);value=json.loads(guard.raw);request=value['request']
        expected={(SECTIONS[0],entry_key(request)):value}
        expected.update({(s,k):v for s,values in derived_heads(value).items() for k,v in values.items()})
        actual={(s,k):v for s,k,v in payload['put'] if k}
        if actual!=expected or inputs!=event_inputs(value):raise Conflict('budget mutation differs from issued context')
        version=self._metadata(db)
        if version!=request['expected_state_version']:raise Conflict('budget stale writer version')
        if self._heads(db,request,guard.budget,version)!=tuple(value[n] for n in ('prior_goal','prior_reservation','prior_project')):
            raise Conflict('budget current prior heads changed')
        validate_links(value,guard.lookup,current=True);guard.check()

    @contextmanager
    def _owned_transaction(self,token):
        def final_check():
            if self._active is None:raise PermissionError('actual final budget guard missing')
            self._active.check()
        def final_deadlines(now,mono):
            # No source/DB/IO here: use the Controller's exact final sample.
            if self._active is None:raise PermissionError('actual final budget guard missing')
            value=json.loads(self._active.raw)
            if (now<timestamp(value['recorded_at']) or value['request']['action']=='RESERVE' and
                    now>=timestamp(value['policy_source']['expires_at'])):
                raise Conflict('budget consent expired at final owned commit')
        if self._active is not None:raise Conflict('nested budget owner transaction refused')
        try:
            with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                    _before_commit=final_check,_after_final_sample=final_deadlines) as context:
                yield context
        finally:self._active=None

    def record(self,request,token):
        """RESERVE, conservative UNKNOWN, or exact core PRE_RUNTIME cancellation.

        No UsageOwner, runtime registration, release, execution or JSON refund.
        """
        self.controller._refuse_nested_writer();self.controller._issued(token)
        check_bytes(request,8192);validate_schema(REQUEST,request);request=json.loads(canonical(request))
        if (request['project_id'],request['data_mode'],request['store_epoch'])!=(self.project_id,self.data_mode,self.store_epoch):
            raise Conflict('budget request scope differs')
        if type(request['expected_state_version']) is not int:raise Conflict('actual budget version required')
        with self._lock:
            existing=self._existing(request)
            if existing is not None:return existing
            with self._owned_transaction(token) as (db,budget,control):
                version=self._metadata(db)
                if request['expected_state_version']!=version:raise Conflict('budget stale expected version')
                goal,reservation,project=self._heads(db,request,budget,version)
                if request['action']=='RESERVE':
                    loaded=self._load(db,request['goal_ref'],budget);sources=source_binding(loaded)
                    policy=loaded['record']['contract']['proposal']['budget']
                    ik=request['preparation_intent_key'];rk=result_key(ik)
                    intent=self.preparation._original(db,PREPARATION[0],ik,budget)
                    outcome=self.preparation._original(db,PREPARATION[1],rk,budget)
                    ref={'intent_key':ik,'intent_hash':digest(intent),'result_key':rk,'result_hash':digest(outcome)}
                    limits=policy_limits(policy)
                    before=goal['balance'] if goal is not None else balances(limits,zero(),zero(),zero())
                    changed=rebase(before,limits)
                    try:
                        reserve(changed,request['amount'],purpose='EXECUTION',fraction=policy['finalization_reserve_fraction'])
                        decision,reason='HELD','BUDGET_RESERVED'
                    except Conflict:decision,reason='DENIED','BUDGET_UNAVAILABLE'
                    recorded=sources['evaluated_at'];_,mono=self.controller._sample()
                else:
                    if goal is None or reservation is None:raise Conflict('exact PRE_RUNTIME HELD reservation required')
                    policy,sources,ref=goal['policy'],goal['policy_source'],reservation['preparation']
                    now,mono=self.controller._sample();recorded=now.isoformat().replace('+00:00','Z')
                    decision,reason=('UNKNOWN','EXPOSURE_UNKNOWN') if request['action']=='MARK_UNKNOWN' else ('CANCELLED','CORE_CANCELLED_BEFORE_RUNTIME')
                value={'schema_version':'1.0','request':request,'request_hash':digest(request),
                    'policy_source':sources,'policy':policy,'preparation':ref,
                    'controller':{'fact_key':controller_key(control['request']),'fact_hash':digest(control),
                        'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
                    'recorded_at':recorded,'controller_checked_monotonic_ns':mono,
                    'prior_goal':goal,'prior_reservation':reservation,'prior_project':project,
                    'decision':decision,'reason':reason,'accepted_state_version':version+1,'execution_enabled':False}
                key=entry_key(request);validate_record(SECTIONS[0],key,value)
                dependencies=self._dependencies(db,value,budget)
                payload={'format':2,'put':[[SECTIONS[0],key,value]],'delete':[],'details':None}
                payload['put'].extend([s,k,v] for s,values in derived_heads(value).items() for k,v in values.items())
                for section in SECTIONS:
                    if not db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone():
                        payload['put'].append([section,'',{}])
                guard=_Guard(self,db,budget,token,value,dependencies);self._active=guard;guard.check()
                self.store._commit(db,EVENT,key,payload,version,account_key(scope(request)),
                    'hybrid-core',event_inputs(value),_authorization=guard)
                guard.check()
            return {'entry':value,'duplicate':False,'execution_enabled':False}
