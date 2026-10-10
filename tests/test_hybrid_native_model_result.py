"""Pure durable result format; fabricated data NEVER proves actual issuance."""
from copy import deepcopy
import hashlib

import pytest

from rlflow.hybrid_a_workflow_profile import PATCH
from rlflow.hybrid_engineering_candidate import transform
from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_result import validate_publication
from rlflow.hybrid_native_model_result import archive_preflight,from_result
from rlflow.hybrid_native_model_stream import REVIEW
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Conflict,canonical
from tests.test_hybrid_native_model_usage import stopped,publication


def engineer():
    runtime=stopped();binding=runtime['origin']['native_model']
    files={'module/source.py':'def parse(text):\n    return text.splitlines()\n'}
    patch={'base_sha256':digest(files),'edits':[{'path':'module/source.py',
        'before_sha256':digest(files['module/source.py']) ,
        'after':'def parse(text):\n    return [line for line in text.splitlines() if line]\n'}]}
    # before hash is UTF8 text SHA, not the JSON string serialization SHA.
    patch['edits'][0]['before_sha256']='sha256:'+hashlib.sha256(files['module/source.py'].encode()).hexdigest()
    message=canonical(patch).decode()
    binding.update(candidate_sha256=digest(files),output_schema_sha256=digest(PATCH),
        workflow={'files':files})
    usage=publication(runtime);usage['output_sha256']='sha256:'+hashlib.sha256(message.encode()).hexdigest()
    runtime['native_model_usage']=usage
    candidate=transform(files,patch,allowed_paths=['module/source.py'])
    return runtime,{'profile':'ORIGINAL_NATIVE_RESULT_V1','role':'Engineer',
        'usage_publication_sha256':digest(usage),'message_utf8':message,
        'files':candidate.files(),'candidate_sha256':candidate.output_sha256,
        'allowed_paths':['module/source.py'],'condition_evidence_enabled':False}


def test_exact_message_and_candidate_recomputed_without_execution_or_authority():
    runtime,value=engineer()
    assert validate_publication(value,runtime,approved_paths=['module/source.py'])==value
    assert not value['condition_evidence_enabled']
    changed=deepcopy(value);changed['files']['module/source.py']='different'
    with pytest.raises(Conflict):validate_publication(changed,runtime)


@pytest.mark.parametrize('damage',['message','files','candidate','paths','usage','role','condition',
    'no_usage','early','wrong_input','wrong_schema','no_workflow','wrong_before'])
def test_durable_result_rehashed_forgery_or_missing_parent_refused(damage):
    runtime,value=engineer()
    if damage=='message':value['message_utf8']+=' '
    elif damage=='files':value['files']['module/source.py']='changed';value['candidate_sha256']=digest(value['files'])
    elif damage=='candidate':value['candidate_sha256']=digest('changed')
    elif damage=='paths':value['allowed_paths'].append('module/extra.py')
    elif damage=='usage':value['usage_publication_sha256']=digest('changed')
    elif damage=='role':runtime['origin']['native_model']['role']='Evaluator'
    elif damage=='condition':value['condition_evidence_enabled']=True
    elif damage=='no_usage':runtime.pop('native_model_usage')
    elif damage=='early':runtime['phase']='STOP_REQUESTED'
    elif damage=='wrong_input':runtime['origin']['native_model']['candidate_sha256']=digest('changed')
    elif damage=='wrong_schema':runtime['origin']['native_model']['output_schema_sha256']=digest('changed')
    elif damage=='no_workflow':runtime['origin']['native_model'].pop('workflow')
    else:
        import json
        patch=json.loads(value['message_utf8']);patch['edits'][0]['before_sha256']=digest('changed')
        value['message_utf8']=canonical(patch).decode()
        runtime['native_model_usage']['output_sha256']='sha256:'+hashlib.sha256(value['message_utf8'].encode()).hexdigest()
        value['usage_publication_sha256']=digest(runtime['native_model_usage'])
    with pytest.raises((Conflict,ProtocolError)):
        validate_publication(value,runtime,approved_paths=['module/source.py'])


