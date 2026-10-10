"""Pure native usage format/math only; never original issuance evidence."""
from copy import deepcopy

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_usage import validate_publication,consumption
from rlflow.store import Conflict
from rlflow.hybrid_protocol import ProtocolError
from tests.test_hybrid_native_model_budget import _binding,_runtime,HASH


def publication(runtime):
    origin=runtime['origin'];binding=origin['native_model']
    return dict(profile='ORIGINAL_NATIVE_CLI_USAGE_V1',source_id='synthetic_source',
        **{key:origin[key] for key in ('lease_id','task_id','attempt_id','nonce')},
        grant_id=binding['grant_id'],grant_sha256=digest(binding),producer=runtime['producer'],
        **{key:binding[key] for key in ('workspace_id','packet_sha256','output_schema_sha256','candidate_sha256')},
        stream_sha256=HASH,output_sha256=HASH,stream_bytes=100,ready_sha256=HASH,
        started_ack_sha256=runtime['started_ack_sha256'],
        terminal_proof_sha256=runtime['terminal_proof_sha256'],producer_exit_code=0,
        usage=dict(input_tokens=12000,output_tokens=1200,cached_tokens=3,complete=True))


def stopped():
    _,_,binding=_binding();runtime=_runtime(binding)
    runtime.update(phase='FIXTURE_SCOPE_STOPPED',native_model_handoff_attempted=True,
        producer=dict(pid=2,pgid=2,starttime='2',boot_id=runtime['origin']['owner']['boot_id']),
        started_ack_sha256=HASH,terminal_proof_sha256=HASH,wall_seconds=21)
    return runtime


def test_complete_cli_consumption_is_not_clipped_or_cached_input_subtracted():
    runtime=stopped();data=publication(runtime)
    counts=consumption(data,runtime)
    assert counts['model_sessions']==1 and counts['model_input_tokens']==12000
    assert counts['model_output_tokens']==1200 and counts['wall_seconds']==21
    assert counts['gpu_device_seconds']==0 and counts['experiment_starts']==0


@pytest.mark.parametrize('field',['lease_id','task_id','attempt_id','grant_id','nonce',
    'grant_sha256','workspace_id','packet_sha256','output_schema_sha256',
    'candidate_sha256','producer','started_ack_sha256','terminal_proof_sha256',
    'incomplete','missing_count','cache_over_input','failed_exit','not_stopped','no_handoff'])
def test_damaged_publication_or_runtime_refused(field):
    runtime=stopped();data=deepcopy(publication(runtime))
    if field=='incomplete':data['usage']['complete']=False
    elif field=='missing_count':del data['usage']['input_tokens']
    elif field=='cache_over_input':data['usage']['cached_tokens']=12001
    elif field=='failed_exit':data['producer_exit_code']=1
    elif field=='not_stopped':runtime['phase']='STOP_REQUESTED'
    elif field=='no_handoff':runtime['native_model_handoff_attempted']=False
    elif field=='producer':data['producer']['pid']=3
    elif field.endswith('sha256'):data[field]='sha256:'+'b'*64
    elif field=='nonce':data[field]='b'*32
    elif field=='workspace_id':data[field]='22345678-1234-1234-1234-123456789012'
    else:data[field]='different'
    with pytest.raises((Conflict,ProtocolError)):validate_publication(data,runtime)
