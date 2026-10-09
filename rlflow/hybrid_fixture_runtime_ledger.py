"""Closed fixed CPU runtime lineage; never a native/model execution grant.

The protected owner and Budget's actual writer must prove these facts. This
module supplies deterministic arithmetic/links, not caller attestations.
"""
from .hybrid_protocol import ID, HASH, obj, enum, validate_schema
from .hybrid_goals import digest
from .store import Conflict,canonical
from .hybrid_cpu_trial import BINDING as CPU_BINDING, KIND as CPU_KIND, AUTHORIZATION as CPU_AUTHORIZATION
from .hybrid_engineering_patch import BINDING as ENGINEERING_BINDING,KIND as ENGINEERING_KIND,AUTHORIZATION as ENGINEERING_AUTHORIZATION

PHASES = ('REGISTER_NO_HANDOFF', 'HANDOFF_UNKNOWN', 'PROCESS_REGISTERED',
          'RELEASE_INTENT', 'STARTED_AS_OBSERVED', 'STOP_REQUESTED',
          'FIXTURE_SCOPE_STOPPED')
ACTIONS = tuple('FIXTURE_RUNTIME_' + phase for phase in PHASES)
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 2**63 - 1}
PROCESS = obj({'pid': {**COUNT, 'minimum': 1}, 'pgid': {**COUNT, 'minimum': 1},
               'starttime': {'type': 'string', 'pattern': '^[0-9]{1,20}$'},
               'boot_id': {'type': 'string', 'pattern': '^[0-9a-f-]{36}$'}})
REFERENCE = obj({'key': ID, 'hash': HASH})
PROTOCOL_ORIGIN = obj({'task_id': ID, 'attempt_id': ID, 'lease_id': ID,
    'kind': {'const': 'PROTOCOL_CONFORMANCE'}, 'authorization': {'const': 'LOCAL_PROTOCOL_ONLY'},
    'program_sha256': HASH, 'scenario': enum('complete', 'missing', 'running', 'bad_ack'),
    'working_plan_intent': REFERENCE, 'working_plan_ready': REFERENCE,
    'pool_claim': REFERENCE, 'pool_id': ID, 'member_id': ID,
    'owner': PROCESS, 'nonce': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'},
    'model_enabled': {'const': False}, 'candidate_write_enabled': {'const': False},
    'delegation_enabled': {'const': False}})
CPU_ORIGIN = obj({**PROTOCOL_ORIGIN['properties'], 'kind': {'const': CPU_KIND},
    'authorization': {'const': CPU_AUTHORIZATION}, 'scenario': {'const': 'cpu_trial'},
    'cpu_trial': CPU_BINDING})
ENGINEERING_ORIGIN=obj({**PROTOCOL_ORIGIN['properties'],'kind':{'const':ENGINEERING_KIND},
    'authorization':{'const':ENGINEERING_AUTHORIZATION},'scenario':{'const':'engineering_patch'},
    'engineering_patch':ENGINEERING_BINDING})
ORIGIN={'type':'object','if':{'properties':{'kind':{'const':'PROTOCOL_CONFORMANCE'}},'required':['kind']},
    'then':PROTOCOL_ORIGIN,'else':{'if':{'properties':{'kind':{'const':CPU_KIND}},'required':['kind']},
    'then':CPU_ORIGIN,'else':ENGINEERING_ORIGIN}}
nullable = lambda schema: {'oneOf': [schema, {'type': 'null'}]}
CONTROL_BODY = obj({'action': enum('START_FIXED_CPU', 'STOP_FIXED_SCOPE'),
    'task_id': ID, 'expected_state_version': COUNT})
CONTROL_COMMAND = obj({**CONTROL_BODY['properties'], 'actor_id': ID,
    'idempotency_key': ID, 'command_id': ID, 'request_hash': HASH})
