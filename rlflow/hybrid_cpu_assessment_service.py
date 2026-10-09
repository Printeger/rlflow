"""Original owner appraisal and current-vs-historical bounded readback."""
from contextlib import contextmanager
import hashlib
import json
import threading

from .hybrid_cpu_assessment import (SECTION,EVENT,REQUEST,fact_key,appraisal,
    validate_record,validate_links,event_inputs)
from .hybrid_controller import SECTIONS as CONTROL, fact_key as control_key
from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_fixture_materials import _read_bounded
from .hybrid_budget_ledger import SECTIONS as BUDGET, entry_key
from .hybrid_preparation import source_binding
from .hybrid_preparation_sources import historical_sources
from .hybrid_reads import ReadBudget
from .hybrid_goals import digest,check_bytes
from .hybrid_protocol import validate_schema
from .hybrid_authority import timestamp
from .store import Conflict,canonical,sha,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,read,token,lease,value):
        self.owner,self.db,self.read=owner,db,read;self.token,self.lease=token,lease
        self.raw=canonical(value);self.thread=threading.get_ident()

    def check(self): self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key: return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        return self.read.object(section,key)


class CpuAssessmentService:
    def __init__(self,runtime):
        if type(runtime) is not FixtureRuntimeOwner: raise TypeError('original fixed CPU runtime owner required')
        runtime._actual(); self.runtime=runtime;self.store=runtime.store;self.controller=runtime.controller
        self.budget=runtime.budget;self.registry=runtime.plans.registry
        self._active=None;self._lock=threading.RLock()
        from .hybrid_cpu_cold_verifier import implementation_hash
        self._cold_verifier_hash=implementation_hash()
        self.store.bind_hybrid_cpu_assessment(self)

    def _actual(self):
        self.runtime._actual()
        if self.store._hybrid_cpu_assessment_service is not self:
            raise PermissionError('actual original CPU appraisal owner required')

    def _original_trial(self,lease):
        self._actual(); attempt=self.runtime._issued(lease)
        if (attempt['cpu_grant'] is None or attempt.get('pool_closed') is None or
                'FIXTURE_SCOPE_STOPPED' not in attempt['entries']):
            raise Conflict('original CPU trial STOP and all-FD/Pool closure required')
        self.runtime._check_terminal(attempt)
        slot=self.runtime.pool._claim_slots[id(attempt['claim'])]
        if not slot.closed or any(fd is not None for fd in slot.fds):
            raise Conflict('original CPU trial pool descriptors not all closed')
        terminal=attempt['entries']['FIXTURE_SCOPE_STOPPED']
        result=self.runtime._cpu_results.get(id(lease))
        recorded=terminal['request']['fixture_runtime']['cpu_trial_result']
        if recorded!=(None if result is None else json.loads(result.raw)):
            raise Conflict('CPU appraisal original result capability differs')
        key='fixture_free_'+sha([attempt['origin']['pool_claim']['key'],lease.id])
        pool=self.runtime.pool
        with pool._transaction() as db:
            free=pool._point(db,key)
            if (free is None or pool._attempts.get(key)!=free or
                    free['payload']['close_witness_hash']!=digest(attempt['pool_closed']) or
                    free['payload']['project_fact_hash']!=digest(terminal)):
                raise Conflict('original CPU trial Pool FREE proof missing or changed')
        return attempt,terminal,free

    def _dependencies(self,db,value,read):
        if 'prior_assessment_key' in value['request']:
            raw_prior=read.object(SECTION,value['request']['prior_assessment_key'])
            if raw_prior is None or 'prior_assessment_key' in raw_prior.get('request',{}):
                raise Conflict('CPU decision requires plain original appraisal')
            prior=self._point(db,value['request']['prior_assessment_key'],read)
            if 'prior_assessment_key' in prior['request']:
                raise Conflict('CPU decision requires plain original appraisal')
        terminal=self.budget._point(db,value['request']['terminal_key'],read)
        self.budget._dependencies(db,terminal,read)
        historical_sources(self.store,db,value['sources'],read)
        self.controller._original(db,value['controller']['fact_key'],read)
        validate_links(value,lambda s,k:read.object(s,k))
        return terminal

    def _point(self,db,key,read):
        value=read.object(SECTION,key)
        if value is None: raise Conflict('CPU appraisal fact missing')
        validate_record(key,value)
        proof=self.store._cpu_assessment_event(db,key,max_bytes=min(read.remaining,256*1024),
            _parse=read.parse,_decode=read.decode)
        if proof!=((EVENT,'hybrid-core',digest(value),value['accepted_state_version']),[(SECTION,key,digest(value))]):
            raise Conflict('CPU appraisal original event differs')
        self._dependencies(db,value,read); return value

    def _current_sources(self,db,read,goal_ref):
        return source_binding(self.budget._load(db,goal_ref,read))

    def check_guard(self,db,guard):
        self._actual()
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.read.db is not db or guard.thread!=threading.get_ident() or not db.in_transaction):
            raise PermissionError('actual active CPU appraisal guard required')
        attempt,terminal,free=self._original_trial(guard.lease); value=json.loads(guard.raw)
        self.runtime._unit_check(attempt)
        if 'machine_verification' in value:
            from .hybrid_cpu_cold_verifier import implementation_hash
            if (implementation_hash()!=self._cold_verifier_hash or
                    value['machine_verification']['verifier_sha256']!=self._cold_verifier_hash):
                raise Conflict('CPU decision protected verifier implementation changed')
        if (terminal['request']['goal_ref']!=value['request']['goal_ref'] or
                entry_key(terminal['request'])!=value['request']['terminal_key'] or digest(terminal)!=value['terminal_hash'] or
                value['pool_free']!=free):
            raise Conflict('CPU appraisal original trial differs')
        control=self.controller.check_token_in_transaction(db,guard.token,guard.read)
        if value['controller']!={'fact_key':control_key(control['request']),'fact_hash':digest(control),
                'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}:
            raise Conflict('CPU appraisal current controller changed')
        current=self._current_sources(db,guard.read,value['request']['goal_ref'])
        if any(current[n]!=v for n,v in value['sources'].items() if n not in ('source_version','evaluated_at')):
            raise Conflict('CPU appraisal current approved sources changed')
        expected=self.runtime._cpu_binding(self.budget._load(db,value['request']['goal_ref'],guard.read))
        expected['grant_id']=attempt['cpu_grant'].id
        if canonical(expected)!=attempt['cpu_grant'].raw:
            raise Conflict('CPU appraisal current original CPU grant differs')
        if 'sha256:'+hashlib.sha256(_read_bounded(self.runtime._cpu_evaluator,16384)).hexdigest()!=self.runtime._cpu_evaluator_hash:
            raise Conflict('CPU appraisal protected evaluator changed')
        version=self.budget._metadata(db)
        if version==value['accepted_state_version']:
            if guard.read.object(SECTION,fact_key(value['request']))!=value:
                raise Conflict('CPU appraisal committed fact changed')
        elif version!=value['request']['expected_state_version']:
            raise Conflict('CPU appraisal writer version changed')
        now,_=self.controller._sample()
        if not timestamp(value['recorded_at'])<=now<timestamp(value['sources']['expires_at']):
            raise Conflict('CPU appraisal current consent expired')

    def check_live_write(self,db,payload,inputs,guard):
        guard.check(); value=json.loads(guard.raw); key=fact_key(value['request'])
        if ([(s,k,v) for s,k,v in payload['put'] if k]!=[(SECTION,key,value)] or inputs!=event_inputs(value) or
                self.budget._metadata(db)!=value['request']['expected_state_version']):
            raise Conflict('CPU appraisal mutation differs from issued context')
        self._dependencies(db,value,guard.read)

    @contextmanager
    def _transaction(self,token):
        def final():
            if self._active is None: raise PermissionError('actual final CPU appraisal guard missing')
            self._active.check()
        def deadlines(now,mono):
            value=json.loads(self._active.raw)
            if not timestamp(value['recorded_at'])<=now<timestamp(value['sources']['expires_at']):
                raise Conflict('CPU appraisal expired at final owned COMMIT')
            self.runtime._unit_effect_check(self.runtime._leases[id(self._active.lease)])
        if self._active is not None: raise Conflict('nested CPU appraisal transaction refused')
        try:
            with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                    _commit_context=self.runtime._held if self.runtime._control_service is not None else None,
                    _before_commit=final,_after_final_sample=deadlines) as context: yield context
        finally: self._active=None

    def assess(self,lease,token,*,idempotency_key,expected_state_version):
        """Commit finite-trial state, never dispatch or satisfy arbitrary conditions."""
        return self._record(lease,token,idempotency_key=idempotency_key,expected_state_version=expected_state_version)

    def decide(self,lease,token,*,assessment_key,idempotency_key,expected_state_version):
        """Cold raw recomputation → immutable machine fact and conservative next step."""
        from .hybrid_protocol import ID
        validate_schema(ID,assessment_key)
        return self._record(lease,token,idempotency_key=idempotency_key,
            expected_state_version=expected_state_version,assessment_key=assessment_key)

    def _record(self,lease,token,*,idempotency_key,expected_state_version,assessment_key=None):
        self._actual();self.controller._refuse_nested_writer();self.controller._issued(token)
        attempt,terminal,free=self._original_trial(lease)
        request={n:terminal['request'][n] for n in ('project_id','data_mode','store_epoch','goal_ref')}
        request.update(idempotency_key=idempotency_key,expected_state_version=expected_state_version,
            terminal_key=entry_key(terminal['request']))
        if assessment_key is not None:request['prior_assessment_key']=assessment_key
        check_bytes(request,4096);validate_schema(REQUEST,request);key=fact_key(request)
        with self.runtime.pool._lock,self._lock:
            with self.store.read_connection() as db:
                db.execute('BEGIN'); read=ReadBudget(db,PREPARATION_READ_BYTES)
                if read.object(SECTION,key) is not None:
                    value=self._point(db,key,read)
                    if value['request']!=request: raise Conflict('CPU appraisal idempotency key reused')
                    return {'fact':value,'duplicate':True,'current_activation':'NOT_RECHECKED'}
            with self._transaction(token) as (db,read,control):
                self.runtime._unit_check(attempt)
                version=self.budget._metadata(db)
                if version!=expected_state_version: raise Conflict('CPU appraisal stale expected version')
                sources=self._current_sources(db,read,request['goal_ref']);_,mono=self.controller._sample()
                result=terminal['request']['fixture_runtime']['cpu_trial_result']
                value={'schema_version':'1.0','request':request,'request_hash':digest(request),
                    'terminal_hash':digest(terminal),'result_hash':None if result is None else digest(result),'pool_free':free,
                    'sources':sources,'controller':{'fact_key':control_key(control['request']),'fact_hash':digest(control),
                        'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']},
                    'recorded_at':sources['evaluated_at'],'controller_checked_monotonic_ns':mono,
                    'accepted_state_version':version+1,'assessment':appraisal(terminal),
                    'evidence_activation':'EXPERIMENT_CURRENT_AS_OF'}
                if assessment_key is not None:
                    prior=self._point(db,assessment_key,read)
                    if 'prior_assessment_key' in prior['request']:raise Conflict('CPU decision requires plain original appraisal')
                    from .hybrid_cpu_cold_verifier import verify
                    value.update(prior_assessment_hash=digest(prior),machine_verification=verify(result))
                unit=self.runtime._execution_units.get(id(lease))
                if unit is not None:value=unit._original_assessment_attempt(value)
                validate_record(key,value);self._dependencies(db,value,read)
                payload={'format':2,'put':[[SECTION,key,value]],'delete':[],'details':None}
                present=read.object(SECTION,'') is not None
                tip,count=self.store._cpu_assessment_summary(db,version)
                if present!=(tip is not None): raise Conflict('CPU appraisal domain differs from original tip')
                if not present: payload['put'].append([SECTION,'',{}])
                guard=_Guard(self,db,read,token,lease,value);self._active=guard;guard.check()
                if unit is not None:unit._capture_assessment(value)
                self.store._commit(db,EVENT,key,payload,version,digest(value),'hybrid-core',event_inputs(value),_authorization=guard)
                guard.check()
            return {'fact':value,'duplicate':False,'current_activation':'EXPERIMENT_CURRENT_AS_OF'}

    def inspect(self,key):
        """No writer/dispatch/owner reconstruction; historical record stays immutable."""
        from .hybrid_protocol import ID
        validate_schema(ID,key)
        with self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            value=self._point(db,key,read); sources=value['sources']
            try:
                current=self._current_sources(db,read,sources['goal_ref'])
                active=all(current[n]==v for n,v in sources.items() if n not in ('source_version','evaluated_at'))
            except Conflict: active=False
            version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
            now,_=self.controller._sample()
            active=active and timestamp(sources['evaluated_at'])<=now<timestamp(sources['expires_at'])
            return {'id':key,'fact':value,'current_activation':'EXPERIMENT_CURRENT_AS_OF' if active else 'HISTORICAL_ONLY',
                'as_of_version':version,'checked_at':now.isoformat().replace('+00:00','Z'),
                'goal_completed':False,'dispatch_enabled':False}
