"""Project-local static metadata, never trusted runtime/control configuration."""
from pathlib import Path
import yaml
from .hybrid_protocol import ID, TEXT, obj, array, enum, nullable, validate_schema

BOOL={'type':'boolean'}
POSITIVE={'type':'integer','minimum':1,'maximum':2**31-1}
NONNEGATIVE={'type':'integer','minimum':0,'maximum':2**31-1}
PATHS={**array(TEXT,128),'uniqueItems':True}
FULL=obj({'schema_version':{'const':'1.0'},'execution_enabled':BOOL,
    'data_mode':enum('fixture','live'),
    'project':obj({'id':ID,'root':TEXT,'state_dir':TEXT,'source_roots':PATHS,
        'data_roots':PATHS,'artifact_root':TEXT,'protected_paths':PATHS}),
    'runtime':obj({'adapter':ID,'approved_real_adapter':nullable(ID),'pinned_version':TEXT,
        'native_subagents':BOOL,'max_delegation_depth':NONNEGATIVE,'require_enforced_readonly':BOOL}),
    'models':obj({name:nullable(ID) for name in ('fast_reader','standard_worker','deep_reviewer')}),
    'limits':obj({'host_model_sessions_including_children':POSITIVE,'writers_per_workspace':POSITIVE,
        'gpu_experiments_concurrent':NONNEGATIVE,'automatic_expensive_retries':NONNEGATIVE,
        'control_rss_target_mib':POSITIVE,'require_cgroup_for_strict_tasks':BOOL}),
    'policy':obj({'repeated_failure_trigger_count':POSITIVE,'same_task_same_cause_escalations':NONNEGATIVE,
        'finalization_reserve_fraction':{'type':'number','minimum':0,'maximum':1},
        'independent_review_before_delivery':BOOL,'allow_lightweight_decision_service':BOOL}),
    'commands':{'type':'object','maxProperties':128,'propertyNames':ID,'additionalProperties':obj({
        'adapter':ID,'template_id':ID,'parameters':{'type':'object'},'network':enum('none','allowlist')})},
    'dashboard':obj({'bind':enum('127.0.0.1','::1'),'port':{'type':'integer','minimum':1,'maximum':65535},
        'auth_required':{'const':True},'timezone':TEXT,'sse_heartbeat_seconds':POSITIVE,
        'stale_after_seconds':POSITIVE,'max_animation_fps':POSITIVE,
        'max_visible_graph_nodes':POSITIVE,'max_active_pulses':POSITIVE}),
    'retention':obj({'raw_log_days':NONNEGATIVE,'telemetry_days':NONNEGATIVE,
        'downsampled_metric_days':NONNEGATIVE,'protect_referenced_evidence':BOOL})})
FLAT=obj({'schema_version':{'const':'1.0'},'project_id':ID,'control_origin':TEXT})


def parse(raw, cwd):
    """Reject aliases, nested duplicates and implicit credentials before use."""
    class ClosedLoader(yaml.SafeLoader): pass
    def mapping(loader,node,deep=False):
        value={}
        for key_node,value_node in node.value:
            key=loader.construct_object(key_node,deep=deep)
            if type(key) is not str or key in value:raise ValueError('closed unique string keys required')
            value[key]=loader.construct_object(value_node,deep=deep)
        return value
    ClosedLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
    count=depth=0
    for event in yaml.parse(raw):
        count+=1
        if isinstance(event,(yaml.events.MappingStartEvent,yaml.events.SequenceStartEvent)):depth+=1
        if isinstance(event,(yaml.events.MappingEndEvent,yaml.events.SequenceEndEvent)):depth-=1
        if count>32768 or depth>32 or isinstance(event,yaml.events.AliasEvent) or getattr(event,'anchor',None) is not None:
            raise ValueError('bounded alias-free project configuration required')
    data=yaml.load(raw,Loader=ClosedLoader)
    if type(data) is not dict:raise ValueError('closed project configuration required')
    def no_credentials(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in {'authorization','password','passphrase','credentials','credential','request_token',
                    'api_key','access_token','secret','csrf_token','salt','digest'}:
                    raise ValueError('project configuration cannot contain credentials')
                no_credentials(item)
        elif isinstance(value,list):
            for item in value:no_credentials(item)
    no_credentials(data)
    if 'project_id' in data:
        validate_schema(FLAT,data)
        return data['project_id'],data['control_origin'],None
    validate_schema(FULL,data)
    project=data['project'];root=Path(project['root'])
    if not root.is_absolute() or root.resolve(strict=True)!=Path(cwd).resolve(strict=True):
        raise ValueError('canonical registered target root required')
    state=Path(project['state_dir'])
    if not state.is_absolute() or state.resolve().is_relative_to(root.resolve(strict=True)):
        raise ValueError('state must remain outside project workspace')
    for key in ('root','state_dir','artifact_root'):
        if not project[key] or 'SET_ME' in project[key] or '\x00' in project[key]:
            raise ValueError('explicit completed project paths required')
    for key in ('source_roots','protected_paths'):
        for name in project[key]:
            path=Path(name)
            if not name or path.is_absolute() or '..' in path.parts or '\x00' in name:
                raise ValueError('relative contained source/protected paths required')
    for name in project['data_roots']:
        if not name or 'SET_ME' in name or '\x00' in name or not Path(name).is_absolute():
            raise ValueError('explicit absolute data roots required')
    dashboard=data['dashboard'];host='[::1]' if dashboard['bind']=='::1' else dashboard['bind']
    return project['id'],f'http://{host}:{dashboard["port"]}',data['data_mode']
