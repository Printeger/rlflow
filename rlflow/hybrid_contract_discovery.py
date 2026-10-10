"""Read-only projection of the original registered proposal contract."""
import json
from copy import deepcopy
from .hybrid_goals import digest
from .hybrid_protocol import ID, HASH, TEXT, obj, array, enum, validate_schema, schemas, ProtocolError
from .hybrid_registry import catalog_map
from .store import Conflict, canonical
from .hybrid_control import ControlError

MAX_BYTES=512*1024
STRINGS={**array(TEXT,128),'uniqueItems':True}
BINDINGS=obj({name:HASH for name in ('tool_registry_hash','command_registry_hash',
    'runtime_profile_hash','resource_profile_hash','dataset_registry_hash')})
PUBLIC=obj({'schema_version':{'const':'1.0'},'profile':{'const':'ORIGINAL_REGISTERED_PROPOSAL_CONTRACT'},
    'project_id':ID,'data_mode':enum('fixture','live'),'store_epoch':ID,
    'execution_enabled':{'const':False},'authority':{'const':'NOT_AUTHORITY'},
    'config_hash':HASH,'registry_bindings':BINDINGS,
    'tools':catalog_map(obj({'adapter':ID})),
    'commands':catalog_map(obj({'tool_id':ID,'parameter_schema':{'type':'object'},
        'network':enum('none','allowlist'),'allowed_hosts':STRINGS})),
    'datasets':catalog_map(obj({'version_hash':HASH,'purposes':{**array(enum('training','validation','evaluation','reference'),4),
        'uniqueItems':True,'minItems':1},'access':enum('READ_ONLY','PROTECTED_EVALUATOR_ONLY')})),
    'evaluation_rules':catalog_map(obj({'version_hash':HASH,'requires_datasets':{'type':'boolean'}})),
    'network_policy':obj({'network_access':enum('none','allowlist'),'allowed_hosts':STRINGS}),
    'goal_proposal_schema':{'type':'object'},'goal_proposal_schema_hash':HASH})


def public_parameter_schema(value,depth=0):
    """Exact safe structural subset; no annotations, literals, refs or rewrites.

    Arbitrary registry metadata can contain private examples/defaults or remote
    refs. Unsupported schema is refused, not fetched or silently redacted into
    a different execution contract. This endpoint never validates parameters.
    """
    from jsonschema import Draft202012Validator, SchemaError
    if depth==0:
        try:Draft202012Validator.check_schema(value)
        except (SchemaError,RecursionError):raise ProtocolError('valid public parameter schema required') from None
    keywords={'type','properties','required','additionalProperties','items','minItems','maxItems',
              'minimum','maximum','minLength','maxLength','uniqueItems'}
    if (depth>16 or type(value) is not dict or set(value)-keywords or
            value.get('type') not in ('object','array','string','integer','number','boolean','null')):
        raise ProtocolError('parameter schema not safe for public discovery')
    for key,item in value.items():
        if key=='properties':
            if type(item) is not dict or len(item)>128:raise ProtocolError('bounded public properties required')
            for name,child in item.items():
                validate_schema(ID,name);public_parameter_schema(child,depth+1)
        elif key=='items':public_parameter_schema(item,depth+1)
        elif key=='required':validate_schema({**array(ID,128),'uniqueItems':True},item)
        elif key in ('additionalProperties','uniqueItems'):
            if type(item) is not bool:raise ProtocolError('public boolean schema bound required')
        elif key!='type':
            if type(item) not in (int,float):raise ProtocolError('public numeric schema bound required')
    return value


def validate_public(value,project_id,data_mode=None):
    validate_schema(PUBLIC,value)
    if value['project_id']!=project_id or data_mode is not None and value['data_mode']!=data_mode:
        raise ProtocolError('original project discovery scope differs')
    schema=schemas()['goal_v1_1']
    if value['goal_proposal_schema']!=schema or value['goal_proposal_schema_hash']!=digest(schema):
        raise ProtocolError('installed original proposal schema required')
    if value['network_policy']['network_access']=='none' and value['network_policy']['allowed_hosts']:
        raise ProtocolError('network-disabled project cannot name hosts')
    for command in value['commands'].values():
        public_parameter_schema(command['parameter_schema'])
        if command['tool_id'] not in value['tools'] or command['network']=='none' and command['allowed_hosts']:
            raise ProtocolError('closed registered command required')
    for dataset in value['datasets'].values():
        if dataset['access']=='PROTECTED_EVALUATOR_ONLY' and 'training' in dataset['purposes']:
            raise ProtocolError('protected dataset cannot grant training')
    return value


