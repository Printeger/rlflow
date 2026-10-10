"""Pure Reviewer material from original CPU/Engineer parents, never authority."""
from copy import deepcopy
import json

from .hybrid_a_workflow_cpu import from_engineer
from .hybrid_a_workflow_profile import validate_approval,registration
from .hybrid_budget_ledger import entry_key
from .hybrid_goals import digest,check_bytes
from .hybrid_local_cpu_profile import KIND
from .hybrid_local_cpu_result import validate_result
from .hybrid_native_model_profile import PROFILE,validate_spec
from .store import Conflict


def from_cpu(proposal,config,cpu,engineer):
    """Replayable DATA only. Original owner must authenticate both whole events."""
    approval=validate_approval(proposal,config)
    envelope=config['tools']['native_model']['definition']['spec']
    request=cpu['request'];runtime=request.get('fixture_runtime',{})
    origin=runtime.get('origin',{});binding=origin.get('local_cpu',{})
    workflow=binding.get('workflow',{})
    # A new reservation observes a later Store snapshot. These two sampling
    # fields are not approval identity (same rule as original Budget guards).
    def policy_identity(value):
        return {k:v for k,v in value.get('policy_source',{}).items()
            if k not in ('source_version','evaluated_at')}
    if (origin.get('kind')!=KIND or runtime.get('phase')!='FIXTURE_SCOPE_STOPPED' or
            cpu.get('decision')!='SETTLED' or workflow.get('stage')!='CANDIDATE_CPU' or
            workflow.get('envelope_sha256')!=approval['envelope_sha256'] or
            workflow.get('parent')!={'key':entry_key(engineer['request']),'hash':digest(engineer)} or
            any(request.get(k)!=engineer['request'].get(k) for k in
                ('project_id','data_mode','goal_ref','store_epoch')) or
            policy_identity(cpu)!=policy_identity(engineer)):
        raise Conflict('original same-approval settled CPU and Engineer parents required')
    expected,spec=from_engineer(proposal,config,origin['program_sha256'],engineer,workflow['modules'])
    expected.update(grant_id=binding['grant_id'],**{k:cpu['policy_source'][k] for k in
        ('proposal_hash','approval_hash','config_hash','scope_hash')})
    if expected!=binding:raise Conflict('original CPU binding differs from Engineer parent')
    terminal=runtime.get('local_cpu_terminal_proof')
    if terminal is None or terminal.get('configured_local_result') is None:
        raise Conflict('original durable CPU result required for Reviewer')
    result=terminal['configured_local_result'];closed=terminal['managed_service_proof']['task_closed']
    validate_result(result,origin,closed['task'],closed['stopped'],spec)
    if result['machine_acceptance']['status']!='PASS' or result.get('execution',{}).get('status')!='SUCCEEDED':
        raise Conflict('original successful machine acceptance required for Reviewer')
    files=engineer['request']['fixture_runtime']['native_model_result']['files']
    if digest(files)!=workflow['candidate_sha256']:
        raise Conflict('original Reviewer candidate differs from executed CPU candidate')
    packet={'role':'Evaluator','files':deepcopy(files),'objective':proposal['objective'],
        'conditions':deepcopy(proposal['global_conditions'])}
    schema=registration(envelope)['tools']['native_model']['definition']['roles']['Evaluator']['output_schema']
    sessions=envelope['medium_sessions']+envelope['high_sessions']
    model=validate_spec({'profile':PROFILE,'role':'Evaluator','model':envelope['model'],'effort':'high',
        'account_mode':envelope['account_mode'],'workspace_id':envelope['workspace_id'],
        'packet_sha256':digest(packet),'output_schema_sha256':digest(schema),
        'candidate_sha256':digest(files),'binary_sha256':envelope['model_binary_sha256'],
        'gate_sha256':envelope['model_gate_sha256'],
        'model_input_tokens':max(1,envelope['input_tokens_soft']//sessions),
        'model_output_tokens':max(1,envelope['output_tokens_soft']//sessions),
        'seconds':envelope['session_seconds'],'token_enforcement':envelope['token_enforcement'],
        'network_enforcement':envelope['network_enforcement'],'model_tools':False,
        'api_billing':False,'account_switch':False,'gpu_enabled':False})
    value={'packet':packet,'schema':deepcopy(schema),'spec':model,
        'envelope_sha256':approval['envelope_sha256'],
        'parents':{'engineer':{'key':entry_key(engineer['request']),'hash':digest(engineer)},
            'cpu':{'key':entry_key(request),'hash':digest(cpu)}},
        'machine_result_sha256':digest(result),'condition_evidence_enabled':False}
    check_bytes(packet,60000);check_bytes(value,144*1024)
    return value
