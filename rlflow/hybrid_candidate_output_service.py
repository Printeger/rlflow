"""Single original-cap core application after fixed worker STOP, never dispatch."""
from contextlib import contextmanager
import json
import threading

from .hybrid_candidate_output import (SECTIONS,EVENTS,SCOPE,intent_key,result_key,
    validate_record,validate_links,event_inputs)
from .hybrid_candidate_output_materials import CandidateOutputMaterial
from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_budget_ledger import entry_key
from .hybrid_controller import fact_key as control_key
from .hybrid_preparation import source_binding
from .hybrid_preparation_sources import historical_sources
from .hybrid_protocol import ID,validate_schema
from .hybrid_reads import ReadBudget
from .hybrid_goals import digest
from .hybrid_engineering_patch import BEFORE,AFTER,TARGET,hash_bytes
from .hybrid_authority import timestamp
from .store import Conflict,canonical,sha,PREPARATION_READ_BYTES


class _Guard:
    def __init__(self,owner,db,read,row,value,*,receipt=False,token=None):
        self.owner,self.db,self.read,self.row=owner,db,read,row
        self.raw=canonical(value);self.receipt=receipt;self.token=token
        self.value=json.loads(self.raw)
        self.control=None if receipt else owner.controller._issued(token)
        self.observation=json.loads(row['material'].observation.raw)
        self.thread=threading.get_ident()

    def check(self):self.owner.check_guard(self.db,self)

    def lookup(self,section,key):
        if not key:return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1',(section,)).fetchone() else None
        return self.read.object(section,key)

    def last_effect(self):
        self.owner._last_effect(self)


