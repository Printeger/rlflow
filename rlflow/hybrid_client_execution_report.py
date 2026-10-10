"""Original delivery source -> bounded non-authoritative client report."""
from .hybrid_protocol import ID,HASH,TEXT,TIME,obj,array,enum,nullable,validate_schema,ProtocolError
from .hybrid_delivery_evidence import DeliveryEvidenceReader
from .hybrid_control import ControlError
from .store import Conflict,canonical

COUNT={'type':'integer','minimum':0,'maximum':2**63-1}
FALSE={'const':False}
BLOCKERS=enum('MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW',
    'CURRENT_CONTRACT_DIFFERS','CURRENT_CONSENT_UNAVAILABLE','RESULT_HISTORICAL_ONLY')
PUBLIC=obj({'schema_version':{'const':'1.0'},'profile':{'const':'ORIGINAL_DELIVERY_CLIENT_REPORT'},
    'project_id':ID,'data_mode':{'const':'fixture'},'store_epoch':{'type':'string','pattern':'^store_[0-9a-f]{32}$'},
    'authority':{'const':'NOT_AUTHORITY'},'execution_enabled':FALSE,'as_of_state_version':COUNT,
    'goal_ref':ID,'contract_revision':{'type':'integer','minimum':1},'proposal_sha256':HASH,
    'source_coverage':{'const':'ORIGINAL_RESULT_AND_CURRENT_CONTRACT_VERIFIED'},
    'result_activation':enum('CURRENT_SOURCE_AS_OF','HISTORICAL_ONLY'),
    'consent_status':enum('CURRENT_AS_OF','UNAVAILABLE_AS_OF'),'checked_at':{**TIME,'pattern':'Z$'},
    'source':obj({'kind':enum('CPU_TRIAL','ENGINEERING'),'id':ID,'sha256':HASH,
        'result_sha256':nullable(HASH),'configuration_sha256':HASH,'original_proposal_sha256':HASH,
        'recorded_state_version':COUNT,'raw_item_count':COUNT,'machine_case_count':COUNT,
        'machine_status':TEXT,'evidence_role':{'const':'UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE'}}),
    'conditions':{**array(obj({'id':ID,'required':{'type':'boolean'},'verification_sha256':HASH,
        'status':{'const':'UNASSESSED'}}),200),'minItems':1},
    'required_count':{**COUNT,'minimum':1},'required_satisfied_count':{'const':0},
    'finalization_status':{'const':'BLOCKED_MISSING_EVIDENCE'},'blockers':{**array(BLOCKERS,5),'uniqueItems':True},
    'independent_review_status':{'const':'NOT_PERFORMED'},'goal_completed':FALSE,
    'dispatch_enabled':FALSE,'model_call_enabled':FALSE,'condition_evidence_write_enabled':FALSE,
    'current_execution_status':{'const':'UNKNOWN'},'resource_release_status':{'const':'NOT_OBSERVED'}})


def validate_public(value,project,kind,key,mode=None):
    validate_schema(PUBLIC,value)
    source=value['source']
    prefix='cpu_assessment_' if kind=='CPU_TRIAL' else 'candidate_output_result_'
    if (value['project_id']!=project or mode not in (None,'fixture') or
            (source['kind'],source['id'])!=(kind,key) or not key.startswith(prefix) or
            source['recorded_state_version']>value['as_of_state_version'] or
            kind=='ENGINEERING' and source['result_sha256'] is None or
            value['required_count']!=sum(c['required'] for c in value['conditions']) or
            not {'MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW'}<=set(value['blockers']) or
            len({c['id'] for c in value['conditions']})!=len(value['conditions'])):
        raise ProtocolError('original non-authoritative client report required')
    blockers=set(value['blockers'])
    same=value['proposal_sha256']==source['original_proposal_sha256']
    active=value['result_activation']=='CURRENT_SOURCE_AS_OF'
    consent=value['consent_status']=='CURRENT_AS_OF'
    status=source['machine_status'];cases=source['machine_case_count']
    if ((not same)!=('CURRENT_CONTRACT_DIFFERS' in blockers) or
            (not active)!=('RESULT_HISTORICAL_ONLY' in blockers) or
            (not consent)!=('CURRENT_CONSENT_UNAVAILABLE' in blockers) or
            active and not (same and consent) or
            kind=='CPU_TRIAL' and (status not in ('NOT_RECORDED','UNAVAILABLE','MACHINE_VERIFIED') or cases!=0) or
            kind=='ENGINEERING' and (status not in ('NOT_RECORDED','MACHINE_ACCEPTED_PENDING_REVIEW') or
                cases!=(21 if status=='MACHINE_ACCEPTED_PENDING_REVIEW' else 0))):
        raise ProtocolError('consistent original delivery snapshot required')
    return value


