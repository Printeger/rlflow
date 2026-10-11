"""A workflow approval envelope, not a packet or an execution capability.

Future attempts must derive their frozen inputs from original persisted facts.
This version cannot be reached by upgrading an existing packet/CPU approval.
"""
from copy import deepcopy

from .hybrid_engineering_candidate import _path, MAX_FILES
from .hybrid_goals import check_bytes, digest
from .hybrid_local_cpu_profile import validate_spec as cpu_spec
from .hybrid_native_model_stream import REVIEW
from .hybrid_protocol import HASH, obj, array, validate_schema
from .store import Conflict

PROFILE = 'A_ENGINEERING_WORKFLOW_V2'
ADAPTER = 'original_a_workflow_v2'
COUNT = lambda high: {'type':'integer','minimum':1,'maximum':high}
PATCH = obj({'base_sha256':HASH,'edits':{**array(obj({
    'path':{'type':'string','minLength':1,'maxLength':200},
    'before_sha256':{'anyOf':[HASH,{'type':'null'}]},
    'after':{'type':['string','null'],'maxLength':49152}}),MAX_FILES),'minItems':1}})
SPEC = obj({'profile':{'const':PROFILE},
    'model':{'const':'gpt-6.1-sol'},
    'account_mode':{'const':'CHATGPT_CURRENT_WORKSPACE_ONLY'},
    'workspace_id':{'type':'string','pattern':'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'},
    'medium_sessions':COUNT(6),'high_sessions':COUNT(2),'session_seconds':COUNT(300),
    'input_tokens_soft':COUNT(400000),'output_tokens_soft':COUNT(32000),
    'wall_seconds':COUNT(5400),'controlled_seconds':COUNT(3600),
    'model_binary_sha256':HASH,'model_gate_sha256':HASH,'cpu_modules_sha256':HASH,
    'candidate_paths':{**array({'type':'string','minLength':1,'maxLength':200},MAX_FILES),
        'minItems':1,'uniqueItems':True},
    'checks':{'type':'string','minLength':1,'maxLength':8192},
    'cpu_seconds':COUNT(300),'cpu_limits':{'type':'object'},'cpu_acceptance':{'type':'object'},
    'repair_sessions':{'type':'integer','minimum':0,'maximum':6},
    'continuations':{'const':1},'token_enforcement':{'const':'SOFT_APPROVED'},
    'network_enforcement':{'const':'PARTIAL_NOT_QUALIFIED'},
    'model_tools':{'const':False},'api_billing':{'const':False},
    'account_switch':{'const':False},'gpu_enabled':{'const':False}})
from .hybrid_a_condition_rules import BINDINGS as CONDITION_BINDINGS
SPEC['properties']['condition_bindings']=CONDITION_BINDINGS
from .hybrid_protocol import ID
SPEC['properties']['continuation_task']=obj({'task_id':ID,
    'objective':{'type':'string','minLength':1,'maxLength':4000}})


def validate_spec(spec):
    check_bytes(spec,16384); validate_schema(SPEC,spec)
    for field in ('medium_sessions','high_sessions','session_seconds','input_tokens_soft',
            'output_tokens_soft','wall_seconds','controlled_seconds','cpu_seconds',
            'repair_sessions','continuations'):
        if type(spec[field]) is not int:raise Conflict('exact workflow counts required')
    if (spec['controlled_seconds']>spec['wall_seconds'] or
            spec['session_seconds']>spec['controlled_seconds'] or
            spec['cpu_seconds']>spec['controlled_seconds'] or
            spec['repair_sessions']+2>spec['medium_sessions'] or spec['high_sessions']<2):
        raise Conflict('workflow must budget first Engineer, continuation and independent reviews')
    for name in spec['candidate_paths']:_path(name)
    if 'continuation_task' in spec and (not spec['continuation_task']['objective'].strip() or
            len(spec['continuation_task']['objective'].encode('utf-8'))>4000):
        raise Conflict('explicit bounded approved continuation demand required')
    if len(spec['checks'].encode('utf-8'))>8192:raise Conflict('bounded trusted workflow checks required')
    # Syntax/limits/rule validation only, NEVER executes trusted or candidate code.
    cpu_spec({'purpose':'engineering','code':spec['checks'],'inputs':{},
        'seconds':spec['cpu_seconds'],'limits':spec['cpu_limits'],'acceptance':spec['cpu_acceptance']})
    return deepcopy(spec)


