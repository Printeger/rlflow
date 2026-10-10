"""Original generating grant and approval-bound, same-lease native launch.

Launching requires a separately issued original capability and current effects
fences. It never promotes inputs into postexecution account/source/usage proof.
"""
from dataclasses import dataclass
import json
import hashlib
import uuid
import threading

from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_native_model_profile import KIND, approved_binding
from .hybrid_goals import digest, check_bytes
from .hybrid_reads import ReadBudget
from .store import Conflict, canonical, PREPARATION_READ_BYTES
from .hybrid_engineering_candidate import _snapshot


def bind_packet(packet, binding, intent, proposal):
    """Data equality against already-proven original plan; NOT provenance."""
    if type(packet) is not dict or set(packet) != {'role','files','objective','conditions'}:
        raise Conflict('closed approved engineering packet required')
    files = _snapshot(packet['files']); plan = intent['plan']
    manifest = [{'name':name, 'bytes':len(text.encode('utf-8')),
        'sha256':'sha256:'+hashlib.sha256(text.encode('utf-8')).hexdigest(), 'mode':0o600}
        for name,text in sorted(files.items())]
    if (packet['role'] != binding['role'] or plan['packet']['role'] != binding['role'] or
            packet['objective'] != proposal['objective'] or packet['conditions'] != proposal['global_conditions'] or
            digest(files) != binding['candidate_sha256'] or manifest != plan['working_tree']['files'] or
            digest(packet) != binding['packet_sha256']):
        raise Conflict('actual packet differs from original plan/task/candidate role')
    return canonical(packet)


@dataclass(frozen=True, eq=False)
class NativeModelGrant:
    id: str
    raw: bytes


@dataclass(frozen=True, eq=False)
class NativeModelLaunch:
    id: str
    raw: bytes


