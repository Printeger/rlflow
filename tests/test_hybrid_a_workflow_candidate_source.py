"""Original source integration with synthetic stdout; NOT a model run."""
import hashlib
import json
import os

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_packet_reader import _HeldPacketReader
from rlflow.store import Conflict, canonical
from tests.test_hybrid_a_workflow_derivation import original, FILES, native_setup


def registered(original, monkeypatch, *, pollute_paths=False):
    owner,bundle,token,obs,claim=original
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('no model authorized'))
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    if pollute_paths:
        owner._native_model_grants[id(grant)]['candidate_paths']=('module/other.py',)
    lease=owner.register(bundle,token,obs,claim,request_key='candidate_source',
        scenario='native_model',native_model_grant=grant)
    source=owner._issued(lease)['source'];row=owner.sources._issued(source)
    return owner,lease,source,row


def output(row, *, path='module/source.py'):
    patch={'base_sha256':digest(FILES),'edits':[{'path':path,
        'before_sha256':('sha256:'+hashlib.sha256(FILES[path].encode()).hexdigest()
                        if path in FILES else None),
        'after':'def parse_entries(text):\n    return [x for x in text.splitlines() if x]\n'}]}
    events=[{'type':'thread.started','thread_id':'synthetic_not_a_model'},
        {'type':'turn.started'}, {'type':'item.completed','item':{'id':'final',
        'type':'agent_message','text':json.dumps(patch)}},
        {'type':'turn.completed','usage':{'input_tokens':12,'cached_input_tokens':3,
            'output_tokens':7}}]
    raw=b''.join(canonical(event)+b'\n' for event in events)
    os.write(row['fds']['write'],raw)
    return raw


def test_original_audited_bytes_derive_candidate_without_execution_or_authority(original,monkeypatch):
    owner,lease,source,row=registered(original,monkeypatch)
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    raw=output(row)
    assert owner.sources.poll_packet_data(source)['offset']==len(raw)
    state=owner.sources.finish_packet_data(source)
    assert state['data_complete'] and not state['source_authenticated']
    assert not state['settlement_enabled'] and not state['condition_evidence_enabled']
    candidate=owner.sources.candidate_data(source)
    assert candidate.base_sha256==digest(FILES)
    assert 'if x' in candidate.files()['module/source.py']
    changed=candidate.files();changed['module/source.py']='caller replacement'
    assert candidate.files()!=changed
    assert owner.sources.candidate_data(source)==candidate
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    assert row['producer'] is None
    with pytest.raises(PermissionError):owner.sources.seal(source)
    with pytest.raises(PermissionError):owner.start(lease)
    # A completed data audit still cannot certify EOF; append invalidates it.
    os.write(row['fds']['write'],b'{}\n')
    with pytest.raises(Conflict,match='final packet data changed'):
        owner.sources.candidate_data(source)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())
    assert owner.store.audit()==owner.store.replay()


@pytest.mark.parametrize('damage',['polluted_grant_paths','message_before_audit','message_after_audit'])
def test_review_source_and_path_cache_corruption_refused(original,monkeypatch,damage):
    owner,lease,source,row=registered(original,monkeypatch,pollute_paths=damage=='polluted_grant_paths')
    output(row,path='module/other.py' if damage=='polluted_grant_paths' else 'module/source.py')
    owner.sources.poll_packet_data(source)
    reader=owner.sources._packet_readers[id(source)]
    message=reader.transcript.message
    if damage!='message_before_audit':owner.sources.finish_packet_data(source)
    if damage!='polluted_grant_paths':
        forged=json.loads(message);forged['edits'][0]['after']='not present in stdout'
        reader.transcript.message=canonical(forged)
    with pytest.raises(Conflict):
        if damage=='message_before_audit':owner.sources.finish_packet_data(source)
        else:owner.sources.candidate_data(source)
    reader.transcript.message=message
    with pytest.raises(Conflict,match='source failed'):owner.sources.candidate_data(source)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())
    assert owner.store.audit()==owner.store.replay()


def test_durable_register_retry_cannot_capture_changed_registry_paths(original,monkeypatch):
    owner,bundle,token,obs,claim=original
    grant=owner.issue_workflow_engineer_grant(bundle,token,obs,files=FILES)
    allocate=owner.sources._runtime_allocate
    def lost(*a,**k):raise OSError('original allocation interrupted after durable REGISTER')
    monkeypatch.setattr(owner.sources,'_runtime_allocate',lost)
    with pytest.raises(OSError,match='allocation interrupted'):
        owner.register(bundle,token,obs,claim,request_key='retry_source',
            scenario='native_model',native_model_grant=grant)
    attempt=owner._attempts['retry_source'];lease=attempt['lease']
    assert 'REGISTER_NO_HANDOFF' in attempt['entries'] and attempt['source'] is None
    monkeypatch.setattr(owner.sources,'_runtime_allocate',allocate)
    saved=owner.plans.registry._raw;config=json.loads(saved)
    config['tools']['native_model']['definition']['spec']['candidate_paths'].append('module/other.py')
    object.__setattr__(owner.plans.registry,'_raw',canonical(config))
    try:
        with pytest.raises((Conflict,PermissionError)):
            owner.register(bundle,token,obs,claim,request_key='retry_source',
                scenario='native_model',native_model_grant=grant)
        assert id(attempt.get('source')) not in owner.sources._packet_origins
    finally:object.__setattr__(owner.plans.registry,'_raw',saved)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    retained=owner.sources._attempts.get(id(claim))
    if retained is not None:assert all(fd is None for fd in retained['fds'].values())
    assert owner.store.audit()==owner.store.replay()


@pytest.mark.parametrize('damage',['unapproved_path','replacement_reader'])
def test_original_candidate_refusal_latches_and_stop_remains_available(original,monkeypatch,damage):
    owner,lease,source,row=registered(original,monkeypatch)
    output(row,path='module/other.py' if damage=='unapproved_path' else 'module/source.py')
    owner.sources.poll_packet_data(source);owner.sources.finish_packet_data(source)
    reader=owner.sources._packet_readers[id(source)]
    if damage=='replacement_reader':
        owner.sources._packet_readers[id(source)]=_HeldPacketReader(row['fds']['read'],
            role='Engineer',candidate_sha256=digest(FILES))
    with pytest.raises(Conflict):owner.sources.candidate_data(source)
    owner.sources._packet_readers[id(source)]=reader
    with pytest.raises(Conflict,match='source failed'):
        owner.sources.candidate_data(source)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0
    assert all(fd is None for fd in row['fds'].values())
    assert owner.store.audit()==owner.store.replay()