def registration(spec):
    spec=validate_spec(spec)
    definition={'profile':PROFILE,'spec':spec,'execution_qualified':False,
        'derivation':'ORIGINAL_PERSISTED_FACTS_ONLY',
        'roles':{'Engineer':{'effort':'medium','output_schema':deepcopy(PATCH)},
                 'Evaluator':{'effort':'high','output_schema':deepcopy(REVIEW)}},
        'policy':{'first_engineer':1,'independent_review_per_candidate':True,
                  'repair_sessions_max':spec['repair_sessions'],'continuations_max':1,
                  'continuation_requires':'ORIGINAL_CONDITION_ACCEPTANCE',
                  'unknown_usage':'STOP_NEW_MODEL_SESSIONS'}}
    def command(tool,network,hosts):
        return {'tool_id':tool,'argv':[PROFILE,tool],
            'parameter_schema':{'type':'object','properties':{},'additionalProperties':False},
            'network':network,'allowed_hosts':hosts}
    return deepcopy({'tools':{name:{'adapter':ADAPTER,'definition':deepcopy(definition)}
                       for name in ('native_model','local_cpu')},
        'commands':{'native_model':command('native_model','allowlist',['chatgpt.com']),
                    'local_cpu':command('local_cpu','none',[])},
        'rule':{'definition':deepcopy(definition),'requires_datasets':False},
        'resources':{'workflow':deepcopy(definition),'mode':'a_workflow','enforcement':'partial'}})


def validate_approval(proposal,config):
    """Registry confirmation check. No receipt/lease/dispatch/source authority."""
    try:
        spec=validate_spec(config['tools']['native_model']['definition']['spec'])
        expected=registration(spec); scope=proposal['scope']; budget=proposal['budget']
        required_methods={condition['verification']['method'] for condition in
            proposal['global_conditions'] if condition['required']}
        if (proposal['goal_kind']!='engineering' or proposal['allowed_tools']!=['native_model','local_cpu'] or
                not {'deterministic','independent_review'}<=required_methods or
                scope['allowed_command_templates']!=['native_model','local_cpu'] or
                scope['network_access']!='allowlist' or scope['allowed_hosts']!=['chatgpt.com'] or
                config['tools']!=expected['tools'] or config['commands']!=expected['commands'] or
                config['evaluation_rules']!={'workflow_rule':expected['rule']} or
                config['resource_profile']!=expected['resources'] or
                proposal['evaluation_data']!={'mode':'EXPLICIT_NONE','datasets':[],
                    'evaluation_rule':{'id':'workflow_rule','version_hash':digest(expected['rule'])}} or
                any(budget[field]!=amount for field,amount in (
                    ('model_sessions',spec['medium_sessions']+spec['high_sessions']),
                    ('model_input_tokens',spec['input_tokens_soft']),('model_output_tokens',spec['output_tokens_soft']),
                    ('wall_seconds',spec['wall_seconds']))) or
                budget['model_token_enforcement']!='soft_approved' or
                any(budget[field]!=0 for field in ('gpu_device_seconds','experiment_starts','experiment_retries'))):
            raise Conflict('original exact A workflow envelope approval required')
        for name in spec['candidate_paths']:
            def beneath(root):return name==root.rstrip('/') or name.startswith(root.rstrip('/')+'/')
            if not any(beneath(root) for root in scope['writable_paths']) or any(
                    beneath(root) or root.rstrip('/').startswith(name+'/')
                    for root in scope['protected_paths']):
                raise Conflict('workflow candidate path exceeds approved writable boundary')
        from .hybrid_a_condition_rules import validate_bindings
        validate_bindings(proposal,spec)
        return {'profile':PROFILE,'envelope_sha256':digest(spec),
                'execution_qualified':False,'derivation_enabled':False}
    except (KeyError,TypeError,ValueError) as error:
        raise Conflict('closed original A workflow approval required') from error
