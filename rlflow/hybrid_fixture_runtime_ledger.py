"""Closed fixed CPU runtime lineage; never a native/model execution grant.

The protected owner and Budget's actual writer must prove these facts. This
module supplies deterministic arithmetic/links, not caller attestations.
"""
from .hybrid_protocol import ID, HASH, obj, enum, validate_schema
from .hybrid_goals import digest
from .store import Conflict,canonical
from .hybrid_cpu_trial import BINDING as CPU_BINDING, KIND as CPU_KIND, AUTHORIZATION as CPU_AUTHORIZATION
from .hybrid_engineering_patch import BINDING as ENGINEERING_BINDING,KIND as ENGINEERING_KIND,AUTHORIZATION as ENGINEERING_AUTHORIZATION
from .hybrid_local_cpu_profile import BINDING as LOCAL_BINDING,KIND as LOCAL_KIND,AUTHORIZATION as LOCAL_AUTHORIZATION
from .hybrid_native_model_profile import BINDING as MODEL_BINDING,KIND as MODEL_KIND,AUTHORIZATION as MODEL_AUTHORIZATION

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
DIAGNOSTIC_KIND='LOCAL_NATIVE_DIAGNOSTIC'
DIAGNOSTIC_BINDING=obj({'profile':{'const':'FIXED_NATIVE_LOCAL_DIAGNOSTIC_V1'},
    'binary_sha256':HASH,'evaluator_sha256':HASH,'command_sha256':HASH,'resource_sha256':HASH,
    'grant_id':ID,'proposal_hash':HASH,'approval_hash':HASH,'config_hash':HASH,'scope_hash':HASH})
DIAGNOSTIC_ORIGIN=obj({**PROTOCOL_ORIGIN['properties'],'kind':{'const':DIAGNOSTIC_KIND},
    'authorization':{'const':'LOCAL_NON_GENERATING_DIAGNOSTIC_ONLY'},
    'scenario':{'const':'native_diagnostic'},'native_diagnostic':DIAGNOSTIC_BINDING})
LOCAL_ORIGIN=obj({**PROTOCOL_ORIGIN['properties'],'kind':{'const':LOCAL_KIND},
    'authorization':{'const':LOCAL_AUTHORIZATION},'scenario':{'const':'local_cpu'},
    'local_cpu':LOCAL_BINDING})
ORIGIN={'type':'object','if':{'properties':{'kind':{'const':'PROTOCOL_CONFORMANCE'}},'required':['kind']},
    'then':PROTOCOL_ORIGIN,'else':{'if':{'properties':{'kind':{'const':CPU_KIND}},'required':['kind']},
    'then':CPU_ORIGIN,'else':{'if':{'properties':{'kind':{'const':DIAGNOSTIC_KIND}},'required':['kind']},
    'then':DIAGNOSTIC_ORIGIN,'else':{'if':{'properties':{'kind':{'const':LOCAL_KIND}},'required':['kind']},
    'then':LOCAL_ORIGIN,'else':ENGINEERING_ORIGIN}}}}
MODEL_ORIGIN=obj({**PROTOCOL_ORIGIN['properties'], 'kind':{'const':MODEL_KIND},
    'authorization':{'const':MODEL_AUTHORIZATION}, 'scenario':{'const':'native_model'},
    'model_enabled':{'const':True}, 'native_model':MODEL_BINDING})
ORIGIN={'type':'object','if':{'properties':{'kind':{'const':MODEL_KIND}},'required':['kind']},
        'then':MODEL_ORIGIN,'else':ORIGIN}
nullable = lambda schema: {'oneOf': [schema, {'type': 'null'}]}
CONTROL_BODY = obj({'action': enum('START_FIXED_CPU', 'STOP_FIXED_SCOPE'),
    'task_id': ID, 'expected_state_version': COUNT})
CONTROL_COMMAND = obj({**CONTROL_BODY['properties'], 'actor_id': ID,
    'idempotency_key': ID, 'command_id': ID, 'request_hash': HASH})