class ContractDiscovery:
    def __init__(self,inbox,pair):
        self.inbox,self.pair=inbox,pair
        self.registry=pair.approvals.registry
        self.raw=self.registry._raw
        self.binding=(inbox,pair,pair.drafts,pair.approvals,self.registry,self.raw,
            inbox.store,inbox.auth,inbox.project_id,inbox.data_mode,inbox.store_epoch,inbox.origin)
        self.pure()

    def pure(self):
        inbox=self.inbox
        inbox._identity()  # Parent first; no inbox file health or write access.
        approval=self.pair.approvals
        if (self.binding!=(inbox,self.pair,self.pair.drafts,approval,self.registry,self.registry._raw,
                inbox.store,inbox.auth,inbox.project_id,inbox.data_mode,inbox.store_epoch,inbox.origin) or
                self.raw != self.binding[5] or self.raw != self.registry._raw or
                self.pair.drafts is not inbox.drafts or
                (approval.store,approval.auth,approval.project_id,approval.data_mode,approval.origin)!=
                (inbox.store,inbox.auth,inbox.project_id,inbox.data_mode,inbox.origin) or
                inbox.store._hybrid_authority_service is not approval or
                inbox.store._hybrid_auth_owner is not inbox.auth or
                approval.registry is not self.registry or inbox.store._hybrid_registry is not self.registry):
            raise Conflict('original discovery registration changed')
        with inbox.store.read_connection() as db:
            row=db.execute('SELECT project_id,data_mode,store_epoch FROM observation_meta WHERE singleton=1').fetchone()
        if row is None or tuple(row)!=(inbox.project_id,inbox.data_mode,inbox.store_epoch):
            raise Conflict('original discovery epoch changed')

    def read(self,*,token,method):
        self.pure();inbox=self.inbox;inbox._authorize(token,method)
        config=json.loads(self.raw)
        if (config['project_id'],config['data_mode'])!=(inbox.project_id,inbox.data_mode):
            raise Conflict('original discovery catalog scope changed')
        try:
            commands={name:{k:c[k] for k in ('tool_id','parameter_schema','network','allowed_hosts')}
                      for name,c in config['commands'].items()}
            for command in commands.values():public_parameter_schema(command['parameter_schema'])
        except ProtocolError:
            raise ControlError(409,'UNSUPPORTED_CAPABILITY','registered parameter schema is not discovery-safe') from None
        schema=deepcopy(schemas()['goal_v1_1'])
        value={'schema_version':'1.0','profile':'ORIGINAL_REGISTERED_PROPOSAL_CONTRACT',
            'project_id':inbox.project_id,'data_mode':inbox.data_mode,'store_epoch':inbox.store_epoch,
            'execution_enabled':False,'authority':'NOT_AUTHORITY','config_hash':self.registry.config_hash,
            'registry_bindings':self.registry.bindings,'tools':{name:{'adapter':t['adapter']} for name,t in config['tools'].items()},
            'commands':commands,'datasets':{name:{k:d[k] for k in ('version_hash','purposes','access')} for name,d in config['datasets'].items()},
            'evaluation_rules':{name:{'version_hash':digest(r),'requires_datasets':r['requires_datasets']} for name,r in config['evaluation_rules'].items()},
            'network_policy':{k:config['project_policy'][k] for k in ('network_access','allowed_hosts')},
            'goal_proposal_schema':schema,'goal_proposal_schema_hash':digest(schema)}
        if len(canonical(value))>MAX_BYTES:raise Conflict('bounded contract discovery required')
        validate_public(value,inbox.project_id,inbox.data_mode)
        self.pure();inbox._authorize(token,method)
        return value