class ExecutionReport:
    def __init__(self,discovery,reader):
        if type(reader) is not DeliveryEvidenceReader:raise TypeError('original delivery reader required')
        self.discovery,self.reader=discovery,reader
        self.binding=(discovery,reader,reader.source,reader.kind,reader.project_id,reader.store_epoch)
        self.pure()

    def pure(self):
        discovery=self.discovery;discovery.pure();reader=self.reader;inbox=discovery.inbox
        if (self.binding!=(discovery,reader,reader.source,reader.kind,reader.project_id,reader.store_epoch) or
                reader.store is not inbox.store or reader.source.registry is not discovery.registry or
                (reader.project_id,reader.data_mode,reader.store_epoch)!=(inbox.project_id,inbox.data_mode,inbox.store_epoch)):
            raise Conflict('original client report registration changed')
        reader._original()

    def read(self,key,*,token,method):
        validate_schema(ID,key);self.pure();inbox=self.discovery.inbox
        inbox._authorize(token,method)
        result=read_public(self.reader,key)
        self.pure();inbox._authorize(token,method)
        return result


def read_public(reader,key):
        """Same original DTO without constructing a writable inbox or owner.

        Authentication belongs to the enclosing trusted transport. This SDK
        read is neither authority nor evidence of current process cleanup.
        """
        if type(reader) is not DeliveryEvidenceReader:raise TypeError('original delivery reader required')
        validate_schema(ID,key);reader._original()
        value=reader.inspect(key)
        if value is None:raise ControlError(404,'NOT_FOUND','original delivery result not found')
        context=value['machine_context']
        fields=('as_of_state_version','goal_ref','contract_revision','proposal_sha256','source_coverage',
            'result_activation','consent_status','checked_at','required_count','required_satisfied_count',
            'finalization_status','blockers','independent_review_status','goal_completed','dispatch_enabled',
            'model_call_enabled','condition_evidence_write_enabled')
        result={name:value[name] for name in fields}
        result.update(schema_version='1.0',profile='ORIGINAL_DELIVERY_CLIENT_REPORT',
            project_id=reader.project_id,data_mode=reader.data_mode,store_epoch=reader.store_epoch,
            authority='NOT_AUTHORITY',execution_enabled=False,current_execution_status='UNKNOWN',
            resource_release_status='NOT_OBSERVED',
            conditions=[{n:c[n] for n in ('id','required','verification_sha256','status')} for c in value['conditions']],
            source={**{n:context[n] for n in ('result_sha256','configuration_sha256','original_proposal_sha256',
                'recorded_state_version','raw_item_count','machine_case_count','machine_status','evidence_role')},
                'kind':context['source_kind'],'id':context['source_id'],'sha256':context['source_sha256']})
        try:validate_public(result,reader.project_id,reader.kind,key,reader.data_mode)
        except ProtocolError:raise Conflict('original client report source invalid') from None
        if len(canonical(result))>64*1024:raise Conflict('bounded client report required')
        reader.check_current(value['as_of_state_version'])
        reader._original()
        return result
