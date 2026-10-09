"""Protected finite CPU protocol runtime, under implementation (Checkpoint 44).

NOT a native WorkingPlan/model/candidate-write executor. Public JSON and
historical facts never reconstruct the original task/attempt/lease capability.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

from .hybrid_budget import account_key, zero
from .hybrid_budget_ledger import (SECTIONS as BUDGET, EVENT, entry_key, scope,
    derived_heads, validate_record, event_inputs, project_key)
from .hybrid_controller import fact_key as controller_key
from .hybrid_fixture_runtime_ledger import ACTIONS, PHASES, dependency_lookup
from .hybrid_fixture_materials import _read_bounded
from .hybrid_fixture_materials import _deadline
from .hybrid_goals import digest
from .hybrid_host_pool import HostPoolOwner
from . import hybrid_host_pool as pool_module
from .hybrid_preparation import source_binding
from .hybrid_reads import ReadBudget
from .hybrid_usage_source import FixtureUsageSourceOwner
from .hybrid_working_plan import SECTIONS as PLANS, intent_key, result_key, stable_context
from .hybrid_working_plan_service import WorkingPlanService
from .jobs import identity
from .store import Conflict, canonical, PREPARATION_READ_BYTES

_owners = {}
_registry = threading.RLock()


def _fork_prepare():
    _registry.acquire()
    for owner in _owners.values(): owner._lock.acquire()


def _fork_parent():
    for owner in reversed(tuple(_owners.values())): owner._lock.release()
    _registry.release()


def _fork_child():
    global _registry
    for owner in _owners.values():
        owner._live = False; owner._active = None; owner._lock = threading.RLock()
    _owners.clear(); _registry = threading.RLock()


# ONE Pool coordinator: lexicographic fixture_runtime precedes fixture_usage,
# matching normal Pool -> Runtime -> Source locking. No separate os callback.
with pool_module._registry_lock:
    if 'fixture_runtime' in pool_module._fork_extensions:
        raise Conflict('original fixture runtime fork coordinator cannot be rebound')
    pool_module._fork_extensions['fixture_runtime'] = (_fork_prepare, _fork_parent, _fork_child)


@dataclass(frozen=True, eq=False)
class FixtureExecutionLease:
    id: str
    raw: bytes


class _FixtureRuntimeGuard:
    def __init__(self, owner, db, read, attempt, value, *, cleanup=False):
        self.owner, self.db, self.read, self.attempt = owner, db, read, attempt
        self.budget = read  # Store's actual Budget writer bounded-read interface.
        self.raw = canonical(value); self.cleanup = cleanup
        self.thread = threading.get_ident(); self.dependencies = {}
        self.expected_heads = derived_heads(value)

    def check(self): self.owner.check_guard(self.db, self)

    def lookup(self, section, key):
        if not key:
            return {} if self.db.execute('SELECT 1 FROM projection WHERE section=? LIMIT 1', (section,)).fetchone() else None
        return dependency_lookup(self.owner.store, self.db, self.read, self.dependencies)(section, key)


class FixtureRuntimeOwner:
    """Protected startup profile: exact fixed local CPU protocol participant."""
    def __init__(self, pool, membership, plans):
        if type(pool) is not HostPoolOwner or type(plans) is not WorkingPlanService:
            raise TypeError('fixed original Pool/WorkingPlan owners required')
        with pool._lock, _registry:
            registered = pool._issued_member(membership)
            if (registered['payload']['project_id'], registered['payload']['store_epoch'],
                    registered['payload']['store_root']) != (plans.workspace.project_id,
                    plans.workspace.store_epoch, str(plans.store.root)):
                raise Conflict('fixture runtime must use original same-application project membership')
            if plans.workspace.data_mode != 'fixture' or plans.controller.owner['process'] != pool.process:
                raise Conflict('fixed original fixture runtime process and scope required')
            if len(_owners) >= 16 or getattr(plans.workspace.budget, '_fixture_runtime', None) is not None:
                raise Conflict('finite fixed fixture runtime owner cannot be rebound')
            pool._physical(); self.pool, self.membership, self.plans = pool, membership, plans
            self.workspace = plans.workspace; self.budget = self.workspace.budget
            self.store, self.controller = plans.store, plans.controller
            self.process = dict(pool.process); self._live = True; self._lock = threading.RLock()
            self._attempts = {}; self._leases = {}; self._active = None
            self._control_service = None
            self._safety_freeze = False
            self.program = Path(__file__).with_name('hybrid_runtime_fixture.py')
            # Exact protected program, not any caller command or plan rewriting.
            raw = _read_bounded(self.program, 16384)
            self.program_raw = raw; self.program_hash = 'sha256:' + hashlib.sha256(raw).hexdigest()
            self.sources = FixtureUsageSourceOwner(pool)
            self.budget._fixture_runtime = self; _owners[id(self)] = self

    def _actual(self):
        if (not self._live or os.getpid() != self.process['pid'] or identity(os.getpid()) != self.process or
                self.budget._fixture_runtime is not self):
            raise PermissionError('actual original protected fixture Runtime owner required')

    def _issued(self, lease):
        self._actual()
        if type(lease) is not FixtureExecutionLease or self._leases.get(id(lease), {}).get('lease') is not lease:
            raise PermissionError('actual original fixture Task/Attempt/Lease required')
        return self._leases[id(lease)]

    def _plan_original(self, bundle, token, observation):
        entry = self.plans.builder._slot(bundle); seed = entry['seed']
        if (seed.token is not token or seed.observation is not observation or
                self.plans._published.get(bundle.id) is not bundle):
            raise PermissionError('original published WorkingPlan/token/observation required')
        first = self.plans._intent_attempts.get(bundle.id); second = self.plans._ready_attempts.get(bundle.id)
        if first is None or second is None or first['bundle'] is not bundle or second['bundle'] is not bundle:
            raise PermissionError('original WorkingPlan INTENT and READY attempts required')
        return json.loads(first['raw']), json.loads(second['raw'])

    def register(self, bundle, token, observation, claim, *, request_key, scenario='complete'):
        """REGISTER/CANCEL compete on the ONE original ReservationHEAD CAS."""
        from .hybrid_protocol import ID, validate_schema
        from .hybrid_runtime_fixture import SCENARIOS
        self._actual(); self.controller._refuse_nested_writer()
        if self._safety_freeze: raise Conflict('fixture runtime permanently frozen for physical cleanup')
        self.controller._issued(token); original_claim = self.pool._issued_claim(claim)
        validate_schema(ID, request_key)
        if type(scenario) is not str or scenario not in SCENARIOS: raise Conflict('fixed CPU protocol scenario required')
        with self.pool._lock, self._lock:
            previous = self._attempts.get(request_key)
            if previous is not None:
                if any(previous[name] is not value for name, value in
                       (('bundle', bundle), ('token', token), ('observation', observation), ('claim', claim))) or previous['scenario'] != scenario:
                    raise Conflict('original fixture runtime request key reused')
                attempt = previous
            else:
                if len(self._attempts) >= 32: raise Conflict('finite original fixture runtime attempts exceeded')
                if original_claim['payload']['member_id'] != self.membership.id:
                    raise PermissionError('fixture runtime original Pool claim membership differs')
                intent, ready = self._plan_original(bundle, token, observation)
                origin = {'task_id': 'fixture_task_' + uuid.uuid4().hex,
                    'attempt_id': 'fixture_attempt_' + uuid.uuid4().hex, 'lease_id': 'fixture_lease_' + uuid.uuid4().hex,
                    'kind': 'PROTOCOL_CONFORMANCE', 'authorization': 'LOCAL_PROTOCOL_ONLY',
                    'program_sha256': self.program_hash, 'scenario': scenario,
                    'working_plan_intent': {'key': intent_key(intent['request']), 'hash': digest(intent)},
                    'working_plan_ready': {'key': result_key(ready['request']), 'hash': digest(ready)},
                    'pool_claim': {'key': original_claim['key'], 'hash': digest(original_claim)},
                    'pool_id': self.pool.binding['pool_id'], 'member_id': self.membership.id,
                    'owner': self.process, 'nonce': uuid.uuid4().hex,
                    'model_enabled': False, 'candidate_write_enabled': False, 'delegation_enabled': False}
                lease = FixtureExecutionLease(origin['lease_id'], canonical(origin))
                attempt = {'lease': lease, 'origin': origin, 'bundle': bundle, 'token': token,
                    'observation': observation, 'claim': claim, 'scenario': scenario,
                    'intent': intent, 'ready': ready, 'claim_value': original_claim, 'entries': {}, 'source': None,
                    'spawn_entered': False, 'release_entered': False, 'started_ack': None,
                    'producer_identity': None, 'terminal': None, 'spawn_monotonic': None}
                self._attempts[request_key] = attempt; self._leases[id(lease)] = attempt
            # Strong original attempt retained BEFORE all cross-database writes.
        # Runtime owner lock must NOT precede Store/Controller/Workspace locks.
        with self.pool._lock:
            self._write_phase(attempt, 'REGISTER_NO_HANDOFF')
            self.pool._fixture_runtime_change(self, attempt['lease'], 'FIXTURE_LINKED', attempt['entries']['REGISTER_NO_HANDOFF'])
            if attempt['source'] is None:
                attempt['source'] = self.sources._runtime_allocate(self, attempt['lease'])
            return attempt['lease']

    @contextmanager
    def _held(self, db=None, *, cleanup=False):
        with (self.workspace._lock, self.workspace.working._lock, self.plans._lock,
              self.plans.installation._lock, self.plans.installation.builder._lock, self._lock):
            if db is None:
                active = self.controller._token_active
                db = None if active is None else active[0]
            if self._control_service is None:
                yield
            else:
                with self._control_service._borrow(db, cleanup=cleanup): yield

    def _fresh(self, db, read, attempt):
        """Independent post-registration guard; NEVER skip old PlanGuard."""
        self._actual(); self.pool.check(attempt['claim'])
        if self._control_service is not None: self._control_service._check_authority(cleanup=False, attempt=attempt)
        if self._safety_freeze: raise Conflict('fixture runtime permanently frozen for physical cleanup')
        self.controller.check_token_in_transaction(db, attempt['token'], read)
        slot, record = self.workspace._issued(attempt['observation'])
        if slot['closed'] is not None or self.workspace._unresolved_renewal(slot):
            raise Conflict('fixture runtime current original Workspace unresolved/closed')
        self.workspace.working.check(attempt['observation'])
        version = self.workspace._metadata(db); captured = attempt['ready']['source_context']
        wh = captured['workspace_head']; fact = self.workspace._point(db, wh['fact_key'], read)
        guard = self._active
        # Cache only the historical closure inside THIS held writer/snapshot.
        # The original fact/event is reread above and every actual current
        # HEAD, authority, FD witness and deadline is still checked below.
        if guard is None or getattr(guard, '_workspace_proved', None) != canonical(fact):
            self.workspace._dependencies(db, fact, read)
            if guard is not None: guard._workspace_proved = canonical(fact)
        current = self.workspace._current(db, fact['request'], read, version)
        if current != wh or record != captured['observation']:
            raise Conflict('fixture runtime current original Workspace lineage changed')
        sources = source_binding(self.budget._load(db, fact['request']['goal_ref'], read))
        if any(sources[name] != value for name, value in captured['sources'].items()
               if name not in ('source_version', 'evaluated_at')):
            raise Conflict('fixture runtime current original Goal/approval/Registry changed')
        if guard is not None:
            guard.plan_witness.check()
            self.workspace.preparation.check_material_witness(guard.preparation,
                read.object('hybrid_preparation_intents', captured['preparation']['intent_key']),
                read.object('hybrid_preparation_results', captured['preparation']['result_key']))
            if self.plans.installation._bootstrap_point(db, guard.bootstrap, read) != captured['bootstrap']:
                raise Conflict('fixture runtime original bootstrap changed')

    def _write_phase(self, attempt, phase, *, cleanup=False):
        if phase not in PHASES: raise Conflict('fixed fixture runtime phase required')
        original = attempt['entries'].get(phase)
        if original is not None:
            if self._control_service is not None: self._control_service._check_fact(attempt, original)
            confirmed = self._confirm_entry(attempt, original)
            if confirmed is not None: return confirmed
        return self._new_entry(attempt, phase, cleanup=cleanup)

    def _confirm_entry(self, attempt, original):
        self._actual()
        with self.store.read_connection() as db:
            db.execute('BEGIN'); read = ReadBudget(db, PREPARATION_READ_BYTES)
            key = entry_key(original['request'])
            if read.object(BUDGET[0], key) is None: return None
            value = self.budget._point(db, key, read)
            if value != original: raise Conflict('original fixture runtime phase COMMIT outcome uncertain')
            self.budget._dependencies(db, value, read)
            return value

    def _new_entry(self, attempt, phase, *, cleanup):
        return self._new_entries(attempt, (phase,), cleanup=cleanup)

    def _new_entries(self, attempt, phases, *, cleanup):
        """One held transaction; each phase retains its own original CAS/event."""
        self._actual()
        if (type(phases) is not tuple or
                not (len(phases) == 1 and phases[0] in PHASES or
                     phases == ('PROCESS_REGISTERED', 'RELEASE_INTENT') and not cleanup) or
                cleanup and phases[0] not in ('STARTED_AS_OBSERVED', 'STOP_REQUESTED', 'FIXTURE_SCOPE_STOPPED')):
            raise PermissionError('only original single phase or fixed identity/release batch allowed')
        if self._active is not None: raise Conflict('nested fixture runtime writer refused')
        captured = attempt['ready']['source_context']
        with ExitStack() as witnesses:
            if not cleanup:
                preparation = self.workspace.preparation.issue_material_witness(captured['preparation']['intent_key'])
                plan_witness = witnesses.enter_context(self.plans.builder._witness(attempt['bundle']))
                bootstrap = witnesses.enter_context(self.plans.installation._bootstrap_witness(self.plans.material))
            else:
                preparation = plan_witness = bootstrap = None

            def final():
                self.check_guard(self._active.db, self._active)
                if len(phases) == 2:
                    first, second = (attempt['entries'][phase] for phase in phases)
                    if (second['request']['expected_state_version'] != first['accepted_state_version'] or
                            second['request']['fixture_runtime']['previous'] !=
                            {'key':entry_key(first['request']), 'hash':digest(first)}):
                        raise Conflict('fixture original identity/release batch prefix differs')
                    for value in (first, second):
                        if self.budget._point(self._active.db, entry_key(value['request']), self._active.read) != value:
                            raise Conflict('fixture original identity/release batch event differs')
            def deadlines(now, mono):
                from .hybrid_authority import timestamp
                value = json.loads(self._active.raw)
                if now < timestamp(value['recorded_at']):
                    raise Conflict('fixture runtime original clock regressed')
                if not cleanup:
                    self._final_deadlines(self._active, now, mono)
                elif self._control_service is not None:
                    self._control_service._check_authority(cleanup=True)

            @contextmanager
            def transaction():
                if not cleanup:
                    with self.controller.token_transaction(attempt['token'], read_bytes=PREPARATION_READ_BYTES,
                            _commit_context=self._held, _before_commit=final, _after_final_sample=deadlines) as context:
                        yield context
                else:
                    # Safety-only original cleanup cannot authorize new work;
                    # it remains possible after Controller/consent TTL expires.
                    with self.store.lock(), self.store.connect() as db:
                        db.execute('BEGIN IMMEDIATE'); read = ReadBudget(db, PREPARATION_READ_BYTES)
                        with self._held(db, cleanup=True):
                            control = self.controller._original(db, captured['controller']['fact_key'], read)
                            yield db, read, control
                            final(); now, mono = self.controller._sample(); deadlines(now, mono); db.commit()
                            if self._control_service is not None:
                                self._control_service._committed(attempt['entries'][phases[-1]])
            try:
                with transaction() as (db, read, control):
                    for phase in phases:
                        self._append_phase(attempt, phase, cleanup, db, read, control,
                                           preparation, plan_witness, bootstrap)
                return attempt['entries'][phases[-1]]
            finally:
                self._active = None

    def _append_phase(self, attempt, phase, cleanup, db, read, control,
                      preparation, plan_witness, bootstrap):
        captured = attempt['ready']['source_context']
        version = self.budget._metadata(db)
        request = {name: attempt['intent']['request'][name] for name in
                   ('project_id', 'data_mode', 'store_epoch', 'goal_ref')}
        request.update(action=ACTIONS[PHASES.index(phase)],
            idempotency_key=attempt['lease'].id + '.' + str(PHASES.index(phase)),
            expected_state_version=version,
            reservation_id=captured['budget_reservation']['reservation_id'])
        goal, reservation, project = self.budget._heads(db, request, read, version)
        if reservation is None: raise Conflict('fixture runtime original Budget reservation missing')
        command = (None if self._control_service is None else
                   self._control_service._accepting_command(attempt, phase, version))
        if command is not None: request['idempotency_key'] = command['command_id']
        original = attempt['entries'].get(phase)
        if original is not None and command is not None:
            name = 'start_command' if phase == 'HANDOFF_UNKNOWN' else 'stop_command'
            if original['request']['fixture_runtime'].get(name) != command:
                raise Conflict('fixture command idempotency differs from retained original acceptance')
        if original is None:
            prior = reservation.get('fixture_runtime')
            registration = (None if phase == 'REGISTER_NO_HANDOFF' else
                prior['registration'] if prior and prior['registration'] is not None else
                {'key': reservation['last_entry_key'], 'hash': reservation['last_entry_hash']})
            runtime = {'phase': phase, 'origin': attempt['origin'], 'registration': registration,
                'previous': None if phase == 'REGISTER_NO_HANDOFF' else
                    {'key': reservation['last_entry_key'], 'hash': reservation['last_entry_hash']},
                'producer': attempt['producer_identity'],
                'started_ack_sha256': None if attempt['started_ack'] is None else digest(json.loads(attempt['started_ack'].raw)),
                'terminal_proof_sha256': None if attempt['terminal'] is None else digest(attempt['terminal']),
                'wall_seconds': 0 if attempt['terminal'] is None else attempt['terminal']['wall_seconds']}
            for name in ('start_command', 'stop_command'):
                if prior is not None and name in prior: runtime[name] = prior[name]
            if command is not None:
                runtime['start_command' if phase == 'HANDOFF_UNKNOWN' else 'stop_command'] = command
            request['fixture_runtime'] = runtime
            now, mono = self.controller._sample()
            if phase == 'REGISTER_NO_HANDOFF': decision, reason = 'HELD', 'FIXTURE_REGISTERED_NO_HANDOFF'
            elif phase == 'FIXTURE_SCOPE_STOPPED': decision, reason = 'SETTLED', 'FIXTURE_SCOPE_TERMINATED'
            else: decision, reason = 'UNKNOWN', 'FIXTURE_EXPOSURE_RETAINED'
            original = {'schema_version': '1.0', 'request': request, 'request_hash': digest(request),
                'policy_source': goal['policy_source'], 'policy': goal['policy'],
                'preparation': reservation['preparation'], 'controller': {
                    'fact_key': controller_key(control['request']), 'fact_hash': digest(control),
                    'controller_epoch': control['controller_epoch'], 'head_revision': control['head_revision']},
                'recorded_at': now.isoformat().replace('+00:00', 'Z'), 'controller_checked_monotonic_ns': mono,
                'prior_goal': goal, 'prior_reservation': reservation, 'prior_project': project,
                'decision': decision, 'reason': reason, 'accepted_state_version': version + 1,
                'execution_enabled': False}
            validate_record(BUDGET[0], entry_key(request), original)
            attempt['entries'][phase] = original  # Retain exact original CAS before COMMIT.
        if original['request']['expected_state_version'] != version:
            raise Conflict('fixture runtime uncertain original phase CAS changed')
        guard = _FixtureRuntimeGuard(self, db, read, attempt, original, cleanup=cleanup)
        guard.preparation, guard.plan_witness, guard.bootstrap = preparation, plan_witness, bootstrap
        guard.dependencies = self.budget._dependencies(db, original, read)
        self._active = guard; guard.check()
        put = [[BUDGET[0], entry_key(original['request']), original]]
        put.extend([s, k, v] for s, values in derived_heads(original).items() for k, v in values.items())
        payload = {'format': 2, 'put': put, 'delete': [], 'details': None}
        self.store._commit(db, EVENT, entry_key(original['request']), payload, version,
            account_key(scope(original['request'])), 'hybrid-core', event_inputs(original), _authorization=guard)
        guard.check()

    def _register_release(self, attempt):
        """Atomic actual identity + release intent, NEVER G before COMMIT ACK."""
        process = attempt['entries'].get('PROCESS_REGISTERED')
        release = attempt['entries'].get('RELEASE_INTENT')
        if process is not None or release is not None:
            # COMMIT unknown-result ACK is ONE original read snapshot. Never
            # acknowledge PROCESS alone and infer durable RELEASE permission.
            with self.store.read_connection() as db:
                db.execute('BEGIN'); read = ReadBudget(db, PREPARATION_READ_BYTES)
                facts = []
                for value in (process, release):
                    fact = None if value is None else read.object(BUDGET[0], entry_key(value['request']))
                    if fact is not None:
                        if self.budget._point(db, entry_key(value['request']), read) != value:
                            raise Conflict('fixture original atomic batch outcome differs')
                        self.budget._dependencies(db, value, read)
                    facts.append(fact)
                if any(fact is not None for fact in facts):
                    if any(fact is None for fact in facts):
                        raise Conflict('fixture original atomic batch incomplete; no release')
                    current = read.object(BUDGET[2], release['request']['reservation_id'])
                    if not attempt['release_entered'] and current != derived_heads(release)[BUDGET[2]][release['request']['reservation_id']]:
                        raise Conflict('fixture original batch final reservation HEAD differs')
                    return release
        return self._new_entries(attempt, ('PROCESS_REGISTERED', 'RELEASE_INTENT'), cleanup=False)

    def check_guard(self, db, guard):
        if (type(guard) is not _FixtureRuntimeGuard or guard.owner is not self or self._active is not guard or
                guard.db is not db or guard.read.db is not db or guard.thread != threading.get_ident() or
                not db.in_transaction or self._leases.get(id(guard.attempt['lease'])) is not guard.attempt):
            raise PermissionError('actual active original fixture runtime writer required')
        self._actual(); value = json.loads(guard.raw); request = value['request']
        if guard.cleanup and request['fixture_runtime']['phase'] not in ('STARTED_AS_OBSERVED', 'STOP_REQUESTED', 'FIXTURE_SCOPE_STOPPED'):
            raise PermissionError('only original ACK observation or safety cleanup may bypass new-work authority')
        if guard.attempt['entries'].get(request['fixture_runtime']['phase']) != value:
            raise Conflict('fixture runtime original retained phase differs')
        if request['fixture_runtime']['origin'] != guard.attempt['origin']:
            raise Conflict('fixture runtime original Task/Attempt/Lease differs')
        version = self.budget._metadata(db)
        if version == request['expected_state_version']:
            # Original heads were fully validated on entry to this same held
            # writer. Re-read exact bounded bytes, not repeat their schema and
            # arithmetic expansion on every physical/source guard callback.
            keys = (account_key(scope(request)), request['reservation_id'],
                    project_key(request['project_id'], request['data_mode']))
            heads = tuple(guard.read.object(section, key) for section, key in zip(BUDGET[1:], keys))
            if heads != tuple(value[name] for name in ('prior_goal', 'prior_reservation', 'prior_project')):
                raise Conflict('fixture runtime original Budget CAS heads changed')
        elif version == value['accepted_state_version']:
            if self.budget._point(db, entry_key(request), guard.read) != value:
                raise Conflict('fixture runtime original committed entry changed')
            for section, objects in guard.expected_heads.items():
                for key, head in objects.items():
                    if guard.read.object(section, key) != head:
                        raise Conflict('fixture runtime original final derived HEAD differs')
        else: raise Conflict('fixture runtime original writer version changed')
        if not guard.cleanup: self._fresh(db, guard.read, guard.attempt)
        else:
            self.pool._physical(); self.pool._claim_slots[id(guard.attempt['claim'])].check()
        phase = request['fixture_runtime']['phase']; attempt = guard.attempt
        if phase in ('PROCESS_REGISTERED', 'RELEASE_INTENT', 'STARTED_AS_OBSERVED'):
            source = self.sources._issued(attempt['source'])
            if source['runtime'] is not attempt or source['producer_identity'] != attempt['producer_identity']:
                raise Conflict('fixture runtime original participant/source differs')
        if phase == 'STARTED_AS_OBSERVED':
            ack = self.sources._runtime_started(self, attempt['lease'])
            if ack is None or ack is not attempt['started_ack'] or not attempt['release_entered']:
                raise PermissionError('actual original gated child started observation required')
        if phase == 'FIXTURE_SCOPE_STOPPED': self._check_terminal(attempt)
        if self._control_service is not None: self._control_service._check_authority(cleanup=guard.cleanup, attempt=attempt)
        if self._control_service is not None: self._control_service._check_fact(attempt, value)

    def check_live_write(self, db, payload, inputs, guard):
        self.check_guard(db, guard); value = json.loads(guard.raw)
        expected = [[BUDGET[0], entry_key(value['request']), value]]
        expected.extend([s, k, v] for s, values in derived_heads(value).items() for k, v in values.items())
        if payload != {'format': 2, 'put': expected, 'delete': [], 'details': None} or inputs != event_inputs(value):
            raise PermissionError('fixture runtime exact joint Budget/Runtime event required')

    def _current(self, attempt):
        with self.store.read_connection() as db:
            db.execute('BEGIN'); read = ReadBudget(db, PREPARATION_READ_BYTES)
            request = {name: attempt['intent']['request'][name] for name in
                       ('project_id', 'data_mode', 'store_epoch', 'goal_ref')}
            request.update(action=ACTIONS[0], reservation_id=attempt['ready']['source_context']['budget_reservation']['reservation_id'])
            _, reservation, _ = self.budget._heads(db, request, read, self.budget._metadata(db))
            if reservation is None or reservation.get('fixture_runtime', {}).get('origin') != attempt['origin']:
                raise Conflict('fixture runtime original current reservation lineage differs')
            return reservation

    def _verify_pool_link(self, attempt, action, project_value):
        self._actual()
        phases = {'FIXTURE_LINKED': 'REGISTER_NO_HANDOFF', 'FIXTURE_HANDOFF_UNKNOWN': 'HANDOFF_UNKNOWN',
                  'FIXTURE_STOP_REQUESTED': 'STOP_REQUESTED', 'FIXTURE_STOPPED': 'FIXTURE_SCOPE_STOPPED',
                  'FIXTURE_FREE': 'FIXTURE_SCOPE_STOPPED'}
        phase = phases[action]
        if (attempt['entries'].get(phase) != project_value or
                project_value['request']['fixture_runtime']['origin'] != attempt['origin'] or
                self._confirm_entry(attempt, project_value) != project_value or
                self._current(attempt) != derived_heads(project_value)[BUDGET[2]][project_value['request']['reservation_id']]):
            raise Conflict('fixture Pool/Project original durable matching proof differs')
        if phase == 'FIXTURE_SCOPE_STOPPED': self._check_terminal(attempt)
        if action == 'FIXTURE_FREE':
            slot = self.pool._claim_slots[id(attempt['claim'])]
            if attempt.get('pool_closed') is None or not slot.closed or any(fd is not None for fd in slot.fds):
                raise Conflict('fixture Runtime original all-Pool-FDs-closed proof required')

    @contextmanager
    def _gate(self, attempt, phase):
        """Borrow current original sources under the writer for ONE side effect."""
        captured = attempt['ready']['source_context']
        preparation = self.workspace.preparation.issue_material_witness(captured['preparation']['intent_key'])
        with self.plans.builder._witness(attempt['bundle']) as witness, self.plans.installation._bootstrap_witness(self.plans.material) as bootstrap:
            def final(): self._active.check()
            def deadlines(now, mono): self._final_deadlines(self._active, now, mono)
            try:
                with self.controller.token_transaction(attempt['token'], read_bytes=PREPARATION_READ_BYTES,
                        _commit_context=self._held, _before_commit=final, _after_final_sample=deadlines) as (db, read, _):
                    value = attempt['entries'][phase]
                    guard = _FixtureRuntimeGuard(self, db, read, attempt, value)
                    guard.preparation, guard.plan_witness, guard.bootstrap = preparation, witness, bootstrap
                    guard.dependencies = self.budget._dependencies(db, value, read)
                    self._active = guard; guard.check()
                    yield
                    guard.check()
            finally: self._active = None

    def _final_deadlines(self, guard, now, mono):
        """Only fixed original fields and clock reads; NO new source/SQL IO."""
        from .hybrid_authority import timestamp
        attempt = guard.attempt; captured = attempt['ready']['source_context']
        observation = attempt['observation']; witness = guard.preparation
        working_now, working_mono = self.workspace.working._sample()
        material_now, material_mono = self.workspace.preparation._witness_sample()
        proof = json.loads(witness.raw); final_now = max(now, working_now, material_now)
        if (not timestamp(captured['observation']['checked_at']) <= final_now < timestamp(captured['observation']['expires_at']) or
                final_now >= timestamp(captured['sources']['expires_at']) or
                not observation.issued_monotonic_ns <= working_mono < observation.expires_monotonic_ns or
                not timestamp(proof['checked_at']) <= final_now < timestamp(proof['expires_at']) or
                not witness.issued_monotonic_ns <= material_mono < witness.expires_monotonic_ns):
            raise Conflict('fixture runtime sources expired at final actual boundary')
        _deadline(guard.bootstrap.inventory.deadline); _deadline(guard.plan_witness.deadline)
        self.pool._claim_clocks(attempt['claim_value'])
        if self._control_service is not None: self._control_service._check_authority(cleanup=False)

    def _final_effect_gate(self, guard):
        # Controller actual process/STOP IO is LAST, then one exact final sample.
        now, mono = self.controller._final_token_freshness(guard.db, guard.attempt['token'], guard.read)
        self._final_deadlines(guard, now, mono)

    def _actual_handoff_link(self, attempt):
        from .store import sha
        value = attempt['entries']['HANDOFF_UNKNOWN']
        key = 'fixture_handoff_unknown_' + sha([attempt['origin']['pool_claim']['key'], attempt['lease'].id])
        original = self.pool._attempts.get(key)
        if (original is None or original['payload']['project_fact_key'] != entry_key(value['request']) or
                original['payload']['project_fact_hash'] != digest(value) or
                original['payload']['runtime_lease_id'] != attempt['lease'].id):
            raise Conflict('fixture effect requires original matching Pool/Project handoff')
        with self.pool._transaction() as db:
            if self.pool._point(db, key) != original or self.pool._state(db)[1][original['slot']]['key'] != key:
                raise Conflict('fixture actual current Pool handoff differs')

    def _check_spawn_gate(self, attempt):
        guard = self._active
        if guard is None or guard.attempt is not attempt or not self.pool._lock._is_owned():
            raise PermissionError('actual original held fixture spawn gate required')
        guard.check()
        self._actual_handoff_link(attempt)
        if (json.loads(guard.raw)['request']['fixture_runtime']['phase'] != 'HANDOFF_UNKNOWN' or
                self.pool.check(attempt['claim'])['state'] != 'FIXTURE_HANDOFF_UNKNOWN' or
                attempt['spawn_entered']):
            raise Conflict('fixture spawn needs two durable matching HANDOFF_UNKNOWN facts')
        self._final_effect_gate(guard)

    def _check_release_gate(self, attempt):
        guard = self._active
        if guard is None or guard.attempt is not attempt or not self.pool._lock._is_owned():
            raise PermissionError('actual original held fixture release gate required')
        guard.check()
        self._actual_handoff_link(attempt)
        if (json.loads(guard.raw)['request']['fixture_runtime']['phase'] != 'RELEASE_INTENT' or
                self.pool.check(attempt['claim'])['state'] != 'FIXTURE_HANDOFF_UNKNOWN' or
                not attempt['spawn_entered'] or attempt['release_entered']):
            raise Conflict('fixture release needs original durable intent and no STOP')
        if time.monotonic() - attempt['spawn_monotonic'] >= attempt['entries']['REGISTER_NO_HANDOFF']['prior_reservation']['amount']['wall_seconds']:
            raise Conflict('fixture release wall budget elapsed')
        self._final_effect_gate(guard)

    def start(self, lease):
        attempt = self._issued(lease)
        if self._control_service is not None: self._control_service._dispatch_entry(lease)
        with self.pool._lock:
            current = self._current(attempt)['fixture_runtime']['phase']
            if current in ('STOP_REQUESTED', 'FIXTURE_SCOPE_STOPPED'):
                raise Conflict('fixture STOP prohibits any later spawn or release')
            if not attempt['spawn_entered']:
                value = self._write_phase(attempt, 'HANDOFF_UNKNOWN')
                self.pool._fixture_runtime_change(self, lease, 'FIXTURE_HANDOFF_UNKNOWN', value)
                with self._gate(attempt, 'HANDOFF_UNKNOWN'):
                    attempt['producer_identity'] = self.sources._runtime_spawn(self, lease)
            if attempt['producer_identity'] is None:
                raise Conflict('fixture original spawn outcome UNKNOWN; never relaunch/adopt')
            self._register_release(attempt)
            if not attempt['release_entered']:
                with self._gate(attempt, 'RELEASE_INTENT'):
                    self.sources._runtime_release(self, lease)
        # Sending G is NOT started. Only original child ACK can advance phase.
        return self.poll(lease)

    def poll(self, lease, *, seal=False):
        attempt = self._issued(lease)
        receipt = self.sources.seal(attempt['source']) if seal else self.sources.poll(attempt['source'])
        ack = self.sources._runtime_started(self, lease)
        with self.pool._lock:
            current = self._current(attempt)['fixture_runtime']['phase']
            if ack is not None and current == 'RELEASE_INTENT':
                attempt['started_ack'] = ack
                self._write_phase(attempt, 'STARTED_AS_OBSERVED', cleanup=True)
                current = 'STARTED_AS_OBSERVED'
        return {'lease_id': lease.id, 'phase': current, 'source': json.loads(receipt.raw),
                'fixed_cpu_scope_only': True, 'native_execution_enabled': False,
                'actual_cost_status': 'UNKNOWN', 'synthetic_tokens_settled': False}

    def request_stop(self, lease):
        attempt = self._issued(lease)
        with self.pool._lock:
            current = self._current(attempt)['fixture_runtime']['phase']
            if current == 'FIXTURE_SCOPE_STOPPED': return attempt['entries']['FIXTURE_SCOPE_STOPPED']
            value = self._write_phase(attempt, 'STOP_REQUESTED', cleanup=True)
            self.pool._fixture_runtime_change(self, lease, 'FIXTURE_STOP_REQUESTED', value)
            return value

    def _check_terminal(self, attempt):
        proof = attempt['terminal']
        if proof is None or proof['lease_id'] != attempt['lease'].id or proof['scope'] != 'FIXED_CPU_SINGLE_PARTICIPANT':
            raise PermissionError('original fixed fixture terminal proof required')
        if attempt['source'] is not None:
            source = self.sources._issued(attempt['source'])
            if source['runtime'] is not attempt or source['status'] != 'CLOSED' or any(fd is not None for fd in source['fds'].values()):
                raise Conflict('fixture original source descriptors not all closed')
            process = source['producer']
            if attempt['spawn_entered'] and (process is None or process.poll() is None or attempt['producer_identity'] is None):
                raise Conflict('fixture original complete participant identity/reap uncertain')
            if process is not None and process.stdin is not None and not process.stdin.closed:
                raise Conflict('fixture original release pipe still open')
        elif attempt['spawn_entered']: raise Conflict('fixture unknown original process cannot be adopted')

    def stop_to_terminal(self, lease):
        attempt = self._issued(lease)
        self.request_stop(lease)  # Both durable freezes precede any interrupt/close.
        with self.pool._lock, self._lock:
            if attempt['terminal'] is None:
                if attempt['source'] is not None:
                    source = self.sources._issued(attempt['source']); process = source['producer']
                    if process is not None and process.poll() is None:
                        if identity(process.pid) != source['producer_identity']:
                            raise Conflict('fixture STOP original live identity differs')
                        self.sources._check_pidfd(source, live=True)
                        signal.pidfd_send_signal(source['fds']['pidfd'], signal.SIGTERM)
                        try: process.wait(timeout=.2)
                        except subprocess.TimeoutExpired: pass
                    self.sources.stop_fixture(attempt['source'])  # KILL/reap bounded fallback + all FD closes.
                if attempt['spawn_entered'] and attempt['producer_identity'] is None:
                    raise Conflict('fixture STOP unknown handoff retains Pool/Budget exposure')
                wall = 0 if attempt['spawn_monotonic'] is None else math.ceil(time.monotonic() - attempt['spawn_monotonic'])
                attempt['terminal'] = {'scope': 'FIXED_CPU_SINGLE_PARTICIPANT', 'lease_id': lease.id,
                    'program_sha256': self.program_hash, 'producer': attempt['producer_identity'],
                    'all_original_source_fds_closed': True, 'original_participant_reaped': True,
                    'no_descendants_in_fixed_program': True, 'arbitrary_tree_stop': False,
                    'wall_seconds': wall, 'synthetic_tokens_settled': False}
                self._check_terminal(attempt)
        # Never hold Runtime lock before the project writer.
        with self.pool._lock:
            value = self._write_phase(attempt, 'FIXTURE_SCOPE_STOPPED', cleanup=True)
            slot = self.pool._claim_slots[id(attempt['claim'])]
            if attempt.get('pool_closed') is None:
                self.pool._fixture_runtime_change(self, lease, 'FIXTURE_STOPPED', value)
                if not slot.closed:
                    if all(fd is not None for fd in slot.fds): slot.check()
                    slot.close()
                attempt['pool_closed'] = {'lease_id': lease.id, 'claim_sha256': digest(attempt['claim_value']),
                    'terminal_sha256': digest(attempt['terminal']), 'all_original_pool_fds_closed': True}
            self.pool._fixture_runtime_change(self, lease, 'FIXTURE_FREE', value)
        return {'lease_id': lease.id, 'phase': 'FIXTURE_SCOPE_STOPPED', 'fixed_cpu_scope_only': True,
                'arbitrary_tree_stop': False, 'synthetic_tokens_settled': False, 'wall_seconds': attempt['terminal']['wall_seconds']}

    def shutdown(self):
        self._actual()
        for attempt in tuple(self._attempts.values()):
            if 'REGISTER_NO_HANDOFF' in attempt['entries'] and self._confirm_entry(attempt, attempt['entries']['REGISTER_NO_HANDOFF']) is not None:
                self.stop_to_terminal(attempt['lease'])
        with self.pool._lock, _registry, self._lock:
            self.sources.shutdown(); self._live = False; _owners.pop(id(self), None)

    def shutdown_safety(self):
        """Irreversible original-cap cleanup; UNKNOWN exposure is NOT refunded.

        No terminal/FREE fact is minted. A partial close retains this original
        owner for bounded retry; no replacement owner or PID adoption is used.
        """
        self._actual()
        with self.pool._lock:
            self._safety_freeze = True
            registered = []
            for attempt in self._attempts.values():
                value = attempt['entries'].get('REGISTER_NO_HANDOFF')
                if value is not None and self._confirm_entry(attempt, value) is not None:
                    self.request_stop(attempt['lease'])
                    registered.append(attempt)
            with _registry, self._lock:
                if self.sources._live: self.sources.shutdown()
                for attempt in registered:
                    slot = self.pool._claim_slots[id(attempt['claim'])]
                    slot.close()
                self._live = False; _owners.pop(id(self), None)
            return {'state': 'PHYSICAL_CLOSED_EXPOSURE_UNKNOWN',
                    'runtime_stopped': False, 'refund_enabled': False,
                    'new_work_enabled': False, 'pool_slots_freed': False}