RUNTIME = obj({'phase': enum(*PHASES), 'origin': ORIGIN,
    'registration': nullable(REFERENCE), 'previous': nullable(REFERENCE),
    'producer': nullable(PROCESS), 'started_ack_sha256': nullable(HASH),
    'terminal_proof_sha256': nullable(HASH), 'wall_seconds': COUNT})
# Optional only for compatibility with already persisted44 facts. A new
# command appears only at its actual accepting phase, then remains immutable.
RUNTIME['properties'].update(start_command=CONTROL_COMMAND, stop_command=CONTROL_COMMAND)
RUNTIME['properties'].update(cpu_trial_release_attempted={'type': 'boolean'},
                             cpu_trial_result=nullable({'type': 'object'}))
RUNTIME['properties'].update(engineering_release_attempted={'type':'boolean'},
                            engineering_patch_result=nullable({'type':'object'}))


def control_command_id(request, actor_id, client_key):
    from .store import sha
    return 'fixture_command_' + sha([request['project_id'], request['data_mode'],
                                   request['store_epoch'], actor_id, client_key])


def _control_links(request, old):
    runtime = request['fixture_runtime']
    for name, action, acceptance in (('start_command', 'START_FIXED_CPU', 'HANDOFF_UNKNOWN'),
                                     ('stop_command', 'STOP_FIXED_SCOPE', 'STOP_REQUESTED')):
        command = runtime.get(name); previous = None if old is None else old.get(name)
        if previous is not None:
            if command != previous: raise Conflict('fixture original control command changed')
            continue
        if command is None: continue
        body = {key: command[key] for key in CONTROL_BODY['properties']}
        if (runtime['phase'] != acceptance or command['action'] != action or
                command['task_id'] != runtime['origin']['task_id'] or
                command['expected_state_version'] != request['expected_state_version'] or
                command['request_hash'] != digest(body) or
                command['command_id'] != control_command_id(request, command['actor_id'], command['idempotency_key']) or
                request['idempotency_key'] != command['command_id']):
            raise Conflict('fixture control acceptance original CAS or scope differs')


def phase(request):
    action = request['action']
    if action not in ACTIONS: raise Conflict('fixed fixture runtime action required')
    return PHASES[ACTIONS.index(action)]


