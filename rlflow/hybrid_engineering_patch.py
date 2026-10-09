"""Exact approved fixed patch family; proposal is not candidate write authority."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from .hybrid_goals import digest
from .hybrid_protocol import HASH,ID,obj,validate_schema
from .store import canonical,Conflict

PROFILE='FIXED_CPU_ADD_PATCH_V1'
KIND='LOCAL_CPU_PATCH_PROPOSAL'
AUTHORIZATION='FIXED_PATCH_PROPOSAL_ONLY'
TARGET='module/source.py'
BEFORE=b'def add(a, b):\n    return a - b\n'
AFTER=b'def add(a, b):\n    return a + b\n'
CASES=((2,3),(-4,2),(0,0))
hash_bytes=lambda value:'sha256:'+hashlib.sha256(value).hexdigest()
SPEC={'target':TARGET,'before_sha256':hash_bytes(BEFORE),'after_sha256':hash_bytes(AFTER),
      'method':'EXACT_SUBTRACTION_TO_ADDITION_PATCH','tests':[list(v) for v in CASES],
      'candidate_input':'ORIGINAL_READONLY_FD','candidate_write':'TRUSTED_CORE_ONLY_AFTER_STOP'}
LIMITS={'mode':'compatible_cpu','enforcement':'partial','cpu_seconds':2,
        'address_space_bytes':128*1024**2,'output_bytes':1024**2,
        'network_enforcement':'NOT_PROVED','tree_enforcement':'NOT_PROVED',
        'fixed_program_no_network_or_descendants':True}
BINDING=obj({'profile':{'const':PROFILE},'spec_sha256':HASH,'program_sha256':HASH,
    'evaluator_sha256':HASH,'command_sha256':HASH,'resource_sha256':HASH,
    'grant_id':ID,'proposal_hash':HASH,'approval_hash':HASH,'config_hash':HASH,'scope_hash':HASH})


@dataclass(frozen=True,eq=False)
class EngineeringPatchGrant:
    id:str
    raw:bytes


@dataclass(frozen=True,eq=False)
class EngineeringPatchResult:
    raw:bytes


def registration(program_sha256,evaluator_sha256):
    definition={'profile':PROFILE,'spec_sha256':digest(SPEC),'program_sha256':program_sha256,
                'evaluator_sha256':evaluator_sha256,'limits':LIMITS}
    return deepcopy({'tool':{'adapter':'fixed_patch_proposer','definition':definition},
        'command':{'tool_id':'engineering_patch','argv':[PROFILE],
            'parameter_schema':{'type':'object','properties':{},'additionalProperties':False},
            'network':'none','allowed_hosts':[]},
        'rule':{'definition':definition,'requires_datasets':False},
        'resources':{'fixed_patch_proposer':definition,**LIMITS}})


def approved_binding(proposal,config,program_sha256,evaluator_sha256):
    expected=registration(program_sha256,evaluator_sha256)
    if (proposal['goal_kind']!='engineering' or proposal['risk']!='low' or
            proposal['allowed_tools']!=['engineering_patch'] or
            proposal['scope']['allowed_command_templates']!=['engineering_patch'] or
            proposal['scope']['writable_paths']!=['module/'] or
            proposal['scope']['protected_paths']!=['.rlflow/','fixtures/acceptance/'] or
            proposal['scope']['network_access']!='none' or proposal['scope']['allowed_hosts'] or
            proposal['evaluation_data']!={'mode':'EXPLICIT_NONE','datasets':[],
                'evaluation_rule':{'id':'engineering_patch_rule','version_hash':digest(expected['rule'])}} or
            config['tools'].get('engineering_patch')!=expected['tool'] or
            config['commands'].get('engineering_patch')!=expected['command'] or
            config['evaluation_rules'].get('engineering_patch_rule')!=expected['rule'] or
            config['resource_profile']!=expected['resources'] or
            any(proposal['budget'][k]!=0 for k in ('model_sessions','model_input_tokens','model_output_tokens',
                'gpu_device_seconds','experiment_starts','experiment_retries'))):
        raise Conflict('exact approved fixed read-only patch proposer profile required')
    return {'profile':PROFILE,'spec_sha256':digest(SPEC),'program_sha256':program_sha256,
        'evaluator_sha256':evaluator_sha256,'command_sha256':digest(expected['command']),
        'resource_sha256':digest(expected['resources'])}


def evaluate(raw,*,nonce,pid):
    if type(raw) is not bytes or len(raw)>16384 or not raw.endswith(b'\n'):
        raise Conflict('complete bounded original patch source required')
    from .hybrid_usage_stream import parse_line
    events=[parse_line(line) for line in raw.splitlines(keepends=True)]
    if len(events)!=3 or events[0]!={'type':'runtime.started','nonce':nonce,'pid':pid,'program':PROFILE} or events[-1]!={'type':'fixture.end'}:
        raise Conflict('original fixed patch ACK and complete source required')
    event=events[1]
    tests=[{'left':a,'right':b,'expected':a+b,'before':a-b,'after':a+b} for a,b in CASES]
    expected={'type':'engineering.patch','target':TARGET,'before_sha256':hash_bytes(BEFORE),
        'after_sha256':hash_bytes(AFTER),'replacement':AFTER.decode(),'tests':tests,
        'cpu_ns':event.get('cpu_ns'),'wall_ns':event.get('wall_ns')}
    if canonical(event)!=canonical(expected) or any(type(event.get(k)) is not int or not 0<=event[k]<=3*10**9 for k in ('cpu_ns','wall_ns')):
        raise Conflict('original fixed patch/tests/measurements differ')
    return {'profile':PROFILE,'verification':'FIXED_PATCH_SOURCE_VERIFIED','source_sha256':hash_bytes(raw),
        'patch':event,'baseline_failed_cases':sum(v['before']!=v['expected'] for v in tests),
        'repaired_passed_cases':sum(v['after']==v['expected'] for v in tests),
        'candidate_write_performed':False,'goal_completed':False,'independent_review_status':'NOT_PERFORMED',
        'model_enabled':False,'gpu_enabled':False,'resource_enforcement':'partial'}


def validate_result(value,origin,producer):
    if type(value) is not dict or type(producer) is not dict:raise Conflict('original fixed patch result required')
    try:
        events=[{'type':'runtime.started','nonce':origin['nonce'],'pid':producer['pid'],'program':PROFILE},
                value['patch'],{'type':'fixture.end'}]
        raw=b''.join(canonical(event)+b'\n' for event in events)
        expected=evaluate(raw,nonce=origin['nonce'],pid=producer['pid'])
        expected.update({k:value[k] for k in ('source_id','lease_id','task_id','attempt_id','grant_id','producer')})
        if (canonical(value)!=canonical(expected) or value['producer']!=producer or
                any(value[k]!=origin[k] for k in ('lease_id','task_id','attempt_id')) or
                value['grant_id']!=origin['engineering_patch']['grant_id']):
            raise Conflict('original fixed patch result linkage differs')
        for k in ('source_id','lease_id','task_id','attempt_id','grant_id'):validate_schema(ID,value[k])
    except (KeyError,TypeError,ValueError):raise Conflict('closed original fixed patch result required') from None
