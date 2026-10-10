"""Historical original local result/managed terminal validation, never control."""
import hashlib
import re

from .hybrid_goals import check_bytes,digest
from .hybrid_local_cpu_profile import evaluate_output,evaluate_acceptance
from .store import Conflict
from .hybrid_protocol import obj,ID,HASH,enum,validate_schema

COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
PID={**COUNT,'minimum':1}
BOOL={'type':'boolean'}
TRUE={'type':'boolean','const':True}
FALSE={'type':'boolean','const':False}
HEX={'type':'string','pattern':'^[0-9a-f]{64}$'}
UNIT={'type':'string','pattern':r'^rlflow-local-[0-9a-f]{32}\.service$'}
KEEPER=obj({'pid':PID,'starttime':{'type':'string','pattern':'^[0-9]{1,20}$'},
    'boot_id':{'type':'string','pattern':'^[0-9a-f-]{36}$'},
    'invocation_id':{'type':'string','pattern':'^[0-9a-f]{32}$'}})
TASK=obj({'pid':PID,'starttime':{'type':'string','pattern':'^[0-9]{1,20}$'},
    'source_sha256':HEX,'sandbox':{'const':'CPU_LOCAL_LANDLOCK_SECCOMP'}})
STOPPED=obj({'control_terminal_reason':enum('DEADLINE','PRODUCER_EXIT','CONTROL_EOF','CONTROL_STOP'),
    'cpu_stat':{'type':'string','maxLength':32768},'handoff_unknown':FALSE,
    'keeper_still_live':TRUE,'memory_peak':COUNT,'protocol_cleanup_unknown':FALSE,
    'reaped':{'type':'array','maxItems':32,'items':obj({'pid':PID,'status':COUNT})},
    'release_attempted':BOOL,'stop_latched':TRUE,'task_empty':TRUE,'whole_scope_stopped':FALSE})
TASK_CLOSED=obj({'type':{'const':'local_cpu.task_closed'},'config_sha256':HEX,'keeper':KEEPER,
    'original_control_fd_closed':TRUE,'original_output_fds_closed':TRUE,'stopped':STOPPED,
    'closed':obj({'keeper_protocol_handles_closed':TRUE,'stop_latched':TRUE,
        'task_handles_closed':TRUE,'whole_scope_stopped':FALSE}),
    'task':TASK,'whole_scope_stopped':FALSE})
MANAGER=obj({'ActiveState':enum('inactive','failed'),'SubState':enum('dead','failed'),
    'ExecMainCode':COUNT,'ExecMainPID':PID,'ExecMainStatus':COUNT,
    'InvocationID':{'type':'string','pattern':'^[0-9a-f]{32}$'},
    'KillMode':{'const':'control-group'},'MainPID':{'type':'integer','const':0},
    'Result':{'type':'string','maxLength':80},'SendSIGKILL':{'type':'integer','const':1},
    'TimeoutStopUSec':{'type':'integer','const':2_000_000}})
MANAGED=obj({'job':obj({'id':PID,'path':{'type':'string','pattern':r'^/org/freedesktop/systemd1/job/[0-9]+$'},
    'result':{'const':'done'},'unit':UNIT}),'keeper':KEEPER,'manager':MANAGER,
    'original_manager_scope_processes':{'type':'array','maxItems':0},'unit':UNIT,
    'unit_reference_held':TRUE,'keeper_kernel_terminal':TRUE,'transport_reaped':TRUE,
    'transport_status':{'type':'integer','minimum':-2**31,'maximum':2**31-1},
    'original_protocol_closed':TRUE,'original_manager_connection_closed':TRUE,'task_closed':TASK_CLOSED})
ACCEPTANCE={'oneOf':[obj({'method':{'const':'EXACT_STDOUT_UTF8'},
    'stdout':{'type':'string','maxLength':65536},'stderr_empty':BOOL}),
    obj({'method':{'const':'JSON_METRICS_RANGE'},'stderr_empty':BOOL,
        'metrics':{'type':'object','minProperties':1,'maxProperties':16,
            'propertyNames':{'pattern':'^[A-Za-z][A-Za-z0-9_]{0,79}$'},
            'additionalProperties':obj({'min':{'type':'number'},'max':{'type':'number'}})}})]}
OUTPUT=obj({'text':{'type':'string','maxLength':65536},'sha256':HASH})
RESULT=obj({'lease_id':ID,'source_id':ID,'task':TASK,'outputs':obj({'stdout':OUTPUT,'stderr':OUTPUT}),
    'machine_acceptance':obj({'criteria_sha256':{'oneOf':[HASH,{'type':'null'}]},
        'status':enum('PASS','FAIL','NOT_CONFIGURED')}),
    'approved_spec_sha256':HASH,'approved_acceptance':{'oneOf':[ACCEPTANCE,{'type':'null'}]},
    'independent_review_status':{'const':'NOT_PROVEN'},'condition_evidence':FALSE})