@pytest.mark.parametrize('verdict',['ACCEPT','REVISE'])
def test_evaluator_durable_data_is_not_independent_review_qualification(verdict):
    runtime=stopped();binding=runtime['origin']['native_model']
    binding.update(role='Evaluator',output_schema_sha256=digest(REVIEW))
    review={'candidate_sha256':binding['candidate_sha256'],'verdict':verdict,'reason':'pure format only','findings':[]}
    message=canonical(review).decode();usage=publication(runtime)
    usage['output_sha256']='sha256:'+hashlib.sha256(message.encode()).hexdigest()
    runtime['native_model_usage']=usage
    value={'profile':'ORIGINAL_NATIVE_RESULT_V1','role':'Evaluator',
        'usage_publication_sha256':digest(usage),'message_utf8':message,
        'review':review,'condition_evidence_enabled':False}
    assert validate_publication(value,runtime)==value
    value['review']={**review,'reason':'caller rewritten'}
    with pytest.raises(Conflict):validate_publication(value,runtime)


def test_duplicate_verdict_cannot_rehash_into_original_canonical_shape():
    runtime=stopped();binding=runtime['origin']['native_model']
    binding.update(role='Evaluator',output_schema_sha256=digest(REVIEW))
    review={'candidate_sha256':binding['candidate_sha256'],'verdict':'ACCEPT','reason':'pure duplicate test','findings':[]}
    message=canonical(review).decode().replace('"verdict":"ACCEPT"','"verdict":"REVISE","verdict":"ACCEPT"')
    usage=publication(runtime);usage['output_sha256']='sha256:'+hashlib.sha256(message.encode()).hexdigest()
    runtime['native_model_usage']=usage
    value={'profile':'ORIGINAL_NATIVE_RESULT_V1','role':'Evaluator','review':review,
        'message_utf8':message,'usage_publication_sha256':digest(usage),'condition_evidence_enabled':False}
    with pytest.raises(Conflict,match='canonical'):validate_publication(value,runtime)


def test_large_base_and_escaped_candidate_admitted_separately_but_whole_archive_denied():
    runtime,value=engineer();files={'module/source.py':'x'*49000}
    runtime['origin']['native_model'].update(candidate_sha256=digest(files),workflow={'files':files})
    patch={'base_sha256':digest(files),'edits':[{'path':'module/source.py',
        'before_sha256':'sha256:'+hashlib.sha256(files['module/source.py'].encode()).hexdigest(),
        'after':'\x00'*9400}]}
    candidate=transform(files,patch,allowed_paths=['module/source.py'])
    message=canonical(patch).decode();usage=publication(runtime)
    usage['output_sha256']='sha256:'+hashlib.sha256(message.encode()).hexdigest()
    runtime['native_model_usage']=usage
    value.update(message_utf8=message,files=candidate.files(),candidate_sha256=candidate.output_sha256,
        usage_publication_sha256=digest(usage))
    assert validate_publication(value,runtime,approved_paths=['module/source.py'])==value
    data={**value};assert from_result(data,'Engineer',usage)==value
    # The actual writer repeats original workflow files in current/prior scope.
    entry={'request':{'fixture_runtime':runtime},'policy_source':{'bounded_metadata':'x'*32000}}
    with pytest.raises(ProtocolError,match='bounded'):
        archive_preflight(entry,value,usage,({}, {'fixture_runtime':runtime}, {}))


def test_high_escape_result_bound_rejected_before_registration():
    runtime,value=engineer();usage=runtime['native_model_usage']
    value['message_utf8']='\\'*60000
    value['files']={'module/source.py':'\\'*49000}
    with pytest.raises(ProtocolError,match='bounded'):from_result(value,'Engineer',usage)


def test_exact_terminal_oversize_demotes_source_and_budget_without_blocking_cleanup():
    # Pure invocation of the size demotion hook, NOT a live Source or writer.
    from types import SimpleNamespace
    from rlflow.hybrid_native_model_runtime import NativeModelOwner
    runtime,value=engineer();source=object()
    runtime['native_model_result']={**value,'message_utf8':'x'*(256*1024)}
    frame={'request':{'fixture_runtime':runtime},'request_hash':digest('before'),
        'decision':'SETTLED','reason':'NATIVE_MODEL_USAGE_SETTLED'}
    fake=SimpleNamespace(sources=SimpleNamespace(_packet_failures=set()))
    NativeModelOwner._native_terminal_archive_gate(fake,{'source':source},frame)
    assert id(source) in fake.sources._packet_failures
    assert 'native_model_result' not in runtime and 'native_model_usage' not in runtime
    assert frame['decision']=='UNKNOWN' and frame['reason']=='FIXTURE_EXPOSURE_RETAINED'
    assert frame['request_hash']==digest(frame['request'])