ENGINEERING_CONTROL_BODY = obj({'action':{'const':'START_FIXED_ENGINEERING'},
    'task_id':ID,'expected_state_version':COUNT})
ENGINEERING_CONTROL_COMMAND = obj({**ENGINEERING_CONTROL_BODY['properties'],'actor_id':ID,
    'idempotency_key':ID,'command_id':ID,'request_hash':HASH})
LOCAL_CONTROL_COMMAND = obj({**CONTROL_BODY['properties'],
    'action':enum('START_LOCAL_CPU','STOP_LOCAL_CPU_SCOPE'),
    'actor_id':ID,'idempotency_key':ID,'command_id':ID,'request_hash':HASH})
RUNTIME = obj({'phase': enum(*PHASES), 'origin': ORIGIN,
    'registration': nullable(REFERENCE), 'previous': nullable(REFERENCE),
    'producer': nullable(PROCESS), 'started_ack_sha256': nullable(HASH),
    'terminal_proof_sha256': nullable(HASH), 'wall_seconds': COUNT})
# Optional only for compatibility with already persisted44 facts. A new
# command appears only at its actual accepting phase, then remains immutable.
RUNTIME['properties'].update(start_command={'oneOf':[CONTROL_COMMAND,ENGINEERING_CONTROL_COMMAND,LOCAL_CONTROL_COMMAND]},
    stop_command={'oneOf':[CONTROL_COMMAND,LOCAL_CONTROL_COMMAND]})
RUNTIME['properties'].update(cpu_trial_release_attempted={'type': 'boolean'},
                             cpu_trial_result=nullable({'type': 'object'}))
RUNTIME['properties'].update(engineering_release_attempted={'type':'boolean'},
                            engineering_patch_result=nullable({'type':'object'}))