class NativeModelOwner(FixtureRuntimeOwner):
    def __init__(self,*args,**kwargs):
        self._native_launches={}
        self._native_releases={}
        self._launch_active=None
        super().__init__(*args,**kwargs)

    def _actual(self):
        if type(self) is not NativeModelOwner:
            raise PermissionError('exact generating model owner required')
        super()._actual()

    def _issued(self, lease):
        attempt = super()._issued(lease)
        if (attempt['origin']['kind'] != KIND or attempt.get('native_model_grant') is None or
                canonical(attempt['origin']) != lease.raw):
            raise PermissionError('generating owner cannot operate another grant kind')
        return attempt

    def issue_cpu_trial_grant(self, *args, **kwargs):raise PermissionError('closed generating owner')
    def issue_engineering_patch_grant(self, *args, **kwargs):raise PermissionError('closed generating owner')

    def _binding(self, loaded, *, workflow=None, intent=None, ready=None):
        if workflow is not None:
            from .hybrid_a_workflow_derivation import first_engineer
            binding,_,_=first_engineer(loaded['record']['contract']['proposal'],
                json.loads(self.plans.registry._raw),self.program_hash,intent,ready,workflow['files'])
            if binding['workflow']!=workflow:raise Conflict('original workflow derivation changed')
            return binding
        return approved_binding(loaded['record']['contract']['proposal'],
            json.loads(self.plans.registry._raw), self.program_hash)

    def issue_native_model_grant(self, bundle, token, observation, *, packet, output_schema,
                                 _workflow=False):
        self._actual(); self.controller._issued(token)
        intent, ready = self._plan_original(bundle, token, observation)
        check_bytes(packet, 60000); check_bytes(output_schema, 8192)
        if type(packet) is not dict or type(output_schema) is not dict:
            raise Conflict('bounded frozen packet/schema objects required')
        packet_raw = canonical(packet); schema_raw = canonical(output_schema)
        with self.pool._lock, self.store.read_connection() as db:
            db.execute('BEGIN'); read = ReadBudget(db, PREPARATION_READ_BYTES)
            loaded = self.budget._load(db, self._ready_for_bundle(bundle)['request']['goal_ref'], read)
            if _workflow:
                from .hybrid_a_workflow_derivation import first_engineer
                binding,derived,schema=first_engineer(loaded['record']['contract']['proposal'],
                    json.loads(self.plans.registry._raw),self.program_hash,intent,ready,packet['files'])
                if packet!=derived or output_schema!=schema:
                    raise Conflict('original first Engineer workflow packet/schema required')
            else:binding = self._binding(loaded)
            if digest(packet) != binding['packet_sha256'] or digest(output_schema) != binding['output_schema_sha256']:
                raise Conflict('actual packet/schema differs from original generating approval')
            packet_raw = bind_packet(packet, binding, intent, loaded['record']['contract']['proposal'])
            binding.update({k: loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
            with self._lock:
                if len(self._native_model_grants) >= 32:
                    raise Conflict('finite generating grants exceeded')
                key = 'native_model_grant_' + uuid.uuid4().hex; binding['grant_id'] = key
                grant = NativeModelGrant(key, canonical(binding))
                self._native_model_grants[id(grant)] = dict(grant=grant, bundle=bundle, token=token,
                    observation=observation, attempt=None, packet_raw=packet_raw, schema_raw=schema_raw)
                return grant

    def issue_workflow_engineer_grant(self,bundle,token,observation,*,files):
        """Only first original Engineer, not an unproven Reviewer/continuation."""
        self._actual();self.controller._issued(token)
        intent,ready=self._plan_original(bundle,token,observation)
        with self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            loaded=self.budget._load(db,self._ready_for_bundle(bundle)['request']['goal_ref'],read)
            captured=ready['source_context']['budget_reservation']
            request={**captured['scope'],'action':'MARK_UNKNOWN','reservation_id':captured['reservation_id']}
            head,_,_=self.budget._heads(db,request,read,self.budget._metadata(db))
            if head is not None and 'workflow' in head:
                raise Conflict('workflow first Engineer already registered; no new first grant')
            from .hybrid_a_workflow_derivation import first_engineer
            _,packet,schema=first_engineer(loaded['record']['contract']['proposal'],
                json.loads(self.plans.registry._raw),self.program_hash,intent,ready,files)
        return self.issue_native_model_grant(bundle,token,observation,packet=packet,
            output_schema=schema,_workflow=True)

    def _issued_native_model_grant(self, grant, bundle, token, observation):
        self._actual(); row = self._native_model_grants.get(id(grant))
        if (type(grant) is not NativeModelGrant or row is None or row['grant'] is not grant or
                any(row[k] is not v for k,v in (('bundle',bundle),('token',token),('observation',observation)))):
            raise PermissionError('original same-plan generating grant required')
        return row

    def _fresh_native_model(self, loaded, attempt):
        grant = attempt['native_model_grant']
        row = self._issued_native_model_grant(grant, attempt['bundle'], attempt['token'], attempt['observation'])
        frozen=json.loads(grant.raw)
        intent,ready=self._plan_original(attempt['bundle'],attempt['token'],attempt['observation'])
        expected = self._binding(loaded,workflow=frozen.get('workflow'),intent=intent,ready=ready)
        expected.update(grant_id=grant.id, **{k:loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if row['attempt'] is not attempt or canonical(expected) != grant.raw:
            raise Conflict('current original generating approval differs')
        if 'workflow' in frozen:
            from .hybrid_a_workflow_accounting import check_window
            active=self.controller._token_active
            if active is None:raise PermissionError('original workflow Controller transaction required')
            captured=attempt['ready']['source_context']['budget_reservation']
            request={**captured['scope'],'action':'MARK_UNKNOWN','reservation_id':captured['reservation_id']}
            version=self.budget._metadata(active[0])
            head,_,_=self.budget._heads(active[0],request,active[2],version)
            if head is None:raise Conflict('original workflow Goal head missing')
            if 'workflow' in head:
                if head['workflow']['approval_sha256']!=loaded['approval_hash']:
                    raise Conflict('original workflow approval changed; no counter reset')
                now,_=self.controller._sample()
                check_window(head['workflow'],frozen['workflow'],now)
            else:
                guard=self._active
                if (guard is None or guard.attempt is not attempt or guard.db is not active[0] or
                        json.loads(guard.raw)['request']['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF' or
                        json.loads(guard.raw)['request']['expected_state_version']!=version):
                    raise Conflict('registered workflow counters missing; no window bypass')
        if attempt['source'] is not None:
            with self.sources._lock:self.sources._physical(self.sources._issued(attempt['source']))

    def prepare_native_launch(self,lease):
        """Original approval-bound launch input, NOT postexecution qualification.

        This performs no spawn or G. Runtime deployment must obtain its actual
        user approval before invoking the launch path; tests never send G.
        Historical V1 packet approvals are not upgraded into workflow starts.
        """
        attempt=self._issued(lease)
        with self.pool._lock,self._gate(attempt,'REGISTER_NO_HANDOFF'):
            if self._current(attempt)['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF':
                raise Conflict('original no-handoff phase required for native launch issue')
            frozen=json.loads(attempt['native_model_grant'].raw)
            if frozen.get('workflow',{}).get('accounting_version')!='A_REGISTRATION_CEILINGS_V1':
                raise PermissionError('original accounted A workflow launch required')
            if id(lease) in self._native_launches:
                raise Conflict('original native launch already issued; no replacement')
            source=attempt['source']
            with self.sources._lock:
                row=self.sources._issued(source);self.sources._physical(row)
                cache=self.sources._account_caches.get(id(source))
                if cache is None:raise PermissionError('original account-cache input qualification missing')
                stamp=cache.check_staged()
                if id(source) not in self.sources._gate_bindings:
                    raise Conflict('original frozen native gate required')
                self._final_effect_gate(self._active)
                launch=NativeModelLaunch('native_launch_'+uuid.uuid4().hex,canonical({
                    'lease_id':lease.id,'source_id':source.id,'grant_sha256':digest(frozen),
                    'approval_sha256':frozen['approval_hash'],'cache_stamp':list(stamp)}))
                self._native_launches[id(lease)]=(launch,launch.raw,attempt,source,cache,stamp)
                return launch

    def _check_launch(self,attempt,launch):
        row=self._native_launches.get(id(attempt['lease']))
        if (type(launch) is not NativeModelLaunch or row is None or row[0] is not launch or
                launch.raw!=row[1] or row[2] is not attempt or row[3] is not attempt['source']):
            raise PermissionError('original same-lease native launch qualification required')
        if self.sources._account_caches.get(id(attempt['source'])) is not row[4] or row[4].check_staged()!=row[5]:
            raise Conflict('original native launch cache input changed')
        if attempt.get('source_stop_latched') or attempt.get('physical_safety_freeze') or self._safety_freeze:
            raise Conflict('original native launch stopped; no new effects')
        return row

    def start(self, lease, *, launch=None):
        attempt=self._issued(lease)
        self._unit_check(attempt)
        with self.pool._lock:
            self._check_launch(attempt,launch)
            if self._current(attempt)['fixture_runtime']['phase'] in ('STOP_REQUESTED','FIXTURE_SCOPE_STOPPED'):
                raise Conflict('original native STOP prohibits start')
            if self._launch_active is not None or self._start_materials is not None:
                raise Conflict('nested native launch refused')
            if self._control_service is not None:self._control_service._dispatch_entry(lease)
            with self._material_context(attempt) as materials:
                self._start_materials=(attempt,threading.get_ident(),materials)
                self._launch_active=(attempt,launch,threading.get_ident())
                try:
                    if not attempt['spawn_entered']:
                        value=self._write_phase(attempt,'HANDOFF_UNKNOWN')
                        self.pool._fixture_runtime_change(self,lease,'FIXTURE_HANDOFF_UNKNOWN',value)
                        with self._gate(attempt,'HANDOFF_UNKNOWN'):
                            attempt['producer_identity']=self.sources._runtime_spawn(self,lease)
                    if attempt['producer_identity'] is None:
                        raise Conflict('original native spawn UNKNOWN; no relaunch')
                    self._register_release(attempt)
                    if not attempt['release_entered']:
                        with self._gate(attempt,'RELEASE_INTENT'):
                            self.sources._runtime_release(self,lease)
                finally:
                    self._launch_active=None;self._start_materials=None
        # A G write is never an ACK, account qualification or model receipt.
        return {'lease_id':lease.id,'phase':self._current(attempt)['fixture_runtime']['phase'],
            'release_attempted':attempt['release_entered'],'source_authenticated':False,
            'account_qualified':False,'usage_qualified':False,'condition_evidence_enabled':False}

    def _native_usage_publication(self, attempt):
        self._issued(attempt['lease'])
        return self.sources._runtime_usage_publication(self,attempt['lease'])

    def _native_result_publication(self,attempt):
        self._issued(attempt['lease'])
        return self.sources._runtime_result_publication(self,attempt['lease'])

    def _preflight_native_result_archive(self,lease,data):
        """Read-only size admission against original current Budget frame."""
        from .hybrid_budget_ledger import SECTIONS as BUDGET
        from .hybrid_native_model_result import from_result,archive_preflight
        attempt=self._issued(lease);origin=attempt['origin'];binding=origin['native_model']
        # A terminal hash has fixed length; actual STOP proof does not exist yet.
        usage={'profile':'ORIGINAL_NATIVE_CLI_USAGE_V1','source_id':attempt['source'].id,
            **{k:origin[k] for k in ('lease_id','task_id','attempt_id','nonce')},
            'grant_id':binding['grant_id'],'grant_sha256':digest(binding),'producer':attempt['producer_identity'],
            **{k:binding[k] for k in ('workspace_id','packet_sha256','output_schema_sha256','candidate_sha256')},
            **{k:data[k] for k in ('stream_sha256','output_sha256','usage','ready_sha256')},
            'stream_bytes':data['bytes'],'started_ack_sha256':digest(json.loads(attempt['started_ack'].raw)),
            'terminal_proof_sha256':'sha256:'+'f'*64,'producer_exit_code':0}
        value=from_result(data,binding['role'],usage)
        request={k:attempt['intent']['request'][k] for k in ('project_id','data_mode','store_epoch','goal_ref')}
        request['action']='FIXTURE_RUNTIME_STARTED_AS_OBSERVED'
        request['reservation_id']=attempt['ready']['source_context']['budget_reservation']['reservation_id']
        with self.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
            heads=self.budget._heads(db,request,read,self.budget._metadata(db))
            reservation=heads[1]
            if reservation is None or reservation.get('fixture_runtime',{}).get('origin')!=origin:
                raise Conflict('original native archive preflight reservation differs')
            entry=read.object(BUDGET[0],reservation['last_entry_key'])
            if entry is None or digest(entry)!=reservation['last_entry_hash']:
                raise Conflict('original native archive preflight fact differs')
            archive_preflight(entry,value,usage,heads)

    def _native_terminal_archive_gate(self,attempt,value):
        """Exact final frame size may only demote to UNKNOWN, never deny STOP."""
        if value['request']['fixture_runtime'].get('native_model_result') is None:return
        try:check_bytes(value,256*1024)
        except Exception:
            self.sources._packet_failures.add(id(attempt['source']))
            runtime=value['request']['fixture_runtime']
            runtime.pop('native_model_result',None);runtime.pop('native_model_usage',None)
            value.update(request_hash=digest(value['request']),decision='UNKNOWN',reason='FIXTURE_EXPOSURE_RETAINED')

    def check_guard(self,db,guard):
        self._issued(guard.attempt['lease'])
        value=super().check_guard(db,guard)
        recorded=json.loads(guard.raw)['request']['fixture_runtime']
        expected=(self._native_usage_publication(guard.attempt)
            if recorded['phase']=='FIXTURE_SCOPE_STOPPED' else None)
        if recorded.get('native_model_usage')!=expected:
            raise PermissionError('original issued native usage publication required')
        result=(self._native_result_publication(guard.attempt)
            if recorded['phase']=='FIXTURE_SCOPE_STOPPED' else None)
        if recorded.get('native_model_result')!=result:
            raise PermissionError('original issued native result publication required')
        return value

    def _final_deadlines(self,guard,now,mono):
        super()._final_deadlines(guard,now,mono)
        frozen=json.loads(guard.attempt['native_model_grant'].raw)
        if 'workflow' in frozen:
            from .hybrid_a_workflow_accounting import check_window
            from .hybrid_budget_ledger import SECTIONS as BUDGET
            head=next(iter(guard.expected_heads[BUDGET[1]].values()))
            check_window(head['workflow'],frozen['workflow'],now)

    def prepare_native_gate(self, lease):
        """Prepare original private no-auth materials; not execution consent."""
        attempt = self._issued(lease)
        with self.pool._lock:
            def final():self._fresh(context[0],context[1],attempt)
            with self.controller.token_transaction(attempt['token'],read_bytes=PREPARATION_READ_BYTES,
                    _commit_context=self._held,_before_commit=final) as context:
                db,read,_ = context
                self._fresh(db,read,attempt)
                current = self._current(attempt)
                if current['fixture_runtime']['phase'] != 'REGISTER_NO_HANDOFF':
                    raise Conflict('original no-handoff registration required for gate materials')
                return self.sources._prepare_model_gate(self,lease)

    def prepare_no_release_producer(self,lease):
        """Run the original Python sandbox gate only, NEVER G/model/auth.

        This proves actual producer ownership under the original Pool/Budget
        and STOP; it is not model execution consent or account qualification.
        """
        attempt=self._issued(lease)
        with self.pool._lock:
            if self._current(attempt)['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF':
                raise Conflict('original first no-release producer preparation required')
            self.prepare_native_gate(lease)
            value=self._write_phase(attempt,'HANDOFF_UNKNOWN')
            self.pool._fixture_runtime_change(self,lease,'FIXTURE_HANDOFF_UNKNOWN',value)
            with self._gate(attempt,'HANDOFF_UNKNOWN'):
                attempt['producer_identity']=self.sources._runtime_spawn(self,lease)
            self._write_phase(attempt,'PROCESS_REGISTERED')
            return {'lease_id':lease.id,'phase':'PROCESS_REGISTERED',
                'sandbox_ready':True,'model_released':False,'account_qualified':False,
                'usage_qualified':False}

    def prepare_current_account_cache(self,lease):
        """Original approved session's opaque cache copy; does not grant G."""
        attempt=self._issued(lease)
        with self.pool._lock:
            if self._current(attempt)['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF':
                raise Conflict('account-cache transfer only before original handoff')
            self.prepare_native_gate(lease)
            with self._gate(attempt,'REGISTER_NO_HANDOFF'):
                return self.sources._prepare_current_account_cache(self,lease)

    def _check_account_cache_gate(self,attempt):
        self._issued(attempt['lease'])
        guard=self._active
        if guard is None or guard.attempt is not attempt or not self.pool._lock._is_owned():
            raise PermissionError('original active Controller required before secret read/copy')
        if self._current(attempt)['fixture_runtime']['phase']!='REGISTER_NO_HANDOFF':
            raise Conflict('current original no-handoff account preparation required')
        guard.check()
        self._final_effect_gate(guard)

    def _check_spawn_gate(self, attempt):
        self._issued(attempt['lease'])
        # Only original no-G Python gate. Source release still always denies.
        return super()._check_spawn_gate(attempt)

    def _check_release_gate(self, attempt):
        self._issued(attempt['lease'])
        active=self._launch_active
        if active is None or active[0] is not attempt or active[2]!=threading.get_ident():
            raise PermissionError('original model qualification missing; no G at effect fence')
        self._check_launch(attempt,active[1])
        self.sources._check_launch_ready(self,attempt['lease'])
        # Original Controller/STOP/deadline is still the LAST IO/sample fence.
        super()._check_release_gate(attempt)
        # Pure original witness after the last IO/sample, immediately before
        # the Source latches its uncertain write. NOT proof that G was sent.
        self._native_releases[id(attempt['lease'])]=(attempt,active[1],active[1].raw,
            attempt['source'],canonical(attempt['producer_identity']),
            self.sources._model_ready[id(attempt['source'])][1])

    def poll_native(self,lease):
        """Finite original observation; no model call, caller receipt or refund."""
        attempt=self._issued(lease)
        state=self.sources.poll_packet_data(attempt['source'])
        source=self.sources._issued(attempt['source'])
        if source['producer'] is not None and source['producer'].poll() is None and state['offset']:
            self.sources.observe_native_started(self,lease)
        ack=self.sources._runtime_started(self,lease)
        if ack is not None and self._current(attempt)['fixture_runtime']['phase']=='RELEASE_INTENT':
            with self.pool._lock:
                if self._current(attempt)['fixture_runtime']['phase']=='RELEASE_INTENT':
                    attempt['started_ack']=ack
                    self._write_phase(attempt,'STARTED_AS_OBSERVED',cleanup=True)
        return {**state,'lease_id':lease.id,'started_observed':ack is not None}

    def collect_native_result(self,lease):
        """Original completed result capability, or None for a finite pending step."""
        return self.sources.collect_native_result(self,lease)

    def _terminal_scope(self):return 'FIXED_NATIVE_SINGLE_TGID'

    def stop_to_terminal(self,lease):
        value=super().stop_to_terminal(lease)
        return {**value,'fixed_cpu_scope_only':False,'scope':self._terminal_scope()}

    def _retained_source(self, attempt):
        self.sources._actual()
        row = self.sources._attempts.get(id(attempt['claim']))
        if row is not None and (row['claim'] is not attempt['claim'] or row['membership'] is not self.membership or
                row['scenario'] != 'runtime.native_model' or
                row['runtime'] is not None and row['runtime'] is not attempt or
                row['runtime'] is None and (row.get('model_allocation_entered') or row['launch_entered'])):
            raise PermissionError('original same-claim retained generating source required')
        return row

    def _stop_original_participant(self, lease):
        attempt = self._issued(lease)
        if attempt['source'] is None:
            with self.pool._lock, self._lock, self.sources._lock:
                retained = self._retained_source(attempt)
                if retained is not None:self.sources._cleanup_attempt(retained)
        return super()._stop_original_participant(lease)

    def _check_terminal(self, attempt):
        retained = self._retained_source(attempt)
        if retained is not None and (retained['status'] != 'CLOSED' or
                self.sources._extra_fork_descriptors(retained) or
                any(fd is not None for fd in retained['fds'].values()) or
                retained['producer'] is not None and (retained['producer'].poll() is None or
                    retained['producer'].stdin is not None and not retained['producer'].stdin.closed)):
            raise Conflict('original generating partial source not fully closed; retain UNKNOWN')
        return super()._check_terminal(attempt)
