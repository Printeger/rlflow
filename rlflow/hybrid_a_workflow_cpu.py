"""Same-envelope CPU derivation. Pure data NEVER authenticates a parent.

The original owner must prove the protected parent event/history and its exact
Source capability, then supply new workspace/reservation/plan capabilities.
"""
import hashlib
import json
from copy import deepcopy

from .hybrid_a_workflow_profile import validate_approval
from .hybrid_engineering_candidate import transform,verification_spec
from .hybrid_goals import digest,head_key
from .hybrid_local_cpu_profile import registration,PROFILE
from .hybrid_native_model_profile import KIND as MODEL_KIND
from .hybrid_native_model_result import validate_publication
from .hybrid_budget_ledger import entry_key
from .store import Conflict


def from_engineer(proposal,config,program_sha256,parent,pins):
    approval=validate_approval(proposal,config)
    envelope=config['tools']['native_model']['definition']['spec']
    request=parent['request'];runtime=request.get('fixture_runtime',{})
    origin=runtime.get('origin',{});model=origin.get('native_model',{})
    workflow=model.get('workflow',{})
    if (proposal['data_mode']!='live' or
            any(request.get(k)!=proposal[k] for k in ('project_id','data_mode')) or
            request.get('goal_ref')!=head_key(proposal['project_id'],'live',proposal['goal_id']) or
            parent.get('decision')!='SETTLED' or parent.get('reason')!='NATIVE_MODEL_USAGE_SETTLED' or
            runtime.get('phase')!='FIXTURE_SCOPE_STOPPED' or origin.get('kind')!=MODEL_KIND or
            model.get('role')!='Engineer' or model.get('effort')!='medium' or
            workflow.get('stage')!='FIRST_ENGINEER' or
            workflow.get('accounting_version')!='A_REGISTRATION_CEILINGS_V1' or
            workflow.get('envelope_sha256')!=approval['envelope_sha256'] or
            digest(pins)!=envelope['cpu_modules_sha256']):
        raise Conflict('original live settled Engineer and same workflow CPU pins required')
    result=runtime.get('native_model_result')
    if result is None:raise Conflict('original durable Engineer candidate required')
    validate_publication(result,runtime,approved_paths=envelope['candidate_paths'])
    candidate=transform(workflow['files'],json.loads(result['message_utf8']),
        allowed_paths=envelope['candidate_paths'])
    spec=verification_spec(candidate,checks=envelope['checks'],acceptance=envelope['cpu_acceptance'],
        seconds=envelope['cpu_seconds'],limits=envelope['cpu_limits'])
    registration(spec,pins)  # exact pin names/format, not a new standalone approval
    if program_sha256!=pins['hybrid_local_runner_service.py']:
        raise Conflict('original pinned CPU service required')
    binding={'profile':PROFILE,'purpose':'engineering','task_seconds':spec['seconds'],
        'code_sha256':'sha256:'+hashlib.sha256(spec['code'].encode()).hexdigest(),
        'inputs_sha256':digest(spec['inputs']),'modules_sha256':digest(pins),'spec_sha256':digest(spec),
        'command_sha256':digest(config['commands']['local_cpu']),
        'resource_sha256':digest(config['resource_profile']),
        'workflow':{'profile':envelope['profile'],'stage':'CANDIDATE_CPU',
            'accounting_version':'A_REGISTRATION_CEILINGS_V1','envelope_sha256':approval['envelope_sha256'],
            'parent':{'key':entry_key(request),'hash':digest(parent)},
            'candidate_sha256':candidate.output_sha256,'acceptance_sha256':digest(envelope['cpu_acceptance']),
            'modules':deepcopy(pins),
            'limits':{key:envelope[key] for key in
                ('medium_sessions','high_sessions','controlled_seconds','wall_seconds')}}}
    return binding,spec
