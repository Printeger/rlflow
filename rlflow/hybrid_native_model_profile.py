"""Generating-model binding under development; validation grants NO execution.

Separate from zero-model diagnostic approvals. Actual native source, account
qualification and writer integration must prove these declarations separately.
No credentials, network calls, model launches or caller settlement API here.
"""
from copy import deepcopy

from .hybrid_budget import vector
from .hybrid_goals import check_bytes, digest
from .hybrid_protocol import HASH, ID, obj, enum, validate_schema
from .store import Conflict

PROFILE = 'NATIVE_MODEL_PACKET_V1'
KIND = 'NATIVE_GENERATING_MODEL'
AUTHORIZATION = 'ORIGINAL_APPROVED_MODEL_PACKET_ONLY'
COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 2**63-1}
SPEC = obj({'profile': {'const': PROFILE}, 'role': enum('Engineer', 'Evaluator'),
    'model': {'const': 'gpt-6.1-sol'}, 'effort': enum('medium', 'high'),
    'account_mode': {'const': 'CHATGPT_CURRENT_WORKSPACE_ONLY'},
    'workspace_id': {'type': 'string', 'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'},
    'packet_sha256': HASH, 'output_schema_sha256': HASH, 'candidate_sha256': HASH,
    'binary_sha256': HASH, 'gate_sha256': HASH,
    'model_input_tokens': {**COUNT, 'minimum': 1},
    'model_output_tokens': {**COUNT, 'minimum': 1},
    'seconds': {'type': 'integer', 'minimum': 1, 'maximum': 300},
    'token_enforcement': {'const': 'SOFT_APPROVED'},
    'network_enforcement': {'const': 'PARTIAL_NOT_QUALIFIED'},
    'model_tools': {'const': False}, 'api_billing': {'const': False},
    'account_switch': {'const': False}, 'gpu_enabled': {'const': False}})
BINDING = obj({**SPEC['properties'], 'grant_id': ID, 'proposal_hash': HASH,
    'approval_hash': HASH, 'config_hash': HASH, 'scope_hash': HASH,
    'command_sha256': HASH, 'resource_sha256': HASH})


def validate_spec(spec):
    check_bytes(spec, 8192); validate_schema(SPEC, spec)
    for field in ('model_input_tokens', 'model_output_tokens', 'seconds'):
        if type(spec[field]) is not int:
            raise Conflict('actual generating model limits required')
    return deepcopy(spec)


def registration(spec):
    spec = validate_spec(spec)
    definition = {'profile': PROFILE, 'spec': spec, 'execution_qualified': False}
    return deepcopy({'tool': {'adapter': 'original_native_model_packet', 'definition': definition},
        'command': {'tool_id': 'native_model', 'argv': [PROFILE],
            'parameter_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'network': 'allowlist', 'allowed_hosts': ['chatgpt.com']},
        'rule': {'definition': definition, 'requires_datasets': False},
        'resources': {'native_model': definition, 'mode': 'native_model_packet',
            'enforcement': 'partial', 'command_seconds': spec['seconds']}})


def approved_binding(proposal, config, program_sha256):
    """Closed proposed binding, NOT account/source/kernel qualification.

    Runtime will need same-original approval, sealed packet/schema and actual
    credential owner; workspace UUID/hash strings alone confer no authority.
    No call-number or money hard-cap promise follows from CLI session limits.
    """
    try:
        spec = validate_spec(config['tools']['native_model']['definition']['spec'])
        expected = registration(spec); budget = proposal['budget']
        if (proposal['goal_kind'] != 'engineering' or
                proposal['allowed_tools'] != ['native_model'] or
                proposal['scope']['allowed_command_templates'] != ['native_model'] or
                proposal['scope']['network_access'] != 'allowlist' or
                proposal['scope']['allowed_hosts'] != ['chatgpt.com'] or
                config['tools'] != {'native_model': expected['tool']} or
                config['commands'] != {'native_model': expected['command']} or
                config['evaluation_rules'] != {'native_model_rule': expected['rule']} or
                config['resource_profile'] != expected['resources'] or
                proposal['evaluation_data'] != {'mode': 'EXPLICIT_NONE', 'datasets': [],
                    'evaluation_rule': {'id': 'native_model_rule', 'version_hash': digest(expected['rule'])}} or
                program_sha256 != spec['gate_sha256'] or
                budget['model_token_enforcement'] != 'soft_approved' or
                any(type(budget[name]) is not int or budget[name] < minimum for name, minimum in
                    (('model_sessions', 1), ('model_input_tokens', spec['model_input_tokens']),
                     ('model_output_tokens', spec['model_output_tokens']), ('wall_seconds', spec['seconds']+10))) or
                any(budget[name] != 0 for name in
                    ('gpu_device_seconds', 'experiment_starts', 'experiment_retries'))):
            raise Conflict('fresh exact generating model approval required; no zero-model upgrade')
        return {**spec, 'command_sha256': digest(expected['command']),
                'resource_sha256': digest(expected['resources'])}
    except (KeyError, TypeError, ValueError) as error:
        raise Conflict('closed original generating model approval required') from error


def validate_reservation(amount, binding):
    """One CLI attempt consumes one reserved slot, not one provider request."""
    amount = vector(amount); validate_schema(BINDING, binding)
    if (amount['model_sessions'] != 1 or
            amount['model_input_tokens'] != binding['model_input_tokens'] or
            amount['model_output_tokens'] != binding['model_output_tokens'] or
            amount['wall_seconds'] < binding['seconds']+10 or
            any(amount[name] for name in ('gpu_device_seconds', 'experiment_starts', 'experiment_retries'))):
        raise Conflict('exact generating model attempt reservation required')
    return amount
