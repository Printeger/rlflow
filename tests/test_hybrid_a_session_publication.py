"""Pure original-publisher harness; these synthetic caps are NOT issuance proof."""
import json
from types import SimpleNamespace

from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_runtime import NativeModelOwner
from rlflow.hybrid_native_model_source import NativeModelSourceOwner,NativeModelResult
from rlflow.hybrid_usage_source import _RuntimeStartedObservation
from rlflow.store import canonical
from tests.test_hybrid_native_model_usage import stopped,HASH


def test_session_id_is_from_original_ack_not_result_or_caller_runtime():
    owner=object.__new__(NativeModelOwner);source_owner=object.__new__(NativeModelSourceOwner)
    owner.sources=source_owner;runtime=stopped();source=SimpleNamespace(id='synthetic_source');lease=SimpleNamespace(id=runtime['origin']['lease_id'])
    runtime['source']=source;runtime['producer_identity']=runtime['producer']
    runtime['terminal']={'scope':'FIXED_NATIVE_SINGLE_TGID','lease_id':lease.id,
        'producer':runtime['producer'],'all_original_source_fds_closed':True,'original_participant_reaped':True}
    runtime['model_session_id']='CALLER_SESSION_NOT_AUTHORITY'
    ack=_RuntimeStartedObservation(source,canonical({'event':{'type':'thread.started','thread_id':'ORIGINAL_ACK_SESSION'}}))
    runtime['started_ack']=ack
    cap=NativeModelResult(source,canonical({'stream_sha256':HASH,'output_sha256':HASH,'ready_sha256':HASH,
        'usage':{'input_tokens':12,'output_tokens':4,'cached_tokens':0,'complete':True},
        'bytes':100,'model_session_id':'RESULT_SESSION_NOT_AUTHORITY'}))
    owner._issued=lambda token:runtime
    source_owner._actual=lambda:None;source_owner._packet_failures=set()
    source_owner._model_results={id(source):(owner,lease,cap)}
    source_owner._issued_native_result=lambda *args:cap;source_owner._runtime_started=lambda *args:ack
    source_owner._extra_fork_descriptors=lambda row:False
    source_owner._issued=lambda token:{'status':'CLOSED','fds':{'read':None},
        'producer':SimpleNamespace(poll=lambda:0,stdin=SimpleNamespace(closed=True))}
    value=source_owner._runtime_usage_publication(owner,lease)
    assert value['model_session_id']=='ORIGINAL_ACK_SESSION'
    assert value['started_ack_sha256']==digest(json.loads(ack.raw))