def validate_result(value,origin,task,stopped,spec=None):
    check_bytes(value,128*1024)
    validate_schema(RESULT,value)
    if (type(value) is not dict or set(value)!={'lease_id','source_id','task','outputs',
            'machine_acceptance','approved_spec_sha256','approved_acceptance',
            'independent_review_status','condition_evidence'} or
            value['lease_id']!=origin['lease_id'] or value['task']!=task or
            value['approved_spec_sha256']!=origin['local_cpu']['spec_sha256'] or
            value['independent_review_status']!='NOT_PROVEN' or value['condition_evidence'] is not False or
            task['source_sha256']!=origin['local_cpu']['code_sha256'].removeprefix('sha256:') or
            not any(item['pid']==task['pid'] and type(item['status']) is int and item['status']==0
                    for item in stopped['reaped'])):
        raise Conflict('original configured CPU result identity/exit differs')
    validate_schema(ID,value['source_id'])
    outputs=value['outputs']
    if type(outputs) is not dict or set(outputs)!={'stdout','stderr'}:
        raise Conflict('closed original configured CPU outputs required')
    for output in outputs.values():
        if (type(output) is not dict or set(output)!={'text','sha256'} or type(output['text']) is not str or
                len(output['text'].encode())>65536 or
                output['sha256']!='sha256:'+hashlib.sha256(output['text'].encode()).hexdigest()):
            raise Conflict('original configured CPU output hash differs')
    rule=value['approved_acceptance']
    expected=evaluate_acceptance(rule,outputs)
    if value['machine_acceptance']!=expected:raise Conflict('configured CPU machine result differs from raw output')
    if spec is not None:
        if (digest(spec)!=value['approved_spec_sha256'] or
                value['approved_acceptance']!=spec.get('acceptance') or
                value['machine_acceptance']!=evaluate_output(spec,outputs)):
            raise Conflict('original approved configured CPU acceptance differs')


def validate_terminal(proof,runtime):
    check_bytes(proof,224*1024)
    from .hybrid_fixture_runtime_ledger import PROCESS,nullable
    validate_schema(obj({'scope':{'const':'ORIGINAL_CONFIGURED_CPU_SERVICE'},'lease_id':ID,
        'program_sha256':HASH,'producer':nullable(PROCESS),'all_original_source_fds_closed':TRUE,
        'original_participant_reaped':TRUE,'managed_service_proof':nullable(MANAGED),
        'configured_local_result':nullable(RESULT),'local_cpu_release_attempted':BOOL,
        'disk_enforcement':{'const':'PARTIAL_NO_HARD_QUOTA'},'arbitrary_tree_stop':FALSE,
        'wall_seconds':COUNT,'synthetic_tokens_settled':FALSE}),proof)
    origin=runtime['origin']
    if (type(proof) is not dict or set(proof)!={'scope','lease_id','program_sha256','producer',
            'all_original_source_fds_closed','original_participant_reaped','managed_service_proof',
            'configured_local_result','local_cpu_release_attempted','disk_enforcement',
            'arbitrary_tree_stop','wall_seconds','synthetic_tokens_settled'} or
            proof['scope']!='ORIGINAL_CONFIGURED_CPU_SERVICE' or proof['lease_id']!=origin['lease_id'] or
            proof['program_sha256']!=origin['program_sha256'] or proof['producer']!=runtime['producer'] or
            proof['local_cpu_release_attempted'] is not runtime['local_cpu_release_attempted'] or
            proof['wall_seconds']!=runtime['wall_seconds'] or
            proof['all_original_source_fds_closed'] is not True or proof['original_participant_reaped'] is not True or
            proof['arbitrary_tree_stop'] is not False or proof['synthetic_tokens_settled'] is not False or
            proof['disk_enforcement']!='PARTIAL_NO_HARD_QUOTA' or digest(proof)!=runtime['terminal_proof_sha256']):
        raise Conflict('original configured CPU durable terminal differs')
    managed=proof['managed_service_proof'];result=proof['configured_local_result']
    if runtime['producer'] is None:
        if managed is not None or result is not None or runtime['local_cpu_release_attempted'] or runtime['wall_seconds']:
            raise Conflict('no-handoff configured CPU cannot supply execution result')
        return
    if type(managed) is not dict:
        raise Conflict('original configured CPU managed terminal required')
    validate_schema(MANAGED,managed)
    try:
        keeper=managed['keeper'];manager=managed['manager'];closed=managed['task_closed']
        if (not re.fullmatch(r'rlflow-local-[0-9a-f]{32}\.service',managed['unit']) or
                managed['job']['unit']!=managed['unit'] or managed['job']['result']!='done' or
                keeper!=closed['keeper'] or
                any(keeper[key]!=runtime['producer'][key] for key in ('pid','starttime','boot_id')) or
                manager['InvocationID']!=keeper['invocation_id'] or manager['ExecMainPID']!=keeper['pid'] or
                manager['MainPID']!=0 or (manager['ActiveState'],manager['SubState']) not in
                    (('inactive','dead'),('failed','failed')) or manager['KillMode']!='control-group' or
                manager['SendSIGKILL']!=1 or manager['TimeoutStopUSec']!=2_000_000 or
                managed['original_manager_scope_processes']!=[] or
                any(managed[key] is not True for key in ('unit_reference_held','keeper_kernel_terminal',
                    'transport_reaped','original_protocol_closed','original_manager_connection_closed')) or
                closed['type']!='local_cpu.task_closed' or
                any(closed[key] is not True for key in ('original_control_fd_closed','original_output_fds_closed')) or
                any(closed['closed'][key] is not True for key in
                    ('keeper_protocol_handles_closed','stop_latched','task_handles_closed')) or
                closed['stopped']['task_empty'] is not True or closed['stopped']['handoff_unknown'] is not False or
                closed['stopped']['protocol_cleanup_unknown'] is not False or
                closed['stopped']['release_attempted'] is not runtime['local_cpu_release_attempted']):
            raise Conflict('original configured CPU managed closure differs')
        if result is not None:
            if not runtime['local_cpu_release_attempted']:raise Conflict('configured CPU result before G refused')
            validate_result(result,origin,closed['task'],closed['stopped'])
    except (KeyError,TypeError) as exc:
        raise Conflict('closed original configured CPU managed proof required') from exc
