"""Durable original native result DATA; pure validation is never issuance.

The original Source and protected writer must authenticate this fact. It is
not CPU verification, an independent Review, condition acceptance or a grant.
"""
import hashlib
import json

from .hybrid_goals import check_bytes,digest
from .hybrid_protocol import HASH,obj,enum,array,validate_schema
from .hybrid_native_model_usage import validate_publication as usage_publication
from .hybrid_engineering_candidate import _snapshot,transform,MAX_FILES
from .hybrid_native_model_stream import REVIEW,review_data
from .store import Conflict,canonical

BASE={'profile':{'const':'ORIGINAL_NATIVE_RESULT_V1'},'usage_publication_sha256':HASH,
    'role':enum('Engineer','Evaluator'),'message_utf8':{'type':'string','minLength':1,'maxLength':60000},
    'condition_evidence_enabled':{'const':False}}
ENGINEER=obj({**BASE,'role':{'const':'Engineer'},'candidate_sha256':HASH,
    'files':{'type':'object','minProperties':1,'maxProperties':MAX_FILES,
        'additionalProperties':{'type':'string','maxLength':49152}},
    'allowed_paths':{**array({'type':'string','minLength':1,'maxLength':200},MAX_FILES),
        'minItems':1,'uniqueItems':True}})
EVALUATOR=obj({**BASE,'role':{'const':'Evaluator'},'review':REVIEW})
PUBLICATION={'oneOf':[ENGINEER,EVALUATOR]}


def archive_preflight(entry,value,usage,heads):
    """Size-only future terminal frame, never a fact/permission or writer.

    Use actual current original heads and reserve 8KiB for STOP command,
    terminal/hash/version expansion. Actual writer checks its exact frame again.
    """
    check_bytes(value,144*1024)
    frame=json.loads(canonical(entry))
    frame.update(zip(('prior_goal','prior_reservation','prior_project'),heads))
    runtime=frame['request']['fixture_runtime']
    runtime.update(phase='FIXTURE_SCOPE_STOPPED',native_model_result=value,native_model_usage=usage,
        terminal_proof_sha256='sha256:'+'f'*64,wall_seconds=2**63-1)
    check_bytes(frame,256*1024-8192)


def from_result(data,role,usage):
    """Closed data construction, only the original Source may issue it."""
    value={'profile':'ORIGINAL_NATIVE_RESULT_V1','usage_publication_sha256':digest(usage),
        'role':role,'message_utf8':data['message_utf8'],'condition_evidence_enabled':False}
    if role=='Engineer':value.update(files=data['files'],candidate_sha256=data['candidate_sha256'],allowed_paths=data['allowed_paths'])
    else:value['review']=data['review']
    check_bytes(value,144*1024);validate_schema(PUBLICATION,value)
    return value


def validate_publication(value,runtime,*,approved_paths=None):
    check_bytes(value,144*1024);validate_schema(PUBLICATION,value)
    usage=runtime.get('native_model_usage')
    if usage is None:raise Conflict('durable native result requires original complete usage publication')
    usage_publication(usage,runtime)
    binding=runtime['origin']['native_model']
    raw=value['message_utf8'].encode('utf-8')
    if (len(raw)>60000 or value['usage_publication_sha256']!=digest(usage) or
            value['role']!=binding['role'] or
            'sha256:'+hashlib.sha256(raw).hexdigest()!=usage['output_sha256']):
        raise Conflict('durable native result original message/role/usage differs')
    try:
        message=json.loads(raw)
        if canonical(message)!=raw:raise Conflict('original canonical native message required')
    except (ValueError,RecursionError,UnicodeError) as error:raise Conflict('bounded canonical native result JSON required') from error
    if value['role']=='Engineer':
        workflow=binding.get('workflow')
        if workflow is None:raise Conflict('durable candidate requires original workflow files')
        from .hybrid_a_workflow_profile import PATCH
        validate_schema(PATCH,message)
        if digest(PATCH)!=binding['output_schema_sha256']:
            raise Conflict('durable candidate original patch schema differs')
        if approved_paths is not None and value['allowed_paths']!=list(approved_paths):
            raise Conflict('durable candidate paths differ from original approval')
        candidate=transform(workflow['files'],message,allowed_paths=value['allowed_paths'])
        if (_snapshot(value['files'])!=candidate.files() or
                value['candidate_sha256']!=candidate.output_sha256 or
                candidate.base_sha256!=binding['candidate_sha256']):
            raise Conflict('durable candidate transformation differs')
    else:
        if digest(REVIEW)!=binding['output_schema_sha256'] or value['review']!=review_data(message,binding['candidate_sha256']):
            raise Conflict('durable Evaluator original review differs')
    return value
