"""Approved demand from original accepted task. Pure DATA never grants effects."""
from copy import deepcopy

from .hybrid_a_workflow_profile import validate_approval,registration
from .hybrid_a_condition_acceptance import validate_record,fact_key
from .hybrid_a_condition_rules import derive
from .hybrid_goals import digest,check_bytes
from .hybrid_native_model_profile import PROFILE,validate_spec
from .store import Conflict


def from_acceptance(proposal,config,acceptance,parents):
    approval=validate_approval(proposal,config)
    spec=config['tools']['native_model']['definition']['spec']
    task=spec.get('continuation_task')
    if task is None:raise Conflict('no explicitly approved continuation demand; do not invent work')
    validate_record(fact_key(acceptance['request']),acceptance)
    actual=derive(proposal,config,parents['cpu'],parents['engineer'],parents['reviewer'])
    if (any(acceptance[k]!=v for k,v in actual.items()) or
            acceptance['sources']['proposal_hash']!=digest(proposal) or
            acceptance['sources']['config_hash']!=digest(config)):
        raise Conflict('continuation demand and original accepted candidate approval differ')
    files=parents['engineer']['request']['fixture_runtime']['native_model_result']['files']
    packet={'role':'Engineer','files':deepcopy(files),'objective':task['objective'],
        'conditions':deepcopy(proposal['global_conditions'])}
    schema=registration(spec)['tools']['native_model']['definition']['roles']['Engineer']['output_schema']
    sessions=spec['medium_sessions']+spec['high_sessions']
    model=validate_spec({'profile':PROFILE,'role':'Engineer','model':spec['model'],'effort':'medium',
        'account_mode':spec['account_mode'],'workspace_id':spec['workspace_id'],
        'packet_sha256':digest(packet),'output_schema_sha256':digest(schema),'candidate_sha256':digest(files),
        'binary_sha256':spec['model_binary_sha256'],'gate_sha256':spec['model_gate_sha256'],
        'model_input_tokens':max(1,spec['input_tokens_soft']//sessions),
        'model_output_tokens':max(1,spec['output_tokens_soft']//sessions),
        'seconds':spec['session_seconds'],'token_enforcement':spec['token_enforcement'],
        'network_enforcement':spec['network_enforcement'],'model_tools':False,'api_billing':False,
        'account_switch':False,'gpu_enabled':False})
    value={'packet':packet,'schema':deepcopy(schema),'spec':model,'task_id':task['task_id'],
        'acceptance':{'key':fact_key(acceptance['request']),'hash':digest(acceptance)},
        'parents':actual['parents'],'envelope_sha256':approval['envelope_sha256'],
        'condition_evidence_enabled':False,'goal_completed':False}
    check_bytes(packet,60000);check_bytes(value,144*1024)
    return value
