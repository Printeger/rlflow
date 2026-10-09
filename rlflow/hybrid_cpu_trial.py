"""One fixed, model-free numerical trial; never an arbitrary CPU executor.

The owner supplies original approval/capability/FD provenance. Pure helpers here
check the pinned grant and independently evaluate raw coordinates. compatible_cpu
is explicitly partial, not cgroup/network/descendant enforcement or Goal success.
"""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import math

from .hybrid_goals import digest
from .hybrid_protocol import ID, HASH, obj
from .hybrid_usage_stream import parse_line
from .store import Conflict, canonical

PROFILE = 'FIXED_CPU_PI_TRIAL_V1'
KIND = 'LOCAL_CPU_NUMERICAL_TRIAL'
AUTHORIZATION = 'LOCAL_CPU_TRIAL_ONLY'
SPEC = {'generator': 'LCG32_TOP16_V1', 'seeds': [7, 11, 19], 'samples_per_seed': 128,
        'coordinate_denominator': 65536, 'baseline': 3, 'reference': 'math.pi',
        'comparison': 'MEAN_ABSOLUTE_ERROR', 'hypothesis': 'estimator_error_below_baseline'}
LIMITS = {'mode': 'compatible_cpu', 'enforcement': 'partial', 'cpu_seconds': 2,
          'address_space_bytes': 128*1024**2, 'output_bytes': 1024**2,
          'network_enforcement': 'NOT_PROVED', 'tree_enforcement': 'NOT_PROVED',
          'fixed_program_no_network_or_descendants': True}
BINDING = obj({'profile': {'const': PROFILE}, 'spec_sha256': HASH, 'input_sha256': HASH,
               'evaluator_sha256': HASH, 'command_sha256': HASH, 'resource_sha256': HASH,
               'grant_id': ID, 'proposal_hash': HASH, 'approval_hash': HASH,
               'config_hash': HASH, 'scope_hash': HASH})


def validate_result(value, origin, producer):
    """Historical content check; the live writer separately proves original cap."""
    if type(value) is not dict:
        raise Conflict('closed original CPU trial result required')
    try:
        rows = inputs(); counts = [sum(x*x+y*y < 65536**2 for x, y in r['points']) for r in rows]
        estimates = [4*n/SPEC['samples_per_seed'] for n in counts]
        error = math.fsum(abs(v-math.pi) for v in estimates)/len(estimates)
        if type(producer) is not dict: raise Conflict('CPU trial original result producer required')
        events = [{'type':'runtime.started','nonce':origin['nonce'],'pid':producer['pid'],'program':PROFILE}]
        for row in rows:
            events.extend({'type':'cpu.trial.sample','seed':row['seed'],'index':i,'x':x,'y':y,
                           'inside':x*x+y*y < 65536**2} for i,(x,y) in enumerate(row['points']))
        events.extend([{'type':'cpu.trial.completed','inside_counts':counts,
                        'cpu_ns':value['cpu_ns'],'wall_ns':value['worker_wall_ns']}, {'type':'fixture.end'}])
        source_sha256 = 'sha256:'+hashlib.sha256(b''.join(canonical(e)+b'\n' for e in events)).hexdigest()
        expected = {'profile': PROFILE, 'verification': 'RAW_VALUES_VERIFIED',
            'evidence_activation': 'AUDIT_ONLY', 'goal_completed': False,
            'raw_samples': rows, 'input_sha256': digest(rows), 'inside_counts': counts,
            'estimates': estimates, 'mean_absolute_error': error, 'baseline': SPEC['baseline'],
            'baseline_absolute_error': abs(SPEC['baseline']-math.pi),
            'hypothesis_supported': error < abs(SPEC['baseline']-math.pi),
            'cpu_ns': value['cpu_ns'], 'worker_wall_ns': value['worker_wall_ns'],
            'cpu_measurement_scope': 'ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT',
            'resource_enforcement': 'partial', 'actual_cost_status': 'UNKNOWN',
            'model_enabled': False, 'gpu_enabled': False, 'source_sha256': source_sha256,
            'producer': producer,
            'source_id': value['source_id'], 'lease_id': origin['lease_id'],
            'task_id': origin['task_id'], 'attempt_id': origin['attempt_id'],
            'grant_id': origin['cpu_trial']['grant_id'], 'program_sha256': origin['program_sha256'],
            'evaluator_sha256': origin['cpu_trial']['evaluator_sha256']}
        if canonical(value) != canonical(expected): raise Conflict('CPU trial original result content differs')
        from .hybrid_protocol import validate_schema
        validate_schema(HASH, value['source_sha256']); validate_schema(ID, value['source_id'])
        if any(type(value[k]) is not int or not 0 <= value[k] <= 3*10**9 for k in ('cpu_ns','worker_wall_ns')):
            raise Conflict('finite CPU trial measurement required')
    except (KeyError, TypeError, ValueError):
        raise Conflict('closed original CPU trial result required') from None


@dataclass(frozen=True, eq=False)
class CpuTrialGrant:
    id: str
    raw: bytes


@dataclass(frozen=True, eq=False)
class CpuTrialResult:
    raw: bytes


