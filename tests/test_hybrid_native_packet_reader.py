"""Held local FD data tests, not real CLI/account or usage qualification."""
import json
import os

import pytest

from rlflow.hybrid_native_packet_reader import _HeldPacketReader, READ_BYTES
from rlflow.store import Conflict, canonical

HASH = 'sha256:'+'a'*64


def lines(reasoning=0):
    rows = [{'type':'thread.started','thread_id':'original'}, {'type':'turn.started'}]
    rows.extend({'type':'item.completed','item':{'id':str(i),'type':'reasoning','text':'x'*200}}
                for i in range(reasoning))
    rows.extend([{'type':'item.completed','item':{'type':'agent_message','id':'final',
        'text':json.dumps({'edits':[]})}}, {'type':'turn.completed',
        'usage':{'input_tokens':10,'output_tokens':2}}])
    return b''.join(canonical(row)+b'\n' for row in rows)


@pytest.fixture
def held(tmp_path):
    path = tmp_path/'stdout.jsonl'
    path.write_bytes(b'')
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        yield path,fd
    finally:
        os.close(fd)


def test_incremental_partial_and_complete_data_never_grants_authority(held):
    path,fd = held
    reader = _HeldPacketReader(fd,role='Engineer',candidate_sha256=HASH)
    raw = lines()
    path.write_bytes(raw[:13])
    assert reader.poll()['offset'] == 0
    with path.open('ab') as output:
        output.write(raw[13:])
    assert reader.poll()['offset'] == len(raw)
    state = reader.finish_data()
    assert state['data_complete']
    assert not state['source_authenticated'] and not state['settlement_enabled']
    assert not state['condition_evidence_enabled']
    assert not reader.result['source_authenticated']
    assert reader.poll() == state


def test_full_audit_catches_old_middle_rewrite_beyond_anchor(held):
    path,fd = held
    raw = lines(600)
    path.write_bytes(raw[:70000])
    reader = _HeldPacketReader(fd,role='Engineer',candidate_sha256=HASH)
    reader.poll()
    # A rewrite hidden by concurrent growth is outside the retained tip; the
    # final independent full-prefix audit, not just metadata, must catch it.
    with path.open('r+b') as output:
        output.seek(raw.index(b'original'))
        output.write(b'changed!')
        output.seek(0,os.SEEK_END)
        output.write(raw[70000:])
    while reader.transcript.offset < len(raw):
        before = reader.transcript.offset
        reader.poll()
        assert 0 < reader.transcript.offset-before <= READ_BYTES
    state = reader.finish_data()
    assert not state['data_complete']
    with pytest.raises(Conflict,match='earlier packet prefix rewritten'):
        while not state['data_complete']:
            state = reader.poll()
    with pytest.raises(Conflict,match='failed'):
        reader.poll()


def test_bounded_multi_step_audit_and_post_completion_append_rejected(held):
    path,fd = held
    raw = lines(600)
    path.write_bytes(raw)
    reader = _HeldPacketReader(fd,role='Evaluator',candidate_sha256=HASH)
    while reader.transcript.offset < len(raw):
        reader.poll()
    state = reader.finish_data()
    assert not state['data_complete'] and state['audit_offset'] == READ_BYTES
    while not state['data_complete']:
        before = state['audit_offset']
        state = reader.poll()
        assert 0 < state['audit_offset']-before <= READ_BYTES
    with path.open('ab') as output:
        output.write(b'{}\n')
    with pytest.raises(Conflict,match='final packet data changed'):
        reader.poll()


@pytest.mark.parametrize('mode',['writable','oversize','incomplete','tail_rewrite','replacement'])
def test_invalid_held_data_refused(held,mode,tmp_path):
    path,fd = held
    if mode == 'writable':
        other = os.open(path,os.O_RDWR)
        try:
            with pytest.raises(Conflict,match='read-only'):
                _HeldPacketReader(other,role='Engineer',candidate_sha256=HASH)
        finally:
            os.close(other)
        return
    reader = _HeldPacketReader(fd,role='Engineer',candidate_sha256=HASH)
    if mode == 'oversize':
        with path.open('ab') as output:
            output.truncate(1024**2+1)
    elif mode == 'incomplete':
        path.write_bytes(lines()[:-1])
        reader.poll()
        with pytest.raises(Conflict,match='complete consumed'):
            reader.finish_data()
        return
    elif mode == 'tail_rewrite':
        path.write_bytes(b'{"type":')
        reader.poll()
        path.write_bytes(b'{"fail": '+b' '*5)
    else:
        replacement = tmp_path/'other'
        replacement.write_bytes(lines())
        other = os.open(replacement,os.O_RDONLY)
        try:
            os.dup2(other,fd)
        finally:
            os.close(other)
    with pytest.raises(Conflict):
        reader.poll()
    with pytest.raises(Conflict,match='failed'):
        reader.poll()