class CandidateOutputService:
    def __init__(self,runtime):
        if type(runtime) is not FixtureRuntimeOwner:raise TypeError('original fixed runtime required')
        runtime._actual();self.runtime=runtime;self.store=runtime.store
        self.controller=runtime.controller;self.budget=runtime.budget
        self._rows={};self._active=None;self._lock=threading.RLock()
        from .hybrid_engineering_cold_verifier import implementation_hash
        self._cold_verifier_hash=implementation_hash()
        self.store.bind_hybrid_candidate_output(self)

    def _actual(self):
        self.runtime._actual()
        if self.store._hybrid_candidate_output_service is not self:
            raise PermissionError('original candidate output service required')

    def _original(self,lease):
        self._actual();attempt=self.runtime._issued(lease)
        if attempt['engineering_grant'] is None or attempt.get('pool_closed') is None:
            raise Conflict('original engineering STOP and Pool closure required')
        self.runtime._check_terminal(attempt)
        terminal=attempt['entries'].get('FIXTURE_SCOPE_STOPPED')
        result=self.runtime._engineering_results.get(id(lease))
        if terminal is None or result is None or terminal['request']['fixture_runtime'].get('engineering_patch_result')!=json.loads(result.raw):
            raise Conflict('original engineering result capability and terminal required')
        slot=self.runtime.pool._claim_slots[id(attempt['claim'])]
        if not slot.closed or any(fd is not None for fd in slot.fds):raise Conflict('original Pool descriptors not closed')
        key='fixture_free_'+sha([attempt['origin']['pool_claim']['key'],lease.id])
        pool=self.runtime.pool
        with pool._transaction() as db:
            free=pool._point(db,key)
            if (free is None or pool._attempts.get(key)!=free or
                    free['payload']['close_witness_hash']!=digest(attempt['pool_closed']) or
                    free['payload']['project_fact_hash']!=digest(terminal)):
                raise Conflict('original engineering Pool FREE proof differs')
        return attempt,terminal,free

    def _dependencies(self,db,section,value,read):
        if 'machine_verification' in value:
            pk=value['request']['prior_output_key'];prior=read.object(SECTIONS[1],pk)
            if prior is None or 'machine_verification' in prior:raise Conflict('candidate acceptance requires plain original output')
            self._point(db,SECTIONS[1],pk,read)
        terminal=self.budget._point(db,value['request']['terminal_key'],read)
        self.budget._dependencies(db,terminal,read)
        historical_sources(self.store,db,value['sources'],read)
        self.controller._original(db,value['controller']['fact_key'],read)
        if section==SECTIONS[1]:self._point(db,SECTIONS[0],value['request']['intent_key'],read)
        validate_links(section,value,lambda s,k:read.object(s,k))

    def _point(self,db,section,key,read):
        value=read.object(section,key)
        if value is None:raise Conflict('original candidate output fact missing')
        validate_record(section,key,value)
        proof=self.store._candidate_output_event(db,key,max_bytes=min(read.remaining,4*1024**2),_parse=read.parse,_decode=read.decode)
        if proof!=((EVENTS[SECTIONS.index(section)],'hybrid-core',digest(value),value['accepted_state_version']),[(section,key,digest(value))]):
            raise Conflict('original candidate output event differs')
        self._dependencies(db,section,value,read);return value

    def check_guard(self,db,guard):
        self._actual()
        if (type(guard) is not _Guard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.read.db is not db or not db.in_transaction or
                guard.thread!=threading.get_ident() or self._rows.get(id(guard.row['lease'])) is not guard.row):
            raise PermissionError('actual active original candidate output guard required')
        row=guard.row;value=json.loads(guard.raw)
        attempt,terminal,free=self._original(row['lease'])
        workspace=self.runtime.workspace
        slot,record=workspace._issued(attempt['observation'])
        if slot['closed'] is not None or workspace._unresolved_renewal(slot):
            raise Conflict('candidate output original Workspace closed or pending renewal')
        captured=attempt['ready']['source_context']['workspace_head']
        fact=workspace._point(db,captured['fact_key'],guard.read)
        if (workspace._current(db,fact['request'],guard.read,self.budget._metadata(db))!=captured or
                record!=attempt['ready']['source_context']['observation']):
            raise Conflict('candidate output current original Workspace lineage changed')
        if (value['request']['terminal_key']!=entry_key(terminal['request']) or
                value['request']['terminal_hash']!=digest(terminal) or value['pool_free']!=free or
                value['base_tree']!=row['material'].base_tree or value['target_identity']!=row['material'].target_identity):
            raise Conflict('candidate output original physical/terminal binding differs')
        section=SECTIONS[1] if guard.receipt else SECTIONS[0]
        key=result_key(value['request']) if guard.receipt else intent_key(value['request'])
        version=self.budget._metadata(db)
        if version==value['accepted_state_version']:
            if guard.read.object(section,key)!=value:raise Conflict('candidate output committed fact changed')
        elif version!=value['request']['expected_state_version']:
            raise Conflict('candidate output writer version changed')
        if guard.receipt:
            if row['intent'] is None or digest(row['intent'])!=value['request']['intent_hash']:
                raise PermissionError('receipt requires actual original durable write intent')
            row['material'].check_hold(receipt=True)
            if 'machine_verification' in value:
                from .hybrid_engineering_cold_verifier import implementation_hash
                if (implementation_hash()!=self._cold_verifier_hash or
                        value['machine_verification']['verifier_sha256']!=self._cold_verifier_hash):
                    raise Conflict('candidate acceptance protected AST verifier changed')
        else:
            control=self.controller.check_token_in_transaction(db,guard.token,guard.read)
            if value['controller']!=self._control_ref(control):raise Conflict('candidate output current controller changed')
            loaded=self.budget._load(db,value['request']['goal_ref'],guard.read)
            current=source_binding(loaded)
            if any(current[k]!=v for k,v in value['sources'].items() if k not in ('source_version','evaluated_at')):
                raise Conflict('candidate output current approved sources changed')
            binding=self.runtime._engineering_binding(loaded)
            binding.update({k:loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
            binding['grant_id']=attempt['engineering_grant'].id
            if canonical(binding)!=attempt['engineering_grant'].raw:raise Conflict('candidate output current original fixed grant changed')
            row['material'].check_hold()
        plan,candidate,deadline=row['witness']
        after=row['material'].write_entered
        row['material'].check_graph(plan,row['material'].after_inventory(candidate) if after else candidate,deadline,after=after)
        if not guard.receipt:self._last_effect(guard)

    @staticmethod
    def _control_ref(control):
        return {'fact_key':control_key(control['request']),'fact_hash':digest(control),
            'controller_epoch':control['controller_epoch'],'head_revision':control['head_revision']}

    def _last_effect(self,guard):
        if self._active is not guard or guard.receipt:raise PermissionError('original live write boundary required')
        self.runtime._actual()
        if self.runtime._safety_freeze:raise Conflict('candidate output permanently frozen for cleanup')
        now,mono=self.controller._final_token_freshness(guard.db,guard.token,guard.read)
        self._deadlines(guard,now,mono)
        self.runtime._unit_effect_check(self.runtime._leases[id(guard.row['lease'])])

    def _deadlines(self,guard,now,mono):
        if self._active is not guard or guard.receipt:raise PermissionError('original live write boundary required')
        value=guard.value;observation=guard.row['material'].observation
        working_now,working_mono=self.runtime.workspace.working._sample()
        if (not timestamp(value['sources']['evaluated_at'])<=max(now,working_now)<timestamp(value['sources']['expires_at']) or
                not timestamp(guard.observation['checked_at'])<=working_now<timestamp(guard.observation['expires_at']) or
                not observation.issued_monotonic_ns<=working_mono<observation.expires_monotonic_ns):
            raise Conflict('candidate output expired at final physical effect')
        # Token transaction validates original Controller deadlines as well.
        if (not guard.control['issued_monotonic_ns']<=mono<guard.control['expires_monotonic_ns'] or
                not timestamp(guard.control['issued_at'])<=max(now,working_now)<timestamp(guard.control['expires_at'])):
            raise Conflict('candidate output controller expired at physical effect')

    def check_live_write(self,db,payload,inputs,guard):
        guard.check();value=json.loads(guard.raw)
        section=SECTIONS[1] if guard.receipt else SECTIONS[0]
        key=result_key(value['request']) if guard.receipt else intent_key(value['request'])
        if ([(s,k,v) for s,k,v in payload['put'] if k]!=[(section,key,value)] or inputs!=event_inputs(value) or
                self.budget._metadata(db)!=value['request']['expected_state_version']):
            raise Conflict('candidate output exact issued mutation required')
        self._dependencies(db,section,value,guard.read)

    @contextmanager
    def _held(self):
        workspace=self.runtime.workspace
        with (workspace._lock,workspace.working._lock,self.runtime.plans._lock,
                self.runtime.plans.installation._lock,self.runtime.plans.installation.builder._lock,self.runtime._lock):
            yield

    @contextmanager
    def _live_transaction(self,token):
        if self._active is not None:raise Conflict('nested candidate output writer refused')
        try:
            with self.controller.token_transaction(token,read_bytes=PREPARATION_READ_BYTES,
                    _commit_context=self._held,
                    _before_commit=lambda:self._active.check(),
                    _after_final_sample=lambda now,mono:self._deadlines(self._active,now,mono)) as context:
                yield context
        finally:self._active=None

    def _put(self,db,read,section,value,row,*,receipt=False,token=None):
        key=result_key(value['request']) if receipt else intent_key(value['request'])
        validate_record(section,key,value);self._dependencies(db,section,value,read)
        payload={'format':2,'put':[[section,key,value]],'delete':[],'details':None}
        present=read.object(section,'') is not None
        tip,_=self.store._candidate_output_summary(db,section,value['request']['expected_state_version'])
        if present!=(tip is not None):raise Conflict('candidate output original domain tip differs')
        if not present:payload['put'].append([section,'',{}])
        guard=_Guard(self,db,read,row,value,receipt=receipt,token=token);self._active=guard
        guard.check()
        if not receipt:row['request']=value['request']
        self.store._commit(db,EVENTS[SECTIONS.index(section)],key,payload,value['request']['expected_state_version'],
            digest(value),'hybrid-core',event_inputs(value),_authorization=guard)
        guard.check();return guard

    def apply(self,lease,token,*,idempotency_key,expected_state_version):
        """One durable intent and one exact original-inode pwrite, never replay."""
        self._actual();self.controller._refuse_nested_writer();self.controller._issued(token)
        self.runtime._unit_check(self.runtime._issued(lease))
        with self.runtime.pool._lock,self._lock:
            attempt,terminal,free=self._original(lease)
            request={k:terminal['request'][k] for k in ('project_id','data_mode','store_epoch','goal_ref')}
            request.update(idempotency_key=idempotency_key,expected_state_version=expected_state_version,
                terminal_key=entry_key(terminal['request']),terminal_hash=digest(terminal))
            validate_schema(SCOPE,request)
            if type(expected_state_version) is not int:raise Conflict('candidate output actual CAS integer required')
            row=self._rows.get(id(lease))
            if row is None:
                if len(self._rows)>=32:raise Conflict('finite original candidate output capacity reached')
                row={'lease':lease,'material':CandidateOutputMaterial(self.runtime,lease),'intent':None,'request':None,'witness':None}
                self._rows[id(lease)]=row
            elif row['request'] is not None and row['request']!=request:raise Conflict('candidate output original request changed')
            if row['material'].write_entered:raise Conflict('candidate output original write entered; explicit reconcile only')
            key=intent_key(request)
            with self.store.read_connection() as db:
                db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
                if read.object(SECTIONS[0],key) is not None:
                    row['intent']=self._point(db,SECTIONS[0],key,read)
                    if row['intent']['request']!=request:raise Conflict('candidate output intent key reused')
                else:row['intent']=None
            if row['intent'] is None:
                with row['material'].witness() as witness:
                    row['witness']=witness
                    with self._live_transaction(token) as (db,read,control):
                        if self.budget._metadata(db)!=expected_state_version:raise Conflict('candidate output stale intent version')
                        sources=source_binding(self.budget._load(db,request['goal_ref'],read));_,mono=self.controller._sample()
                        value={'schema_version':'1.0','request':request,'request_hash':digest(request),'sources':sources,
                            'controller':self._control_ref(control),'controller_checked_monotonic_ns':mono,
                            'accepted_state_version':expected_state_version+1,'recorded_at':sources['evaluated_at'],
                            'pool_free':free,'result_hash':digest(terminal['request']['fixture_runtime']['engineering_patch_result']),
                            'base_tree':row['material'].base_tree,'target':TARGET,'target_identity':row['material'].target_identity,
                            'before_sha256':hash_bytes(BEFORE),'after_sha256':hash_bytes(AFTER),
                            'goal_completed':False,'independent_review_status':'NOT_PERFORMED','dispatch_enabled':False,
                            'state':'FIXED_WRITE_INTENT','execution_authority':'ACTUAL_ORIGINAL_CORE_APPLIER_ONLY'}
                        self._put(db,read,SECTIONS[0],value,row,token=token)
                        # Remember the original attempt before uncertain COMMIT return.
                        row['intent']=value
            with row['material'].witness(effect=True) as witness:
                row['witness']=witness
                with self._live_transaction(token) as (db,read,control):
                    intent=self._point(db,SECTIONS[0],key,read)
                    if intent!=row['intent'] or self.budget._metadata(db)!=intent['accepted_state_version']:
                        raise Conflict('candidate output original intent/CAS changed before write')
                    guard=_Guard(self,db,read,row,intent,token=token);self._active=guard
                    guard.check();row['material'].begin_fd(witness[1])
                    row['material'].apply_once(guard)
                    row['material'].close_fd();guard.check()
            return self.reconcile(lease)

    def reconcile(self,lease):
        """Original already-entered write readback only; no token, no rewrite."""
        self._actual();self.controller._refuse_nested_writer()
        with self.runtime.pool._lock,self._lock:
            row=self._rows.get(id(lease))
            if row is None or row['lease'] is not lease or row['intent'] is None or not row['material'].write_entered:
                raise PermissionError('actual original entered write required; history cannot reconstruct it')
            material=row['material']
            if material.fd is not None:material.close_fd()
            with material.witness(after=True) as witness:
                row['witness']=witness
                try:
                    with self.store.lock(),self.store.connect() as db,self._held():
                        db.execute('BEGIN IMMEDIATE');read=ReadBudget(db,PREPARATION_READ_BYTES)
                        prior=self._point(db,SECTIONS[0],intent_key(row['request']),read)
                        if prior!=row['intent']:raise Conflict('candidate output original durable intent differs')
                        request={**row['request'],'expected_state_version':self.budget._metadata(db),
                            'intent_key':intent_key(row['request']),'intent_hash':digest(prior)}
                        key=result_key(request)
                        if read.object(SECTIONS[1],key) is not None:
                            result=self._point(db,SECTIONS[1],key,read)
                            return {'fact':result,'duplicate':True,'execution_authority':'NONE'}
                        tree,tests=material.capture(witness[1],witness[2]);now,_=self.controller._sample()
                        value={k:v for k,v in prior.items() if k not in ('state','execution_authority')}
                        value.update(request=request,request_hash=digest(request),accepted_state_version=request['expected_state_version']+1,
                            recorded_at=now.isoformat().replace('+00:00','Z'),
                            sources={**prior['sources'],'source_version':request['expected_state_version']},
                            state='OUTPUT_CAPTURED_AUDIT_ONLY',output_tree=tree,actual_tests=tests,
                            candidate_write_performed=True,candidate_write_fd_closed=True)
                        guard=self._put(db,read,SECTIONS[1],value,row,receipt=True)
                        guard.check();db.commit()
                        return {'fact':value,'duplicate':False,'execution_authority':'NONE'}
                finally:self._active=None

    def accept_machine(self,lease,*,output_key,idempotency_key,expected_state_version):
        """Original-cap read-only disposition, not current Goal acceptance.

        Does not rewrite, launch, renew consent, or replace independent review.
        Explicit CAS/client key binds the original derived receipt permanently.
        """
        self._actual();self.controller._refuse_nested_writer()
        from .hybrid_engineering_cold_verifier import verify,implementation_hash
        validate_schema(ID,output_key);validate_schema(ID,idempotency_key)
        with self.runtime.pool._lock,self._lock:
            row=self._rows.get(id(lease))
            if row is None or row['lease'] is not lease or row['intent'] is None:
                raise PermissionError('actual original candidate output required; no cold acceptance capability')
            material=row['material'];material.check_hold(receipt=True)
            with material.witness(after=True) as witness:
                row['witness']=witness
                try:
                    with self.store.lock(),self.store.connect() as db,self._held():
                        db.execute('BEGIN IMMEDIATE');read=ReadBudget(db,PREPARATION_READ_BYTES)
                        prior=self._point(db,SECTIONS[1],output_key,read)
                        if 'machine_verification' in prior:raise Conflict('candidate acceptance requires plain original output')
                        if prior['request']['intent_key']!=intent_key(row['request']):raise Conflict('candidate acceptance original cap/output differs')
                        request={**prior['request'],'idempotency_key':idempotency_key,'expected_state_version':expected_state_version,
                            'prior_output_key':output_key,'prior_output_hash':digest(prior)}
                        validate_schema(SCOPE,request)
                        if type(expected_state_version) is not int:raise Conflict('candidate acceptance actual CAS integer required')
                        key=result_key(request)
                        existing=read.object(SECTIONS[1],key)
                        if existing is not None:
                            existing=self._point(db,SECTIONS[1],key,read)
                            if existing['request']!=request:raise Conflict('candidate acceptance idempotency request changed')
                            return {'fact':existing,'duplicate':True,'execution_authority':'NONE'}
                        self.runtime._unit_check(self.runtime._issued(lease))
                        if self.budget._metadata(db)!=expected_state_version:raise Conflict('candidate acceptance stale writer version')
                        if implementation_hash()!=self._cold_verifier_hash:raise Conflict('candidate acceptance protected AST verifier changed')
                        actual=material._read_target(witness[1],AFTER,witness[2]);machine=verify(actual,implementation=self._cold_verifier_hash)
                        now,_=self.controller._sample()
                        value={**prior,'request':request,'request_hash':digest(request),
                            'accepted_state_version':expected_state_version+1,'recorded_at':now.isoformat().replace('+00:00','Z'),
                            'sources':{**prior['sources'],'source_version':expected_state_version},'machine_verification':machine}
                        guard=self._put(db,read,SECTIONS[1],value,row,receipt=True)
                        guard.check()
                        self.runtime._unit_effect_check(self.runtime._leases[id(lease)])
                        db.commit()
                        return {'fact':value,'duplicate':False,'execution_authority':'NONE'}
                finally:self._active=None
