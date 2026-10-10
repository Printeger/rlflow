"""Original generating grant/registration; launch remains unqualified/denied.

This closes local approval/material/ledger ownership without reading credentials
or turning declaration-only account/profile fields into execution qualification.
"""
from dataclasses import dataclass
import json
import hashlib
import uuid

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


class NativeModelOwner(FixtureRuntimeOwner):
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

    def start(self, lease):
        self._issued(lease)
        raise PermissionError('native account/ELF/sandbox launch qualification not implemented; no model handoff')

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

    def _check_spawn_gate(self, attempt):
        self._issued(attempt['lease'])
        raise PermissionError('unqualified native generating spawn denied')

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
