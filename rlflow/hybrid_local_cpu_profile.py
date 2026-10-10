"""Configurable CPU approval contract; pure validation NEVER grants execution.

Distinct from fixed PI/add/native diagnostic profiles. Frozen registry inputs
bind task code, private input manifest, exact trusted modules and kernel limits.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .hybrid_goals import digest
from .hybrid_protocol import HASH, ID, obj, enum
from .store import Conflict, canonical

PROFILE = 'CONFIGURED_LOCAL_CPU_V1'
KIND = 'LOCAL_CONFIGURED_CPU'
AUTHORIZATION = 'ORIGINAL_APPROVED_LOCAL_CPU_ONLY'
MODULES = ('hybrid_local_runner_service.py', 'hybrid_local_runner_keeper.py',
           'hybrid_local_runner_cgroup.py', 'hybrid_local_runner_sandbox.py',
           'hybrid_local_cpu_runtime.py', 'hybrid_local_cpu_source.py', 'hybrid_local_cpu_profile.py',
           'hybrid_local_cpu_manager.py','hybrid_local_cpu_result.py', 'system_python', 'elf_loader', 'systemd_run', 'libsystemd')
BINDING = obj({'profile': {'const': PROFILE}, 'code_sha256': HASH,
               'purpose': enum('engineering','research'),
               'task_seconds': {'type':'integer','minimum':1,'maximum':300},
               'inputs_sha256': HASH, 'modules_sha256': HASH,
               'command_sha256': HASH, 'resource_sha256': HASH,
               'spec_sha256': HASH, 'grant_id': ID, 'proposal_hash': HASH,
               'approval_hash': HASH, 'config_hash': HASH, 'scope_hash': HASH})


def validate_spec(spec):
    fields={'purpose','code','inputs','limits','seconds'}
    if type(spec) is not dict or set(spec) not in (fields,fields|{'acceptance'}):
        raise Conflict('closed configurable CPU spec required')
    if spec['purpose'] not in ('engineering','research'):
        raise Conflict('explicit CPU task purpose required')
    code = spec['code']
    if type(code) is not str or not 0 < len(code.encode()) <= 32768:
        raise Conflict('bounded frozen CPU code required')
    try: compile(code, '<approved-local-cpu>', 'exec')
    except (SyntaxError, ValueError) as exc: raise Conflict('valid frozen CPU source required') from exc
    inputs = spec['inputs']
    if type(inputs) is not dict or len(inputs)>16:
        raise Conflict('bounded flat private CPU input manifest required')
    for name,value in inputs.items():
        if (type(name) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',name)
                or name in ('.','..') or type(value) is not str):
            raise Conflict('exact flat CPU input names and UTF-8 values required')
    if sum(len(value.encode()) for value in inputs.values())>65536:
        raise Conflict('finite original CPU input size exceeded')
    limits = spec['limits']
    if type(limits) is not dict or set(limits) != {'memory_max','cpu_max','pids_max'}:
        raise Conflict('closed CPU memory/pids/rate limits required')
    for name,low,high in (('memory_max',32*1024**2,512*1024**2),('pids_max',2,32)):
        if type(limits[name]) is not int or not low<=limits[name]<=high:
            raise Conflict('bounded original CPU hard limits required')
    if limits['cpu_max'] != '100000 100000':
        raise Conflict('one-core exact finite CPU rate required')
    if type(spec['seconds']) is not int or not 1<=spec['seconds']<=300:
        raise Conflict('finite original CPU wall limit required')
    if 'acceptance' in spec:
        rule=spec['acceptance']
        if (type(rule) is not dict or set(rule)!={'method','stdout','stderr_empty'} or
                rule['method']!='EXACT_STDOUT_UTF8' or type(rule['stdout']) is not str or
                len(rule['stdout'].encode())>65536 or type(rule['stderr_empty']) is not bool):
            raise Conflict('closed bounded configured CPU acceptance required')
    return deepcopy(spec)


def evaluate_output(spec,outputs):
    """Approved deterministic comparison only; NOT independent product Review."""
    rule=validate_spec(spec).get('acceptance')
    if rule is None:return {'status':'NOT_CONFIGURED','criteria_sha256':None}
    passed=(outputs['stdout']['text']==rule['stdout'] and
            (not rule['stderr_empty'] or outputs['stderr']['text']==''))
    return {'status':'PASS' if passed else 'FAIL','criteria_sha256':digest(rule)}


def module_pins():
    root=Path(__file__).parent
    paths={name:root/name for name in MODULES if name not in ('system_python','elf_loader','systemd_run','libsystemd')}
    paths.update(system_python=Path('/usr/bin/python3').resolve(strict=True),
                 elf_loader=Path('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'),
                 systemd_run=Path('/usr/bin/systemd-run'),libsystemd=Path('/usr/lib/x86_64-linux-gnu/libsystemd.so.0'))
    return {name:'sha256:'+hashlib.sha256(paths[name].read_bytes()).hexdigest() for name in MODULES}


def validate_bound_spec(spec,binding):
    spec=validate_spec(spec)
    if (digest(spec)!=binding['spec_sha256'] or digest(spec['inputs'])!=binding['inputs_sha256'] or
            'sha256:'+hashlib.sha256(spec['code'].encode()).hexdigest()!=binding['code_sha256'] or
            spec['purpose']!=binding['purpose'] or spec['seconds']!=binding['task_seconds']):
        raise Conflict('actual configured CPU spec differs from original approved grant')
    return spec


def registration(spec,pins):
    spec=validate_spec(spec)
    if type(pins) is not dict or set(pins)!=set(MODULES) or any(
            type(value) is not str or not re.fullmatch('sha256:[0-9a-f]{64}',value)
            for value in pins.values()):
        raise Conflict('exact trusted CPU module pins required')
    definition={'profile':PROFILE,'spec':spec,'modules':deepcopy(pins),
                'disk_enforcement':'PARTIAL_NO_HARD_QUOTA','network':'DENIED',
                'model_enabled':False,'gpu_enabled':False}
    return deepcopy({'tool':{'adapter':'original_configured_local_cpu','definition':definition},
        'command':{'tool_id':'local_cpu','argv':[PROFILE],
            'parameter_schema':{'type':'object','properties':{},'additionalProperties':False},
            'network':'none','allowed_hosts':[]},
        'rule':{'definition':definition,'requires_datasets':False},
        'resources':{'local_cpu':definition,'mode':'local_cpu_cgroup',
                     'enforcement':'partial','command_seconds':spec['seconds']}})


def approved_binding(proposal,config,program_sha256):
    try:
        definition=config['tools']['local_cpu']['definition']
        spec=validate_spec(definition['spec']);pins=definition['modules']
        expected=registration(spec,pins)
        if (proposal['goal_kind']!=spec['purpose'] or proposal['risk']!='low' or
                proposal['allowed_tools']!=['local_cpu'] or
                proposal['scope']['allowed_command_templates']!=['local_cpu'] or
                proposal['scope']['network_access']!='none' or proposal['scope']['allowed_hosts']!=[] or
                proposal['evaluation_data']!={'mode':'EXPLICIT_NONE','datasets':[],
                    'evaluation_rule':{'id':'local_cpu_rule','version_hash':digest(expected['rule'])}} or
                config['tools']!={'local_cpu':expected['tool']} or
                config['commands']!={'local_cpu':expected['command']} or
                config['evaluation_rules']!={'local_cpu_rule':expected['rule']} or
                config['resource_profile']!=expected['resources'] or
                program_sha256!=pins['hybrid_local_runner_service.py'] or
                any(proposal['budget'][name]!=0 for name in ('model_sessions','model_input_tokens',
                    'model_output_tokens','gpu_device_seconds','experiment_retries')) or
                proposal['budget']['wall_seconds']<spec['seconds']+10 or
                (spec['purpose']=='engineering' and proposal['budget']['experiment_starts']!=0) or
                (spec['purpose']=='research' and proposal['budget']['experiment_starts']<1)):
            raise Conflict('fresh exact zero-model/GPU configurable CPU approval required')
        return {'profile':PROFILE,'purpose':spec['purpose'],'task_seconds':spec['seconds'],
                'code_sha256':'sha256:'+hashlib.sha256(spec['code'].encode()).hexdigest(),
                'inputs_sha256':digest(spec['inputs']),'modules_sha256':digest(pins),
                'spec_sha256':digest(spec),'command_sha256':digest(expected['command']),
                'resource_sha256':digest(expected['resources'])}
    except (KeyError,TypeError,ValueError) as exc:
        raise Conflict('closed original configurable CPU approval sources required') from exc