def validate_runtime(request, prior):
    """Local one-way transition; live original provenance is a separate gate."""
    value = request['fixture_runtime']; validate_schema(RUNTIME, value)
    current = phase(request)
    old = prior.get('fixture_runtime') if prior is not None else None
    trial = value['origin']['kind'] == CPU_KIND
    if trial:
        from .hybrid_cpu_trial import validate_result
        if (type(value.get('cpu_trial_release_attempted')) is not bool or 'cpu_trial_result' not in value or
                (current == 'STARTED_AS_OBSERVED' or value['started_ack_sha256'] is not None) and
                    not value['cpu_trial_release_attempted'] or
                value['cpu_trial_release_attempted'] and current not in PHASES[4:] or
                old is not None and old['cpu_trial_release_attempted'] and not value['cpu_trial_release_attempted'] or
                value['cpu_trial_result'] is not None and
                    (current != 'FIXTURE_SCOPE_STOPPED' or not value['cpu_trial_release_attempted'])):
            raise Conflict('CPU trial original release/result phase differs')
        if value['cpu_trial_result'] is not None: validate_result(value['cpu_trial_result'], value['origin'], value['producer'])
    elif any(name in value for name in ('cpu_trial_release_attempted', 'cpu_trial_result')):
        raise Conflict('protocol capability cannot acquire CPU trial fields')
    engineering=value['origin']['kind']==ENGINEERING_KIND
    if engineering:
        from .hybrid_engineering_patch import validate_result
        if (type(value.get('engineering_release_attempted')) is not bool or 'engineering_patch_result' not in value or
                (current=='STARTED_AS_OBSERVED' or value['started_ack_sha256'] is not None) and not value['engineering_release_attempted'] or
                value['engineering_release_attempted'] and current not in PHASES[4:] or
                old is not None and old['engineering_release_attempted'] and not value['engineering_release_attempted'] or
                value['engineering_patch_result'] is not None and (current!='FIXTURE_SCOPE_STOPPED' or not value['engineering_release_attempted'])):
            raise Conflict('engineering patch original release/result phase differs')
        if value['engineering_patch_result'] is not None:validate_result(value['engineering_patch_result'],value['origin'],value['producer'])
    elif any(k in value for k in ('engineering_release_attempted','engineering_patch_result')):
        raise Conflict('another profile cannot acquire engineering result fields')
    _control_links(request, old)
    if value['phase'] != current: raise Conflict('fixture runtime action/phase differs')
    if request['data_mode'] != 'fixture': raise Conflict('fixed CPU runtime is fixture only')
    if current == 'REGISTER_NO_HANDOFF':
        if (prior is None or prior['status'] != 'HELD' or
                prior['runtime_registration'] != 'NOT_AUTHORIZED' or
                value['registration'] is not None or value['previous'] is not None or
                value['producer'] is not None or value['started_ack_sha256'] is not None or
                value['terminal_proof_sha256'] is not None or value['wall_seconds'] != 0):
            raise Conflict('fixture registration requires exact unregistered HELD origin')
        # This fixed CPU diagnostic does not spend/settle synthetic model tokens.
        amount = prior['amount']
        if (amount['wall_seconds'] < 4 or
                amount['experiment_starts'] != int(trial) or
                any(n for k, n in amount.items() if k not in ('wall_seconds', 'experiment_starts'))):
            raise Conflict('fixed CPU runtime requires wall-only finite reservation')
        return value
    if old is None or old['origin'] != value['origin']:
        raise Conflict('fixture runtime original task/attempt/lease differs')
    expected = {'key': prior['last_entry_key'], 'hash': prior['last_entry_hash']}
    if value['previous'] != expected or value['registration'] is None:
        raise Conflict('fixture runtime prior or registration reference differs')
    allowed = {
        'HANDOFF_UNKNOWN': {'REGISTER_NO_HANDOFF'},
        'PROCESS_REGISTERED': {'HANDOFF_UNKNOWN'},
        'RELEASE_INTENT': {'PROCESS_REGISTERED'},
        'STARTED_AS_OBSERVED': {'RELEASE_INTENT'},
        'STOP_REQUESTED': set(PHASES[:-2]),
        'FIXTURE_SCOPE_STOPPED': {'STOP_REQUESTED'},
    }[current]
    if old['phase'] not in allowed: raise Conflict('fixture runtime one-way transition refused')
    if old['registration'] is not None and value['registration'] != old['registration']:
        raise Conflict('fixture runtime registration lineage changed')
    if current == 'HANDOFF_UNKNOWN' and value['registration'] != expected:
        raise Conflict('fixture runtime first registration reference differs')
    if current in ('PROCESS_REGISTERED', 'RELEASE_INTENT', 'STARTED_AS_OBSERVED') and value['producer'] is None:
        raise Conflict('fixture runtime requires original actual participant identity')
    if old['producer'] is not None and value['producer'] != old['producer']:
        raise Conflict('fixture runtime producer identity changed')
    if current == 'STARTED_AS_OBSERVED' and value['started_ack_sha256'] is None:
        raise Conflict('fixture runtime requires original observed child ACK')
    if old['started_ack_sha256'] is not None and value['started_ack_sha256'] != old['started_ack_sha256']:
        raise Conflict('fixture runtime original child ACK changed')
    if current == 'FIXTURE_SCOPE_STOPPED':
        if value['terminal_proof_sha256'] is None:
            raise Conflict('fixture terminal requires original complete finite scope proof')
        # A known overrun remains consumed/visible and blocks later reserve;
        # it must not be clipped into a false within-budget settlement.
    elif value['terminal_proof_sha256'] is not None or value['wall_seconds'] != 0:
        raise Conflict('nonterminal fixture cannot supply a refund or consumption')
    return value