RUNTIME['properties']['local_cpu_release_attempted']={'type':'boolean'}
RUNTIME['properties']['local_cpu_terminal_proof']=nullable({'type':'object'})
from .hybrid_local_cpu_recovery import SOURCE as RECOVERY_SOURCE
from .hybrid_local_cpu_recovery import SCOPE_RUNTIME
RUNTIME['properties']['local_cpu_recovery_source']=RECOVERY_SOURCE
RUNTIME['properties']['local_cpu_recovery_public_key']={'type':'string','pattern':'^[0-9a-f]{64}$'}
RUNTIME['properties']['local_cpu_scope_binding']=SCOPE_RUNTIME
RUNTIME['properties']['native_model_handoff_attempted']={'type':'boolean'}
from .hybrid_native_model_usage import PUBLICATION as MODEL_USAGE
RUNTIME['properties']['native_model_usage']=nullable(MODEL_USAGE)
from .hybrid_native_model_result import PUBLICATION as MODEL_RESULT
RUNTIME['properties']['native_model_result']=MODEL_RESULT


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
        allowed_action = ('START_FIXED_ENGINEERING' if name=='start_command' and
            runtime['origin']['kind']==ENGINEERING_KIND else action)
        if runtime['origin']['kind']==LOCAL_KIND:
            allowed_action='START_LOCAL_CPU' if name=='start_command' else 'STOP_LOCAL_CPU_SCOPE'
        if (runtime['phase'] != acceptance or command['action'] != allowed_action or
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
    generating=value['origin']['kind']==MODEL_KIND
    if generating:
        entered=value.get('native_model_handoff_attempted')
        if (type(entered) is not bool or
                current=='REGISTER_NO_HANDOFF' and entered or
                current in ('HANDOFF_UNKNOWN','PROCESS_REGISTERED','RELEASE_INTENT','STARTED_AS_OBSERVED') and not entered or
                old is not None and old.get('native_model_handoff_attempted') and not entered or
                entered and old is not None and not old.get('native_model_handoff_attempted') and current!='HANDOFF_UNKNOWN'):
            raise Conflict('generating model original handoff latch differs')
        usage=value.get('native_model_usage')
        if usage is not None:
            from .hybrid_native_model_usage import validate_publication
            validate_publication(usage,value)
        if old is not None and old.get('native_model_usage') is not None and usage!=old['native_model_usage']:
            raise Conflict('original native usage publication changed')
        result=value.get('native_model_result')
        if result is not None:
            from .hybrid_native_model_result import validate_publication as validate_result
            validate_result(result,value)
        if old is not None and old.get('native_model_result') is not None and result!=old['native_model_result']:
            raise Conflict('original durable native result changed')
    elif 'native_model_handoff_attempted' in value:
        raise Conflict('zero-model profile cannot acquire generating handoff fields')
    if not generating and 'native_model_usage' in value:
        raise Conflict('zero-model profile cannot acquire native usage publication')
    if not generating and 'native_model_result' in value:
        raise Conflict('zero-model profile cannot acquire native result publication')
    local=value['origin']['kind']==LOCAL_KIND
    if local:
        publication=value.get('local_cpu_recovery_source')
        previous=None if old is None else old.get('local_cpu_recovery_source')
        if publication is not None:
            from .hybrid_local_cpu_recovery import validate_source
            validate_source(publication)
            if previous is None and current not in ('HANDOFF_UNKNOWN','STOP_REQUESTED'):
                raise Conflict('recovery publication must bind before dispatch')
        if previous is not None and publication!=previous:
            raise Conflict('original recovery publication changed')
        key=value.get('local_cpu_recovery_public_key');old_key=None if old is None else old.get('local_cpu_recovery_public_key')
        if key is not None and old_key is None and (current!='PROCESS_REGISTERED' or publication is None):
            raise Conflict('original recovery public key must bind before G')
        if old_key is not None and key!=old_key:raise Conflict('original recovery public key changed')
        scope=value.get('local_cpu_scope_binding');old_scope=None if old is None else old.get('local_cpu_scope_binding')
        if scope is not None:
            from .hybrid_local_cpu_recovery import validate_scope
            validate_scope(scope['scope'],publication['unit'] if publication is not None else '')
            if (scope['owner']!=value['origin']['owner'] or key is None or value['producer'] is None or
                    any(item['boot_id']!=value['producer']['boot_id'] for item in (scope['transport'],scope['owner'])) or
                    any(scope['keeper'][key]!=value['producer'][key] for key in ('pid','starttime','boot_id')) or
                    len({scope['owner']['pid'],scope['transport']['pid'],value['producer']['pid']})!=3):
                raise Conflict('original scope recovery producer lineage differs')
        if scope is not None and old_scope is None and current!='PROCESS_REGISTERED':
            raise Conflict('original scope recovery binding must precede G')
        if old_scope is not None and scope!=old_scope:raise Conflict('original scope recovery binding changed')
        released=value.get('local_cpu_release_attempted')
        if (type(released) is not bool or released and current not in PHASES[4:] or
                (current=='STARTED_AS_OBSERVED' or value['started_ack_sha256'] is not None) and not released or
                old is not None and old['local_cpu_release_attempted'] and not released or
                released and old is not None and not old['local_cpu_release_attempted'] and
                    (old['phase']!='RELEASE_INTENT' or old['producer'] is None)):
            raise Conflict('configurable CPU original release phase differs')
        if 'local_cpu_terminal_proof' in value:
            proof=value['local_cpu_terminal_proof']
            if current=='FIXTURE_SCOPE_STOPPED':
                if proof is None:raise Conflict('original configured CPU durable terminal missing')
                from .hybrid_local_cpu_result import validate_terminal
                validate_terminal(proof,value)
            elif proof is not None:raise Conflict('nonterminal configured CPU cannot archive terminal')
    elif any(key in value for key in ('local_cpu_release_attempted','local_cpu_terminal_proof',
            'local_cpu_recovery_source','local_cpu_recovery_public_key','local_cpu_scope_binding')):
        raise Conflict('fixed capability cannot acquire configurable CPU release fields')
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
    if request['data_mode']!='fixture':
        from .hybrid_native_model_profile import KIND as NATIVE_KIND
        workflow=(value['origin'].get('native_model',{}) if value['origin']['kind']==NATIVE_KIND else
            value['origin'].get('local_cpu',{}) if value['origin']['kind']==LOCAL_KIND else {})
        if (request['data_mode']!='live' or
                workflow.get('workflow',{}).get('accounting_version')!='A_REGISTRATION_CEILINGS_V1'):
            raise Conflict('live runtime requires original accounted native engineering workflow')
    if current == 'REGISTER_NO_HANDOFF':
        if (prior is None or prior['status'] != 'HELD' or
                prior['runtime_registration'] != 'NOT_AUTHORIZED' or
                value['registration'] is not None or value['previous'] is not None or
                value['producer'] is not None or value['started_ack_sha256'] is not None or
                value['terminal_proof_sha256'] is not None or value['wall_seconds'] != 0):
            raise Conflict('fixture registration requires exact unregistered HELD origin')
        # This fixed CPU diagnostic does not spend/settle synthetic model tokens.
        amount = prior['amount']
        if generating:
            from .hybrid_native_model_profile import validate_reservation
            validate_reservation(amount,value['origin']['native_model'])
            return value
        needed_seconds=value['origin']['local_cpu']['task_seconds']+10 if local else 4
        starts=int(value['origin']['local_cpu']['purpose']=='research') if local else int(trial)
        if (amount['wall_seconds'] < needed_seconds or
                amount['experiment_starts'] != starts or
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
    if origin['kind']==MODEL_KIND:
        from .hybrid_native_model_profile import approved_binding
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        sources=value['policy_source'];record=lookup(GOALS[0],sources['contract_key']);approval=lookup(AUTHORITY[0],sources['approval_key'])
        if record is None or approval is None:raise Conflict('generating model original approval missing')
        frozen=origin['native_model']
        if 'workflow' in frozen:
            from .hybrid_a_workflow_derivation import first_engineer,independent_reviewer,continuation
            intent=lookup(SECTIONS[0],origin['working_plan_intent']['key'])
            ready=lookup(SECTIONS[1],origin['working_plan_ready']['key'])
            if intent is None or ready is None:raise Conflict('original workflow plans missing')
            if frozen['workflow']['stage']=='INDEPENDENT_REVIEW':
                from .hybrid_budget_ledger import validate_record as budget_record,validate_links as budget_links
                parents={}
                for name,ref in frozen['workflow']['parents'].items():
                    parent=lookup(BUDGET[0],ref['key'])
                    if parent is None or digest(parent)!=ref['hash']:raise Conflict('original Reviewer parent missing or changed')
                    if (any(parent['request'][k]!=request[k] for k in ('project_id','data_mode','goal_ref','store_epoch')) or
                            any(parent['policy_source'][k]!=sources[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash'))):
                        raise Conflict('original Reviewer parent scope or approval differs')
                    budget_record(BUDGET[0],ref['key'],parent);budget_links(parent,lookup);parents[name]=parent
                binding,_,_=independent_reviewer(record['contract']['proposal'],approval['registry_witness'],
                    origin['program_sha256'],intent,ready,parents['cpu'],parents['engineer'])
            elif frozen['workflow']['stage']=='CONTINUATION':
                from .hybrid_a_condition_acceptance import SECTION as CONDITIONS,validate_links as condition_links,validate_record as condition_record
                from .hybrid_budget_ledger import validate_record as budget_record,validate_links as budget_links
                ref=frozen['workflow']['acceptance'];accepted=lookup(CONDITIONS,ref['key'])
                if (accepted is None or digest(accepted)!=ref['hash'] or
                        accepted['accepted_state_version']>=value['accepted_state_version'] or
                        any(accepted['request'][k]!=request[k] for k in ('project_id','data_mode','goal_ref','store_epoch')) or
                        any(accepted['sources'][k]!=sources[k] for k in
                            ('proposal_hash','approval_hash','config_hash','scope_hash'))):
                    raise Conflict('original earlier continuation acceptance scope required')
                condition_record(ref['key'],accepted)
                proof=getattr(lookup,'_condition_proof',None)
                if type(proof) is _ConditionLookupProof and proof.lookup is lookup:proof(accepted)
                else:
                    from .hybrid_fixture_runtime import _FixtureRuntimeGuard
                    guard=getattr(lookup,'__self__',None)
                    if type(guard) is _FixtureRuntimeGuard:guard._condition_links(accepted)
                    else:condition_links(accepted,lookup)
                parents={}
                for name,parent_ref in accepted['parents'].items():
                    parent=lookup(BUDGET[0],parent_ref['key'])
                    if parent is None or digest(parent)!=parent_ref['hash']:
                        raise Conflict('original accepted continuation parent changed')
                    parents[name]=parent
                binding,_,_=continuation(record['contract']['proposal'],approval['registry_witness'],
                    origin['program_sha256'],intent,ready,accepted,parents)
            else:
                binding,_,_=first_engineer(record['contract']['proposal'],approval['registry_witness'],
                    origin['program_sha256'],intent,ready,frozen['workflow']['files'],
                    accounted='accounting_version' in frozen['workflow'])
        else:binding=approved_binding(record['contract']['proposal'],approval['registry_witness'],origin['program_sha256'])
        binding.update(grant_id=origin['native_model']['grant_id'],
            **{k:sources[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if canonical(binding)!=canonical(origin['native_model']):raise Conflict('generating model original approved binding differs')
        if runtime.get('native_model_result') is not None:
            from .hybrid_native_model_result import validate_publication as validate_result
            paths=(approval['registry_witness']['tools']['native_model']['definition']['spec']['candidate_paths']
                if 'workflow' in frozen else None)
            validate_result(runtime['native_model_result'],runtime,approved_paths=paths)
    if origin['kind']==LOCAL_KIND:
        from .hybrid_local_cpu_profile import approved_binding
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        sources=value['policy_source'];record=lookup(GOALS[0],sources['contract_key']);approval=lookup(AUTHORITY[0],sources['approval_key'])
        if record is None or approval is None:raise Conflict('configurable CPU original approval missing')
        frozen=origin['local_cpu']
        if 'workflow' in frozen:
            from .hybrid_a_workflow_cpu import from_engineer
            parent=lookup(BUDGET[0],frozen['workflow']['parent']['key'])
            if (parent is None or digest(parent)!=frozen['workflow']['parent']['hash'] or
                    parent['request']['store_epoch']!=request['store_epoch'] or
                    any(parent['policy_source'][k]!=sources[k] for k in
                        ('proposal_hash','approval_hash','config_hash','scope_hash'))):
                raise Conflict('original same-approval CPU Engineer parent missing or changed')
            from .hybrid_budget_ledger import validate_record as budget_record,validate_links as budget_links
            budget_record(BUDGET[0],frozen['workflow']['parent']['key'],parent)
            budget_links(parent,lookup)
            # Replay uses the approved module digest; it never reads current
            # disk bytes or upgrades a historical parent into live capability.
            pins=frozen['workflow']['modules']
            binding,spec=from_engineer(record['contract']['proposal'],approval['registry_witness'],
                origin['program_sha256'],parent,pins)
        else:
            binding=approved_binding(record['contract']['proposal'],approval['registry_witness'],origin['program_sha256'])
            spec=approval['registry_witness']['tools']['local_cpu']['definition']['spec']
        binding.update(grant_id=origin['local_cpu']['grant_id'],
            **{k:sources[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if canonical(binding)!=canonical(origin['local_cpu']):raise Conflict('configurable CPU original approved binding differs')
        proof=runtime.get('local_cpu_terminal_proof')
        if proof is not None and proof['configured_local_result'] is not None:
            from .hybrid_local_cpu_result import validate_result
            closed=proof['managed_service_proof']['task_closed']
            validate_result(proof['configured_local_result'],origin,closed['task'],closed['stopped'],spec)
    if origin['kind']==DIAGNOSTIC_KIND:
        from .hybrid_native_diagnostic import approved_binding
        from .hybrid_goals import SECTIONS as GOALS
        from .hybrid_authority import SECTIONS as AUTHORITY
        sources=value['policy_source'];record=lookup(GOALS[0],sources['contract_key']);approval=lookup(AUTHORITY[0],sources['approval_key'])
        if record is None or approval is None:raise Conflict('diagnostic original approval missing')
        binding=approved_binding(record['contract']['proposal'],approval['registry_witness'],
            origin['program_sha256'],origin['native_diagnostic']['evaluator_sha256'],origin['native_diagnostic']['binary_sha256'])
        binding.update(grant_id=origin['native_diagnostic']['grant_id'],
            **{k:sources[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if canonical(binding)!=canonical(origin['native_diagnostic']):raise Conflict('diagnostic original approved profile binding differs')
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


_CONDITION_LOOKUP_FACTORY=object()


class _ConditionLookupProof:
    """Factory-held same-read historical closure, never current authorization."""
    def __init__(self,store,db,read,state,lookup,*,_factory=None):
        import threading
        self.store,self.db,self.read,self.state,self.lookup=store,db,read,state,lookup
        self.thread=threading.get_ident()
        self._factory=_factory
        self._completed=None
    def __call__(self,value):
        from .hybrid_a_continuation_runtime import prove_historical_links
        return prove_historical_links(self,value)


def dependency_lookup(store, db, read, state):
    """Bounded original-event reads for plan's immutable historical closure.

    No live grant is minted. Mutable historical heads are compared by domain
    validators to their original immutable source, never cached as current.
    """
    from .hybrid_working_plan import SECTIONS as PLANS, EVENTS as PLAN_EVENTS, expected_objects as plan_objects, event_inputs as plan_inputs
    from .hybrid_runtime_installation import SECTIONS as INSTALLATION, EVENTS as INSTALL_EVENTS, expected_objects as install_objects, event_inputs as install_inputs
    from .hybrid_workspace import SECTIONS as WORKSPACE, EVENT as WORKSPACE_EVENT, expected_objects as workspace_objects
    from .hybrid_controller import SECTIONS as CONTROLLER, EVENT as CONTROLLER_EVENT, head as controller_head
    from .hybrid_preparation import SECTIONS as PREPARATION,EVENTS as PREPARATION_EVENTS,validate_record as preparation_record
    from .hybrid_budget_ledger import SECTIONS as BUDGET, EVENT as BUDGET_EVENT, expected_objects as budget_objects
    from .hybrid_a_condition_acceptance import SECTION as CONDITIONS,original_event as condition_event
    def lookup(section, key):
        if key in state.get(section, {}): return state[section][key]
        value = read.object(section, key)
        if value is None: return None
        if section==CONDITIONS:
            if condition_event(store,db,key,read)!=value:
                raise Conflict('continuation acceptance original whole event differs')
            proof=expected=None
        elif section in PREPARATION:
            preparation_record(section,key,value)
            proof=store._preparation_event(db,key,max_bytes=min(read.remaining,5*1024**2),
                _parse=read.parse,_decode=read.decode)
            expected=((PREPARATION_EVENTS[PREPARATION.index(section)],'hybrid-core',digest(value),
                value['accepted_state_version']),[(section,key,digest(value))])
            if proof!=expected:raise Conflict('fixture original preparation event differs')
            if section==PREPARATION[0]:
                from .hybrid_preparation_sources import historical_sources
                for source_section,rows in historical_sources(store,db,value['sources'],read).items():
                    target=state.setdefault(source_section,{})
                    for source_key,item in rows.items():
                        if source_key in target and target[source_key]!=item:
                            raise Conflict('fixture original preparation historical sources disagree')
                        target[source_key]=item
        elif section in PLANS:
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
    proof=_ConditionLookupProof(store,db,read,state,lookup,_factory=_CONDITION_LOOKUP_FACTORY)
    lookup._condition_proof=proof
    return lookup
