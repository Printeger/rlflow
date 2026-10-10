"""Synthetic failure observations, never CLI exit or actual cost evidence."""
import json

import pytest

from rlflow.hybrid_native_model_stream import PacketTranscript
from rlflow.store import Conflict,canonical

HASH='sha256:'+'a'*64


@pytest.mark.parametrize('kind,position',[('error','empty'),('error','thread'),
    ('error','turn'),('turn.failed','turn'),('turn.failed','message')])
def test_failure_data_is_auditable_but_not_success_or_known_usage(kind,position):
    stream=PacketTranscript(role='Engineer',candidate_sha256=HASH)
    rows=[]
    if position!='empty':rows.append({'type':'thread.started','thread_id':'synthetic'})
    if position in ('turn','message'):rows.append({'type':'turn.started'})
    if position=='message':rows.append({'type':'item.completed','item':{
        'id':'final','type':'agent_message','text':json.dumps({'edits':[]})}})
    # Even counts claimed in a failure event are not a complete usage receipt.
    rows.append({'type':kind,'error':{'message':'synthetic diagnostic'},
        'usage':{'input_tokens':100,'cached_input_tokens':0,'output_tokens':5}})
    for row in rows:stream.accept(stream.offset,canonical(row)+b'\n')
    data=stream.finish()
    assert data['failure_event']['type']==kind
    assert data['output_sha256'] is None if position!='message' else data['output_sha256'] is not None
    assert not data['usage']['complete']
    assert data['usage']['input_tokens'] is None
    assert not data['source_authenticated'] and not data['settlement_enabled']
    assert not data['condition_evidence_enabled']
    observed_state=stream.state
    stream.state='DONE'  # A mutable status cannot erase the failure latch.
    with pytest.raises(Conflict):stream.candidate({'x.py':'x'},allowed_paths=['x.py'])
    with pytest.raises(Conflict):stream.review()
    stream.state=observed_state
    with pytest.raises(Conflict):stream.accept(stream.offset,canonical({'type':'turn.started'})+b'\n')


def test_failure_data_does_not_hide_retry_or_success_suffix():
    stream=PacketTranscript(role='Engineer',candidate_sha256=HASH)
    for row in [{'type':'thread.started','thread_id':'synthetic'}, {'type':'turn.started'},
                {'type':'turn.failed'}]:
        stream.accept(stream.offset,canonical(row)+b'\n')
    with pytest.raises(Conflict):stream.accept(stream.offset,canonical({'type':'turn.completed'})+b'\n')
    with pytest.raises(Conflict):stream.finish()


def test_valid_evaluator_accept_message_followed_by_failure_is_not_review():
    stream=PacketTranscript(role='Evaluator',candidate_sha256=HASH)
    review={'candidate_sha256':HASH,'verdict':'ACCEPT','reason':'synthetic','findings':[]}
    for row in [{'type':'thread.started','thread_id':'synthetic'}, {'type':'turn.started'},
        {'type':'item.completed','item':{'id':'review','type':'agent_message','text':json.dumps(review)}},
        {'type':'turn.failed'}]:
        stream.accept(stream.offset,canonical(row)+b'\n')
    data=stream.finish()
    assert data['output_sha256'] is not None and not data['usage']['complete']
    with pytest.raises(Conflict):stream.review()
    stream.state='DONE'
    with pytest.raises(Conflict):stream.review()