def inputs():
    rows = []
    for seed in SPEC['seeds']:
        state = seed; points = []
        for _ in range(SPEC['samples_per_seed']):
            state = (1664525*state + 1013904223) & 0xffffffff; x = state >> 16
            state = (1664525*state + 1013904223) & 0xffffffff; y = state >> 16
            points.append([x, y])
        rows.append({'seed': seed, 'points': points})
    return rows


def registration(program_sha256, evaluator_sha256):
    """Exact protected catalog entries; registering them is NOT approval."""
    definition = {'profile': PROFILE, 'program_sha256': program_sha256,
                  'evaluator_sha256': evaluator_sha256, 'spec_sha256': digest(SPEC),
                  'input_sha256': digest(inputs()), 'limits': LIMITS}
    return deepcopy({'tool': {'adapter': 'fixed_cpu_trial', 'definition': definition},
            'command': {'tool_id': 'cpu_trial', 'argv': [PROFILE],
                        'parameter_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                        'network': 'none', 'allowed_hosts': []},
            'rule': {'definition': definition, 'requires_datasets': False},
            'resources': {'fixed_cpu_trial': definition, **LIMITS}})


def approved_binding(proposal, config, program_sha256, evaluator_sha256):
    expected = registration(program_sha256, evaluator_sha256)
    if (proposal['goal_kind'] != 'research' or proposal['risk'] != 'low' or
            proposal['allowed_tools'] != ['cpu_trial'] or
            proposal['scope']['allowed_command_templates'] != ['cpu_trial'] or
            proposal['scope']['network_access'] != 'none' or proposal['scope']['allowed_hosts'] or
            proposal['evaluation_data'] != {'mode': 'EXPLICIT_NONE', 'datasets': [],
                'evaluation_rule': {'id': 'cpu_trial_rule', 'version_hash': digest(expected['rule'])}} or
            config['tools'].get('cpu_trial') != expected['tool'] or
            config['commands'].get('cpu_trial') != expected['command'] or
            config['evaluation_rules'].get('cpu_trial_rule') != expected['rule'] or
            config['resource_profile'] != expected['resources'] or
            any(proposal['budget'][name] != 0 for name in
                ('model_sessions', 'model_input_tokens', 'model_output_tokens', 'gpu_device_seconds', 'experiment_retries')) or
            proposal['budget']['experiment_starts'] < 1):
        raise Conflict('exact approved fixed CPU trial profile, rule and partial limits required')
    return {'profile': PROFILE, 'spec_sha256': digest(SPEC), 'input_sha256': digest(inputs()),
            'evaluator_sha256': evaluator_sha256, 'command_sha256': digest(expected['command']),
            'resource_sha256': digest(expected['resources'])}


def evaluate(raw, *, nonce, pid):
    """Independently verify the complete original sealed stream, <=64KiB."""
    if type(raw) is not bytes or len(raw) > 65536 or not raw.endswith(b'\n'):
        raise Conflict('complete bounded original CPU trial source required')
    events = [parse_line(line) for line in raw.splitlines(keepends=True)]
    rows = inputs(); count = len(rows)*SPEC['samples_per_seed']
    if (len(events) != count+3 or events[0] != {'type': 'runtime.started', 'nonce': nonce,
            'pid': pid, 'program': PROFILE} or events[-1] != {'type': 'fixture.end'}):
        raise Conflict('original CPU trial ACK/end or finite sample count differs')
    counts = []; cursor = 1
    for row in rows:
        inside = 0
        for index, (x, y) in enumerate(row['points']):
            hit = x*x+y*y < 65536**2
            expected = {'type': 'cpu.trial.sample', 'seed': row['seed'], 'index': index,
                        'x': x, 'y': y, 'inside': hit}
            actual = events[cursor]; cursor += 1
            if canonical(actual) != canonical(expected):
                raise Conflict('CPU trial raw sample differs from pinned actual input')
            inside += hit
        counts.append(inside)
    reported = events[-2]
    if (set(reported) != {'type', 'inside_counts', 'cpu_ns', 'wall_ns'} or
            reported['type'] != 'cpu.trial.completed' or canonical(reported['inside_counts']) != canonical(counts) or
            any(type(reported[key]) is not int or not 0 <= reported[key] <= 3*10**9
                for key in ('cpu_ns', 'wall_ns'))):
        raise Conflict('CPU trial measured completion differs from independent raw evaluation')
    estimates = [4*n/SPEC['samples_per_seed'] for n in counts]
    error = math.fsum(abs(v-math.pi) for v in estimates)/len(estimates)
    baseline_error = abs(SPEC['baseline']-math.pi)
    return {'profile': PROFILE, 'verification': 'RAW_VALUES_VERIFIED',
            'evidence_activation': 'AUDIT_ONLY', 'goal_completed': False,
            'raw_samples': rows, 'input_sha256': digest(rows), 'inside_counts': counts,
            'estimates': estimates, 'mean_absolute_error': error, 'baseline': SPEC['baseline'],
            'baseline_absolute_error': baseline_error, 'hypothesis_supported': error < baseline_error,
            'cpu_ns': reported['cpu_ns'], 'worker_wall_ns': reported['wall_ns'],
            'cpu_measurement_scope': 'ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT',
            'resource_enforcement': 'partial', 'actual_cost_status': 'UNKNOWN',
            'model_enabled': False, 'gpu_enabled': False,
            'source_sha256': 'sha256:'+hashlib.sha256(raw).hexdigest()}
