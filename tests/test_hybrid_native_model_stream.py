"""Synthetic decoding tests, NOT real model/source/independent review evidence."""
import hashlib
import json

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_stream import PacketTranscript
from rlflow.store import canonical, Conflict

FILES = {'normalizer.py': 'def clean(value):\n    return value\n'}
PATCH = {'base_sha256': digest(FILES), 'edits': [{'path': 'normalizer.py',
    'before_sha256': 'sha256:' + hashlib.sha256(FILES['normalizer.py'].encode()).hexdigest(),
    'after': 'def clean(value):\n    return value.strip()\n'}]}


def transcript(output=PATCH, *, role='Engineer', candidate=None, usage=None):
    decoder = PacketTranscript(role=role, candidate_sha256=candidate or digest(FILES))
    events = [dict(type='thread.started', thread_id='thread_one'), dict(type='turn.started'),
        dict(type='item.completed', item=dict(id='item_one', type='agent_message', text=json.dumps(output))),
        dict(type='turn.completed', usage=usage if usage is not None else
            dict(input_tokens=120, cached_input_tokens=20, output_tokens=40))]
    for event in events: decoder.accept(decoder.offset, canonical(event) + b'\n')
    return decoder


def test_packet_decodes_arbitrary_candidate_without_authority_or_settlement():
    decoder = transcript(); result = decoder.finish()
    assert result['usage']['input_tokens'] == 120 and result['usage']['complete']
    assert not result['source_authenticated'] and not result['settlement_enabled']
    assert not result['condition_evidence_enabled'] and not result['usage']['settlement_enabled']
    assert decoder.candidate(FILES, allowed_paths=['normalizer.py']).files()['normalizer.py'].endswith('value.strip()\n')
    assert decoder.finish() == result
    with pytest.raises(Conflict):decoder.accept(decoder.offset, canonical(dict(type='turn.started')) + b'\n')


@pytest.mark.parametrize('usage', [{}, {'input_tokens': 120},
    {'input_tokens': 120, 'output_tokens': 40}])
def test_missing_actual_counters_preserves_unknown_even_with_valid_output(usage):
    decoder = transcript(usage=usage); result = decoder.finish()
    assert not result['usage']['complete']
    assert result['usage']['cached_tokens'] is None
    assert decoder.candidate(FILES, allowed_paths=['normalizer.py']).files()


@pytest.mark.parametrize('event', [dict(type='thread.started', thread_id='second'),
    dict(type='turn.started'), dict(type='turn.failed'), dict(type='error'),
    dict(type='unknown'), dict(type='item.completed', item=dict(type='command_execution', text='{}')),
    dict(type='item.completed', item=dict(type='agent_message', text='{}'))])
def test_post_completion_events_are_latched_failure_not_second_session(event):
    decoder = transcript()
    with pytest.raises(Conflict):decoder.accept(decoder.offset, canonical(event) + b'\n')
    with pytest.raises(Conflict):decoder.finish()
    with pytest.raises(Conflict):decoder.candidate(FILES, allowed_paths=['normalizer.py'])


@pytest.mark.parametrize('text', ['{"base_sha256":1,"base_sha256":2}', '{} , "extra":1',
    '"plain string"', '{"value":NaN}', '{"value":Infinity}', 'not JSON'])
def test_invalid_structured_output_never_salvaged_as_candidate(text):
    decoder = PacketTranscript(role='Engineer', candidate_sha256=digest(FILES))
    for event in [dict(type='thread.started', thread_id='one'), dict(type='turn.started')]:
        decoder.accept(decoder.offset, canonical(event) + b'\n')
    event = dict(type='item.completed', item=dict(type='agent_message', text=text))
    with pytest.raises(Conflict):decoder.accept(decoder.offset, canonical(event) + b'\n')
    with pytest.raises(Conflict):decoder.finish()


@pytest.mark.parametrize('damage', ['offset', 'partial', 'tool', 'missing_output', 'second_thread'])
def test_non_packet_or_partial_original_stream_is_not_accepted(damage):
    decoder = PacketTranscript(role='Engineer', candidate_sha256=digest(FILES))
    decoder.accept(0, canonical(dict(type='thread.started', thread_id='one')) + b'\n')
    decoder.accept(decoder.offset, canonical(dict(type='turn.started')) + b'\n')
    event = dict(type='item.completed', item=dict(type='agent_message', text=json.dumps(PATCH)))
    offset = decoder.offset
    if damage == 'offset':offset += 1
    elif damage == 'tool':event['item']['type'] = 'file_change'
    elif damage == 'missing_output':event = dict(type='turn.completed', usage={})
    elif damage == 'second_thread':event = dict(type='thread.started', thread_id='two')
    raw = canonical(event) + (b'' if damage == 'partial' else b'\n')
    with pytest.raises(Conflict):decoder.accept(offset, raw)
    with pytest.raises(Conflict):decoder.finish()


def test_reviewer_data_is_candidate_bound_not_an_independence_receipt():
    candidate = digest({'new': 'snapshot'})
    review = dict(candidate_sha256=candidate, verdict='ACCEPT', reason='No blocking finding.', findings=[])
    decoder = transcript(review, role='Evaluator', candidate=candidate)
    result = decoder.finish(); assert decoder.review() == review
    assert not result['condition_evidence_enabled']
    with pytest.raises(Conflict):decoder.candidate(FILES, allowed_paths=['normalizer.py'])
    for changed in [{**review, 'candidate_sha256': digest(FILES)},
        {**review, 'findings': [dict(severity='MUST', text='Needs repair.')]},
        {**review, 'source_authenticated': True}]:
        decoder = transcript(changed, role='Evaluator', candidate=candidate); decoder.finish()
        with pytest.raises(ValueError):decoder.review()


def test_engineer_cannot_change_approved_paths_or_snapshot():
    decoder = transcript(); decoder.finish()
    with pytest.raises(Conflict):decoder.candidate({'normalizer.py': 'different'}, allowed_paths=['normalizer.py'])
    with pytest.raises(Conflict):decoder.candidate(FILES, allowed_paths=['other.py'])


@pytest.mark.parametrize('kind', ['item.started', 'item.updated', 'item.completed'])
def test_final_message_cannot_change_before_turn_completion(kind):
    decoder = PacketTranscript(role='Engineer', candidate_sha256=digest(FILES))
    for event in [dict(type='thread.started', thread_id='one'), dict(type='turn.started'),
        dict(type='item.completed', item=dict(id='final', type='agent_message', text=json.dumps(PATCH)))]:
        decoder.accept(decoder.offset, canonical(event) + b'\n')
    assert decoder.state == 'MESSAGE'
    event = dict(type=kind, item=dict(id='final', type='agent_message', text='{"changed":true}'))
    with pytest.raises(Conflict):decoder.accept(decoder.offset, canonical(event) + b'\n')
    with pytest.raises(Conflict):decoder.finish()
