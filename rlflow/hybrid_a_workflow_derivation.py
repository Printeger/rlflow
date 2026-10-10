"""Original first Engineer derivation; never manufactures later model evidence.

The live owner binds its original-issued published WorkingPlan; original
physical/current-state gates are rechecked at registration. This pure
derivation is replayed over the original persisted plan/approval. Frozen file
bytes must match the original manifest.
Reviewer derivation requires authenticated executed CPU and Engineer parents.
Repair and continuation are not admitted by these first-stage derivations.
"""
from .hybrid_a_workflow_profile import validate_approval, registration
from .hybrid_engineering_candidate import _snapshot
from .hybrid_goals import digest
from .hybrid_native_model_profile import PROFILE, validate_spec
from .hybrid_working_plan import intent_key, result_key
from .store import Conflict


def first_engineer(proposal, config, program_sha256, intent, ready, files,*,accounted=True):
    approval=validate_approval(proposal,config)
    spec=config['tools']['native_model']['definition']['spec']; files=_snapshot(files)
    if (program_sha256!=spec['model_gate_sha256'] or
            intent['plan']['packet']['role']!='Engineer' or
            ready['request']['intent_key']!=intent_key(intent['request']) or
            ready['request']['intent_hash']!=digest(intent) or
            ready['plan_hash']!=digest(intent['plan'])):
        raise Conflict('original workflow first Engineer plan/gate required')
    packet=dict(role='Engineer',files=files,objective=proposal['objective'],
        conditions=proposal['global_conditions'])
    schema=registration(spec)['tools']['native_model']['definition']['roles']['Engineer']['output_schema']
    sessions=spec['medium_sessions']+spec['high_sessions']
    binding=validate_spec(dict(profile=PROFILE,role='Engineer',model=spec['model'],effort='medium',
        account_mode=spec['account_mode'],workspace_id=spec['workspace_id'],
        packet_sha256=digest(packet),output_schema_sha256=digest(schema),candidate_sha256=digest(files),
        binary_sha256=spec['model_binary_sha256'],gate_sha256=spec['model_gate_sha256'],
        model_input_tokens=max(1,spec['input_tokens_soft']//sessions),
        model_output_tokens=max(1,spec['output_tokens_soft']//sessions),
        seconds=spec['session_seconds'],token_enforcement=spec['token_enforcement'],
        network_enforcement=spec['network_enforcement'],model_tools=False,api_billing=False,
        account_switch=False,gpu_enabled=False))
    # Reuse the exact original manifest/role/objective/conditions checks; this
    # function never treats a caller dictionary or a matching hash as source.
    from .hybrid_native_model_runtime import bind_packet
    bind_packet(packet,binding,intent,proposal)
    binding.update(command_sha256=digest(config['commands']['native_model']),
        resource_sha256=digest(config['resource_profile']),workflow={
            'profile':spec['profile'],'stage':'FIRST_ENGINEER',
            'envelope_sha256':approval['envelope_sha256'],
            'intent':{'key':intent_key(intent['request']),'hash':digest(intent)},
            'ready':{'key':result_key(ready['request']),'hash':digest(ready)},'files':files})
    if accounted:
        binding['workflow'].update(accounting_version='A_REGISTRATION_CEILINGS_V1',
            limits={field:spec[field] for field in
                ('medium_sessions','high_sessions','controlled_seconds','wall_seconds')})
    return binding, packet, schema


def independent_reviewer(proposal,config,program_sha256,intent,ready,cpu,engineer):
    from .hybrid_a_workflow_review import from_cpu
    material=from_cpu(proposal,config,cpu,engineer)
    spec=config['tools']['native_model']['definition']['spec']
    if (program_sha256!=spec['model_gate_sha256'] or intent['plan']['packet']['role']!='Evaluator' or
            intent['plan']['write_roots'] or ready['request']['intent_key']!=intent_key(intent['request']) or
            ready['request']['intent_hash']!=digest(intent) or ready['plan_hash']!=digest(intent['plan'])):
        raise Conflict('original independent readonly Evaluator plan/gate required')
    binding={**material['spec'],'command_sha256':digest(config['commands']['native_model']),
        'resource_sha256':digest(config['resource_profile']),
        'workflow':{'profile':spec['profile'],'stage':'INDEPENDENT_REVIEW',
            'envelope_sha256':material['envelope_sha256'],
            'intent':{'key':intent_key(intent['request']),'hash':digest(intent)},
            'ready':{'key':result_key(ready['request']),'hash':digest(ready)},
            'files':material['packet']['files'],'parents':material['parents'],
            'machine_result_sha256':material['machine_result_sha256'],
            'cpu_registration':cpu['prior_goal']['workflow']['candidate_cpu_entry'],
            'accounting_version':'A_REGISTRATION_CEILINGS_V1',
            'limits':{k:spec[k] for k in ('medium_sessions','high_sessions','controlled_seconds','wall_seconds')}}}
    from .hybrid_native_model_runtime import bind_packet
    bind_packet(material['packet'],binding,intent,proposal)
    return binding,material['packet'],material['schema']
