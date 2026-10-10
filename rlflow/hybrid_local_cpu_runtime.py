"""Exact configurable CPU owner; original Core budget/Pool writers only.

No model, GPU, production scope, fixed-profile grant upgrade or cold adoption.
"""
from dataclasses import dataclass
import json
import os
import uuid

from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_local_cpu_profile import KIND, approved_binding, module_pins, validate_bound_spec
from .hybrid_reads import ReadBudget
from .store import Conflict, canonical, PREPARATION_READ_BYTES


@dataclass(frozen=True,eq=False)
class LocalCpuGrant:
    id: str
    raw: bytes


class LocalCpuRunnerOwner(FixtureRuntimeOwner):
    def shutdown(self):
        self._actual();self._safety_freeze=True
        # STOP never waits for the whole run/sequence. Finish only an already
        # admitted bounded preparation step before closing original handles.
        with self._workflow_cpu_admission_lock:return super().shutdown()

    def shutdown_safety(self):
        self._actual();self._safety_freeze=True
        with self._workflow_cpu_admission_lock:value=super().shutdown_safety()
        # Compatibility state names are not a whole managed-scope proof.
        # Lost report/job receipts never become terminal/FREE by retirement.
        return {**value,'retirement_scope':'ORIGINAL_PARENT_HANDLES_ONLY',
                'managed_scope_status':'UNKNOWN'}

    def _actual(self):
        from .hybrid_fixture_runtime import _owners
        if type(self) is not LocalCpuRunnerOwner or _owners.get(id(self)) is not self:
            raise PermissionError('exact original configured CPU owner required')
        super()._actual()

    def _issued(self,lease):
        attempt=super()._issued(lease)
        if attempt['origin']['kind']!=KIND or attempt.get('local_cpu_grant') is None or canonical(attempt['origin'])!=lease.raw:
            raise PermissionError('configured CPU owner cannot operate another kind')
        return attempt

    def issue_cpu_trial_grant(self,*args,**kwargs):raise PermissionError('no fixed CPU grant upgrade')
    def issue_engineering_patch_grant(self,*args,**kwargs):raise PermissionError('no fixed engineering grant upgrade')

    def execute_workflow_cpu(self,token):
        """Derive and execute the single original A candidate CPU stage.

        No caller candidate, checks, limits, plan or reservation is accepted.
        Concurrent/reentrant calls fail rather than waiting across a writer.
        An uncertain preparation failure latches this sequence: never allocate
        a replacement reservation/Workspace/claim or silently retry dispatch.
        Existing original handles remain available for explicit safe cleanup.
        """
        from .hybrid_budget import zero
        from .hybrid_budget_ledger import reservation_key
        from .store import sha
        self._actual();self.controller._refuse_nested_writer()
        self.controller._issued(token)
        if self._workflow_handoff is None:
            raise PermissionError('original A workflow CPU handoff required')
        if not self._workflow_cpu_sequence_lock.acquire(blocking=False):
            raise Conflict('original CPU sequence already active')
        try:
            sequence=self._workflow_cpu_sequence
            if sequence is not None:
                if sequence['token'] is not token:
                    raise PermissionError('original CPU sequence token required')
                if sequence['complete']:
                    receipt=self._workflow_cpu_completed
                    if receipt is None or receipt[0] is not sequence or receipt[1] is not sequence['lease']:
                        raise PermissionError('original completed CPU sequence and lease required')
                    self._issued(receipt[1])
                    return json.loads(receipt[2])
                raise Conflict('original CPU sequence outcome unresolved; no redispatch')
            self.controller.check_token(token)
            parent=json.loads(self._workflow_handoff_raw[1])
            with self.store.read_connection() as db:
                db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
                loaded=self.budget._load(db,parent['request']['goal_ref'],read)
                binding,_,_=self._workflow_cpu_material(loaded)
                from .hybrid_a_workflow_accounting import check_window
                probe={k:parent['request'][k] for k in ('project_id','data_mode','goal_ref','store_epoch','reservation_id')}
                probe['action']='MARK_UNKNOWN'
                head,_,_=self.budget._heads(db,probe,read,self.budget._metadata(db))
                if head is None or 'workflow' not in head or 'candidate_cpu_entry' in head['workflow']:
                    raise Conflict('original unique CPU stage required before reservation')
                now,_=self.controller._sample();check_window(head['workflow'],binding['workflow'],now)
                if head['workflow']['controlled_seconds_charged']+binding['task_seconds']+10>binding['workflow']['limits']['controlled_seconds']:
                    raise Conflict('workflow CPU controlled time quota exceeded before reservation')
            key='a_cpu_'+sha([binding['workflow']['parent'],binding['workflow']['envelope_sha256']])
            sequence={'token':token,'complete':False,'lease':None,'phase':'RESERVE',
                'observation':None,'bundle':None,'claim':None,'grant':None}
            self._workflow_cpu_sequence=sequence
            def step(phase,operation,field=None):
                with self._workflow_cpu_admission_lock:
                    self._actual()
                    if self._safety_freeze:raise Conflict('original CPU sequence frozen for cleanup')
                    sequence['phase']=phase
                    value=operation()
                    if field is not None:sequence[field]=value
                    return value
            request={k:parent['request'][k] for k in ('project_id','data_mode','goal_ref','store_epoch')}
            intent=parent['preparation']['intent_key']
            reserve={**request,'idempotency_key':key+'_reserve','expected_state_version':self.store.version(),
                'action':'RESERVE','preparation_intent_key':intent,
                'amount':{**zero(),'wall_seconds':binding['task_seconds']+10},'purpose':'EXECUTION'}
            sequence['reserve']=reserve
            step('RESERVE',lambda:self.budget.record(reserve,token))
            observation=step('WORKSPACE_STAGE',lambda:self.workspace.stage(intent,ttl_seconds=60),'observation')
            value=json.loads(observation.raw)
            acquire={**request,'idempotency_key':key+'_workspace','expected_state_version':self.store.version(),
                'expected_workspace_revision':0,'workspace_id':value['workspace_id'],
                'reservation_id':reservation_key(reserve),'operation':'acquire','ttl_seconds':60}
            sequence['acquire']=acquire
            step('WORKSPACE_ACQUIRE',lambda:self.workspace.record(acquire,token,observation))
            bundle=step('PLAN',lambda:self.plans.prepare_plan(token,observation,key+'_plan'),'bundle')
            step('PLAN_INTENT',lambda:self.plans.persist_intent(bundle,token,observation,expected_version=self.store.version()))
            step('PLAN_PUBLISH',lambda:self.plans.publish(bundle,token,observation,expected_version=self.store.version()))
            claim=step('CLAIM',lambda:self.pool.claim(self.membership,expected_version=self.pool.snapshot()['version'],request_key=key+'_claim',seconds=60),'claim')
            grant=step('GRANT',lambda:self.issue_local_cpu_grant(bundle,token,observation),'grant')
            lease=step('REGISTER',lambda:self.register(bundle,token,observation,claim,request_key=key+'_task',scenario='local_cpu',local_cpu_grant=grant),'lease')
            sequence['phase']='RUN'
            result=self.run_local_cpu(lease)
            with self._workflow_cpu_admission_lock:
                self._workflow_cpu_completed=(sequence,lease,canonical(result))
                sequence['complete']=True;sequence['phase']='COMPLETE'
            return result
        finally:self._workflow_cpu_sequence_lock.release()

    def _binding(self,loaded):
        config=json.loads(self.plans.registry._raw)
        if self._workflow_handoff is not None:
            binding,_,_=self._workflow_cpu_material(loaded)
            return binding
        binding=approved_binding(loaded['record']['contract']['proposal'],config,self.program_hash)
        if config['tools']['local_cpu']['definition']['modules']!=module_pins():
            raise Conflict('original approved CPU trusted programs changed')
        return binding

    def _workflow_cpu_material(self,loaded,*,config=None):
        from .hybrid_a_workflow_cpu import from_engineer
        from .hybrid_goals import digest
        from .hybrid_budget_ledger import entry_key
        row=self._workflow_handoff
        if row is None or not row['retired'] or row['child'] is not self:
            raise PermissionError('original workflow CPU handoff required')
        if self._workflow_handoff_raw!=(row['material'],row['parent']):
            raise PermissionError('original frozen workflow CPU handoff changed')
        parent=json.loads(row['parent']);material=json.loads(row['material'])
        with self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            original=self.budget._point(db,entry_key(parent['request']),read)
            if original!=parent:raise Conflict('original workflow CPU parent event changed')
            self.budget._dependencies(db,parent,read)
        if any(parent['policy_source'][key]!=loaded[key] for key in
                ('proposal_hash','approval_hash','config_hash','scope_hash')):
            raise Conflict('current original CPU parent approval changed')
        pins=module_pins()
        config=json.loads(self.plans.registry._raw) if config is None else config
        if digest(config)!=loaded['config_hash']:
            raise Conflict('original workflow CPU registry changed')
        binding,spec=from_engineer(loaded['record']['contract']['proposal'],config,
            self.program_hash,parent,pins)
        if material['binding']!=binding or material['spec']!=spec or material['pins']!=pins:
            raise Conflict('original workflow CPU material changed')
        return binding,spec,pins

    def _workflow_allocation_material(self,attempt,binding,config):
        """Also used on durable REGISTER allocation retries, before any IO."""
        from .hybrid_goals import digest
        if digest(config)!=binding['config_hash'] or binding!=attempt['origin']['local_cpu']:
            raise Conflict('original workflow CPU allocation registry or binding changed')
        request=attempt['entries']['REGISTER_NO_HANDOFF']['request']
        with self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            loaded=self.budget._load(db,request['goal_ref'],read)
            expected,spec,pins=self._workflow_cpu_material(loaded,config=config)
        expected.update(grant_id=binding['grant_id'],**{key:loaded[key] for key in
            ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if expected!=binding:raise Conflict('original workflow CPU allocation derivation changed')
        return spec,pins

    def issue_local_cpu_grant(self,bundle,token,observation):
        self._actual();self.controller._issued(token);self._plan_original(bundle,token,observation)
        with self.pool._lock,self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            loaded=self.budget._load(db,self._ready_for_bundle(bundle)['request']['goal_ref'],read)
            binding=self._binding(loaded)
            if self._workflow_handoff is not None:
                _,spec,modules=self._workflow_cpu_material(loaded)
                validate_bound_spec(spec,binding)
                from .hybrid_a_workflow_accounting import check_window
                captured=self._ready_for_bundle(bundle)['source_context']['budget_reservation']
                request={**captured['scope'],'action':'MARK_UNKNOWN','reservation_id':captured['reservation_id']}
                head,_,_=self.budget._heads(db,request,read,self.budget._metadata(db))
                if head is None or 'workflow' not in head or 'candidate_cpu_entry' in head['workflow']:
                    raise Conflict('original unique CPU stage required')
                now,_=self.controller._sample();check_window(head['workflow'],binding['workflow'],now)
            else:
                spec=validate_bound_spec(json.loads(self.plans.registry._raw)['tools']['local_cpu']['definition']['spec'],binding)
                modules=json.loads(self.plans.registry._raw)['tools']['local_cpu']['definition']['modules']
            from .hybrid_goals import digest
            if digest(modules)!=binding['modules_sha256']:raise Conflict('original approved CPU module pins changed')
            binding.update({key:loaded[key] for key in ('proposal_hash','approval_hash','config_hash','scope_hash')})
            with self._lock:
                if len(self._local_cpu_grants)>=32:raise Conflict('finite configured CPU grants exceeded')
                key='local_cpu_grant_'+uuid.uuid4().hex;binding['grant_id']=key
                grant=LocalCpuGrant(key,canonical(binding))
                self._local_cpu_grants[id(grant)]={'grant':grant,'bundle':bundle,'token':token,
                    'observation':observation,'attempt':None,'spec_raw':canonical(spec),'modules_raw':canonical(modules)}
                return grant

    def _issued_local_cpu_grant(self,grant,bundle,token,observation):
        self._actual();row=self._local_cpu_grants.get(id(grant))
        if (type(grant) is not LocalCpuGrant or row is None or row['grant'] is not grant or
                any(row[key] is not value for key,value in
                    (('bundle',bundle),('token',token),('observation',observation)))):
            raise PermissionError('same-original-plan configured CPU grant required')
        return row

    def _fresh_local_cpu(self,loaded,attempt):
        grant=attempt['local_cpu_grant']
        row=self._issued_local_cpu_grant(grant,attempt['bundle'],attempt['token'],attempt['observation'])
        expected=self._binding(loaded)
        expected.update(grant_id=grant.id,**{key:loaded[key] for key in
                                         ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if row['attempt'] is not attempt or canonical(expected)!=grant.raw:
            raise Conflict('current original configurable CPU approval differs')
        if 'workflow' in expected:
            from .hybrid_a_workflow_accounting import check_window
            active=self.controller._token_active
            if active is None:raise PermissionError('original CPU workflow transaction required')
            captured=attempt['ready']['source_context']['budget_reservation']
            request={**captured['scope'],'action':'MARK_UNKNOWN','reservation_id':captured['reservation_id']}
            head,_,_=self.budget._heads(active[0],request,active[2],self.budget._metadata(active[0]))
            if head is None or head['workflow']['approval_sha256']!=loaded['approval_hash']:
                raise Conflict('original CPU workflow head or approval changed')
            now,_=self.controller._sample();check_window(head['workflow'],expected['workflow'],now)
        if attempt['source'] is not None:
            with self.sources._lock:self.sources._physical(self._original_source(attempt))

    def _final_deadlines(self,guard,now,mono):
        super()._final_deadlines(guard,now,mono)
        binding=json.loads(guard.attempt['local_cpu_grant'].raw)
        if 'workflow' in binding:
            from .hybrid_a_workflow_accounting import check_window
            from .hybrid_budget_ledger import SECTIONS as BUDGET
            head=next(iter(guard.expected_heads[BUDGET[1]].values()))
            check_window(head['workflow'],binding['workflow'],now)

    def _original_source(self,attempt):
        from .hybrid_local_cpu_source import LocalCpuSourceOwner
        if type(self.sources) is not LocalCpuSourceOwner:
            raise PermissionError('exact original configured CPU source owner required')
        self.sources._actual()
        source=attempt['source']
        row=(self.sources._issued(source) if source is not None else
             self.sources._attempts.get(id(attempt['claim'])))
        if row is None:return None
        if (row['claim'] is not attempt['claim'] or row['membership'] is not self.membership or
                row['scenario']!='runtime.local_cpu' or
                (row['runtime'] is not attempt and not
                 (source is None and row['runtime'] is None and not row['launch_entered']))):
            raise PermissionError('same original configured CPU source/claim required before cleanup')
        return row

    def check_guard(self,db,guard):
        self._issued(guard.attempt['lease'])
        value=super().check_guard(db,guard)
        recorded=json.loads(guard.raw)['request']['fixture_runtime']
        expected=None if recorded['phase']=='REGISTER_NO_HANDOFF' else self._recovery_source(guard.attempt)
        if recorded.get('local_cpu_recovery_source')!=expected:
            raise Conflict('original configured CPU recovery publication source differs')
        expected_key=self._recovery_public_key(guard.attempt,recorded['phase'])
        if recorded['phase'] in ('STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'):
            prior=json.loads(guard.raw)['prior_reservation'].get('fixture_runtime')
            if prior is None or prior.get('local_cpu_recovery_public_key') is None:expected_key=None
        if recorded.get('local_cpu_recovery_public_key')!=expected_key:
            raise Conflict('original configured CPU recovery public key differs')
        expected_scope=self._recovery_scope_binding(guard.attempt,recorded['phase'])
        if recorded['phase'] in ('STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'):
            prior=json.loads(guard.raw)['prior_reservation'].get('fixture_runtime')
            if prior is None or prior.get('local_cpu_scope_binding') is None:expected_scope=None
        if recorded.get('local_cpu_scope_binding')!=expected_scope:
            raise Conflict('original configured CPU scope recovery binding differs')
        return value

    def _recovery_scope_binding(self,attempt,phase):
        row=self._original_source(attempt)
        if (phase in ('REGISTER_NO_HANDOFF','HANDOFF_UNKNOWN') or row is None or
                attempt['producer_identity'] is None or row.get('scope_runtime_raw') is None):return None
        expected={'scope':row['ready']['scope_binding'],'transport':row['transport_identity'],
            'owner':attempt['origin']['owner'],'keeper':row['ready']['keeper'],
            'manager_producers_closed':True,'process_view':row['scope_process_view']}
        if canonical(expected)!=row['scope_runtime_raw']:
            raise Conflict('original scope/transport recovery source differs')
        return expected

    def _recovery_public_key(self,attempt,phase):
        row=self._original_source(attempt)
        if phase in ('REGISTER_NO_HANDOFF','HANDOFF_UNKNOWN') or row is None or row.get('ready') is None:
            return None
        if attempt['producer_identity'] is None:return None
        return row['ready']['recovery_public_key']

    def _recovery_source(self,attempt):
        row=self._original_source(attempt)
        if row is None or not row.get('local_allocated'):return None
        binding=json.loads(row['source'].raw)['local_cpu_binding']
        return {'source_id':row['source'].id,'path':str(row['path']),'chain':row['chain'],
                'config_sha256':binding['config_sha256'],'unit':binding['unit'],
                'files':{name:[*row['identities'][name],os.geteuid()]
                    for name in ('task-report','task-stdout','task-stderr')}}

    def _terminal_scope(self):return 'ORIGINAL_CONFIGURED_CPU_SERVICE'

    def _stop_original_participant(self,lease):
        attempt=self._issued(lease)
        with self.pool._lock,self._lock,self.sources._lock:
            retained=self._original_source(attempt)
            if retained is not None:self.sources._cleanup_attempt(retained)
            if attempt['spawn_entered'] and attempt['producer_identity'] is None:
                raise Conflict('original service handoff UNKNOWN; no adoption/refund')

    def _terminal_extra(self,attempt):
        row=self._original_source(attempt)
        return {'managed_service_proof':None if row is None else row.get('managed_terminal'),
                'configured_local_result':None if attempt.get('local_result_raw') is None else
                    json.loads(attempt['local_result_raw']),
                'local_cpu_release_attempted':attempt['release_entered'],
                'disk_enforcement':'PARTIAL_NO_HARD_QUOTA'}

    def _check_terminal(self,attempt):
        super()._check_terminal(attempt)
        cached=None if attempt.get('local_result_raw') is None else json.loads(attempt['local_result_raw'])
        if attempt['terminal']['configured_local_result']!=cached:
            raise Conflict('original configured CPU cached result differs from terminal')
        row=self._original_source(attempt)
        if row is not None:
            if row['status']!='CLOSED' or any(fd is not None for fd in row['fds'].values()):
                raise Conflict('original configured CPU partial source closure required')
            if attempt['spawn_entered'] and row.get('managed_terminal') is None:
                raise Conflict('original full managed service terminal proof required')
            if attempt['terminal']['managed_service_proof']!=row.get('managed_terminal'):
                raise Conflict('original configured CPU managed proof changed')

    def start(self,lease):
        attempt=self._issued(lease)
        if attempt.get('source_stop_latched') or attempt.get('physical_safety_freeze') or self._safety_freeze:
            raise Conflict('original configured CPU STOP forbids dispatch')
        return super().start(lease)

    def poll(self,lease,*,seal=False):
        value=super().poll(lease,seal=seal)
        value.update(fixed_cpu_scope_only=False,configured_local_cpu_only=True)
        return value

    def collect_local_result(self,lease):
        import hashlib
        import os
        attempt=self._issued(lease);row=self._original_source(attempt)
        with self.sources._lock:
            if attempt.get('local_result_raw') is not None:
                return json.loads(attempt['local_result_raw'])
            self.sources.poll(attempt['source'])
            closed=row['task_closed']
            if closed is None or not attempt['release_entered'] or not closed['stopped']['release_attempted']:
                raise Conflict('original configured task terminal after G required')
            from .hybrid_local_cpu_result import execution_from_closed,evaluate_execution
            execution=execution_from_closed(closed['task'],closed['stopped'])
            output={}
            for name,key in (('stdout','task_read'),('stderr','task_error_read')):
                raw=os.pread(row['fds'][key],65537,0)
                if len(raw)>65536:raise Conflict('bounded original task output required')
                output[name]={'text':raw.decode(),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}
            from .hybrid_local_cpu_profile import evaluate_output
            spec=self.sources._runtime_spec(row)
            value={'lease_id':lease.id,'source_id':attempt['source'].id,
                    'task':closed['task'],'outputs':output,
                    'approved_spec_sha256':attempt['origin']['local_cpu']['spec_sha256'],
                    'approved_acceptance':spec.get('acceptance'),
                    'machine_acceptance':evaluate_execution(spec.get('acceptance'),output,execution),
                    'execution':execution,
                    'independent_review_status':'NOT_PROVEN','condition_evidence':False}
            # Reserve room inside unchanged Budget/terminal envelopes for the
            # manager receipt and original references. UTF-8 byte bounds alone
            # do not bound JSON escaping. A rejected result NEVER enters cache.
            from .hybrid_goals import check_bytes
            from .hybrid_protocol import ProtocolError
            try:check_bytes(value,128*1024)
            except ProtocolError as exc:
                raise Conflict('configured CPU result exceeds canonical bound; result unavailable') from exc
            attempt['local_result_raw']=canonical(value)
            return json.loads(attempt['local_result_raw'])

    def run_local_cpu(self,lease):
        """Original configured task/result/STOP; machine FAIL never completes Goal."""
        import time
        attempt=self._issued(lease)
        if attempt['terminal'] is not None:
            self.stop_to_terminal(lease)
            return self.collect_local_result(lease)
        try:
            self.start(lease)
            end=time.monotonic()+self.sources._runtime_spec(self._original_source(attempt))['seconds']+2
            while time.monotonic()<end:
                self.poll(lease)
                row=self._original_source(attempt)
                if row['task_closed'] is not None:return self.collect_local_result(lease)
                time.sleep(.01)
            raise Conflict('finite configured CPU result deadline exceeded')
        finally:self.stop_to_terminal(lease)