def validate_original_links(value, lookup):
    """Prove immutable plan and registration sources, not any live FD/lease."""
    from .hybrid_working_plan import SECTIONS, validate_record, validate_links
    from .hybrid_budget_ledger import SECTIONS as BUDGET
    request = value['request']; runtime = request['fixture_runtime']; origin = runtime['origin']
    if origin['kind']==ENGINEERING_KIND:
        from .hybrid_engineering_patch import approved_binding
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        sources=value['policy_source'];record=lookup(GOALS[0],sources['contract_key']);approval=lookup(AUTHORITY[0],sources['approval_key'])
        if record is None or approval is None:raise Conflict('engineering original approval missing')
        binding=approved_binding(record['contract']['proposal'],approval['registry_witness'],
            origin['program_sha256'],origin['engineering_patch']['evaluator_sha256'])
        binding.update(grant_id=origin['engineering_patch']['grant_id'],
            **{k:sources[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if canonical(binding)!=canonical(origin['engineering_patch']):raise Conflict('engineering original approved profile binding differs')
    if origin['kind'] == CPU_KIND:
        from .hybrid_cpu_trial import approved_binding
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        sources = value['policy_source']; record = lookup(GOALS[0], sources['contract_key'])
        approval = lookup(AUTHORITY[0], sources['approval_key'])
        if record is None or approval is None: raise Conflict('CPU trial original approval missing')
        binding = approved_binding(record['contract']['proposal'], approval['registry_witness'],
                                  origin['program_sha256'], origin['cpu_trial']['evaluator_sha256'])
        # Budget.validate_links has already proved these exact policy sources
        # with _references (whole original Registry/approval/confirmation).
        # Do not recursively rebuild that same Registry a second time here.
        binding.update(grant_id=origin['cpu_trial']['grant_id'], proposal_hash=sources['proposal_hash'],
                       approval_hash=sources['approval_hash'], config_hash=sources['config_hash'],
                       scope_hash=sources['scope_hash'])
        if origin['cpu_trial'] != binding: raise Conflict('CPU trial grant differs from original approved sources')
    for section, field in zip(SECTIONS, ('working_plan_intent', 'working_plan_ready')):
        ref = origin[field]; original = lookup(section, ref['key'])
        if original is None or digest(original) != ref['hash']:
            raise Conflict('fixture runtime original Working plan missing or changed')
        validate_record(section, ref['key'], original)
        # READY's validator already recursively proves its original INTENT.
        # Do not re-expand the same historical closure a second time.
        if section == SECTIONS[1]: validate_links(section, original, lookup)
        if (original['accepted_state_version'] >= value['accepted_state_version'] or
                any(original['request'][key] != request[key] for key in ('project_id', 'data_mode', 'store_epoch', 'goal_ref')) or
                original['source_context']['budget_reservation']['reservation_id'] != request['reservation_id']):
            raise Conflict('fixture runtime Working plan source scope differs')
    intent = lookup(SECTIONS[0], origin['working_plan_intent']['key'])
    ready = lookup(SECTIONS[1], origin['working_plan_ready']['key'])
    if (ready['request']['intent_key'] != origin['working_plan_intent']['key'] or
            ready['request']['intent_hash'] != digest(intent) or ready['plan_hash'] != digest(intent['plan'])):
        raise Conflict('fixture runtime READY does not close original INTENT')
    ref = runtime['registration']
    if ref is not None:
        registered = lookup(BUDGET[0], ref['key'])
        if (registered is None or digest(registered) != ref['hash'] or
                registered['request']['action'] != ACTIONS[0] or
                registered['request']['fixture_runtime']['origin'] != origin or
                registered['request']['reservation_id'] != request['reservation_id'] or
                registered['accepted_state_version'] >= value['accepted_state_version']):
            raise Conflict('fixture runtime original registration proof differs')
    if runtime['phase'] == 'FIXTURE_SCOPE_STOPPED' and runtime['producer'] is None:
        stop = lookup(BUDGET[0], runtime['previous']['key'])
        previous = stop['request']['fixture_runtime']['previous'] if stop is not None else None
        before = lookup(BUDGET[0], previous['key']) if previous is not None else None
        if (stop is None or digest(stop) != runtime['previous']['hash'] or before is None or
                digest(before) != previous['hash'] or
                before['request']['fixture_runtime']['phase'] != 'REGISTER_NO_HANDOFF' or
                runtime['wall_seconds'] != 0):
            raise Conflict('fixture no-producer terminal requires original NO_HANDOFF lineage')
    # Original predecessor derived HEAD verification stays in Budget links.


def dependency_lookup(store, db, read, state):
    """Bounded original-event reads for plan's immutable historical closure.

    No live grant is minted. Mutable historical heads are compared by domain
    validators to their original immutable source, never cached as current.
    """
    from .hybrid_working_plan import SECTIONS as PLANS, EVENTS as PLAN_EVENTS, expected_objects as plan_objects, event_inputs as plan_inputs
    from .hybrid_runtime_installation import SECTIONS as INSTALLATION, EVENTS as INSTALL_EVENTS, expected_objects as install_objects, event_inputs as install_inputs
    from .hybrid_workspace import SECTIONS as WORKSPACE, EVENT as WORKSPACE_EVENT, expected_objects as workspace_objects
    from .hybrid_controller import SECTIONS as CONTROLLER, EVENT as CONTROLLER_EVENT, head as controller_head
    from .hybrid_preparation import SECTIONS as PREPARATION
    from .hybrid_budget_ledger import SECTIONS as BUDGET, EVENT as BUDGET_EVENT, expected_objects as budget_objects
    def lookup(section, key):
        if key in state.get(section, {}): return state[section][key]
        value = read.object(section, key)
        if value is None: return None
        if section in PLANS:
            index = PLANS.index(section)
            proof = store._working_plan_event(db, key, _parse=read.parse, _decode=read.decode)
            expected = ((PLAN_EVENTS[index], 'hybrid-core', value['request']['plan_id'], value['accepted_state_version']),
                        plan_objects(section, key, value), plan_inputs(value))
        elif section in INSTALLATION:
            index = INSTALLATION.index(section)
            proof = store._installation_event(db, key, _parse=read.parse, _decode=read.decode)
            expected = ((INSTALL_EVENTS[index], 'hybrid-installer', value['request']['installation_id'], value['accepted_state_version']),
                        install_objects(section, key, value), install_inputs(value))
        elif section == WORKSPACE[0]:
            proof = store._workspace_event(db, key, _parse=read.parse, _decode=read.decode)
            expected = ((WORKSPACE_EVENT, 'hybrid-core', value['request']['reservation_id'], value['accepted_state_version']), workspace_objects(value))
        elif section == BUDGET[0]:
            from .hybrid_budget import account_key
            from .hybrid_budget_ledger import scope
            proof = store._budget_event(db, key, _parse=read.parse, _decode=read.decode)
            expected = ((BUDGET_EVENT, 'hybrid-core', account_key(scope(value['request'])), value['accepted_state_version']), budget_objects(value))
        elif section == CONTROLLER[0]:
            from .hybrid_controller import scope_key
            proof = store._controller_event(db, key, _parse=read.parse, _decode=read.decode)
            expected = ((CONTROLLER_EVENT, 'hybrid-core', digest(value), value['accepted_state_version']),
                        sorted([(CONTROLLER[0], key, digest(value)), (CONTROLLER[1], scope_key(value['request']['project_id'], value['request']['data_mode']), digest(controller_head(value)))]))
        else:
            # Claimed heads/Workspace claim are verified against original facts
            # by WorkingPlan's closed historical links. Goal/preparation proofs
            # are also checked by the surrounding original Budget dependency set.
            proof = expected = None
        if proof != expected: raise Conflict('fixture runtime immutable dependency original event differs')
        state.setdefault(section, {})[key] = value
        return value
    return lookup
