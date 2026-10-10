"""Original held Reviewer FD wiring with synthetic bytes; not a model review."""
import json
import os

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_stream import REVIEW
from rlflow.store import Conflict,canonical
from tests.test_hybrid_native_model_runtime import model_runtime,native_setup,FILES
import tests.test_hybrid_native_model_runtime as fixture_module


@pytest.mark.parametrize('model_runtime',['Evaluator'],indirect=True)
@pytest.mark.parametrize('outcome',['accept','revise','candidate','must','failure'])
def test_original_evaluator_review_data_binds_frozen_candidate_and_never_accepts(model_runtime,outcome):
    owner,bundle,token,obs,claim=model_runtime
    grant=owner.issue_native_model_grant(bundle,token,obs,packet=fixture_module.PACKET,output_schema=REVIEW)
    lease=owner.register(bundle,token,obs,claim,request_key='review_source',
        scenario='native_model',native_model_grant=grant)
    source=owner._issued(lease)['source'];row=owner.sources._issued(source)
    review={'candidate_sha256':digest(FILES),'verdict':'ACCEPT','reason':'synthetic only','findings':[]}
    if outcome=='revise':review.update(verdict='REVISE',findings=[{'severity':'MUST','text':'repair needed'}])
    if outcome=='candidate':review['candidate_sha256']=digest({'other':'version'})
    if outcome=='must':review['findings']=[{'severity':'MUST','text':'unresolved'}]
    events=[{'type':'thread.started','thread_id':'synthetic_reviewer'},
        {'type':'turn.started'},{'type':'item.completed','item':{'id':'final',
            'type':'agent_message','text':json.dumps(review)}},
        {'type':'turn.completed','usage':{'input_tokens':12,'cached_input_tokens':0,'output_tokens':4}}]
    if outcome=='failure':events[-1]={'type':'turn.failed','error':{'message':'synthetic'}}
    os.write(row['fds']['write'],b''.join(canonical(event)+b'\n' for event in events))
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    owner.sources.poll_packet_data(source);owner.sources.finish_packet_data(source)
    if outcome in ('candidate','must','failure'):
        with pytest.raises(Conflict):owner.sources.review_data(source)
        with pytest.raises(Conflict,match='source failed'):owner.sources.review_data(source)
        owner.stop_to_terminal(lease)
        assert owner.pool.snapshot()['occupied']==0 and all(fd is None for fd in row['fds'].values())
        assert owner.store.audit()==owner.store.replay()
        return
    value=owner.sources.review_data(source)
    assert value==review
    value['findings'].append({'severity':'MUST','text':'caller mutation'})
    assert owner.sources.review_data(source)==review
    assert row['producer'] is None
    assert not owner.sources.packet_result_data(source)['condition_evidence_enabled']
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    with pytest.raises(PermissionError):owner.sources.seal(source)
    # Transcript role is not authority: original frozen Evaluator cannot
    # consume its review as an Engineer candidate, even after caller mutation.
    owner.sources._packet_readers[id(source)].transcript.role='Engineer'
    with pytest.raises(Conflict):owner.sources.candidate_data(source)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied']==0 and all(fd is None for fd in row['fds'].values())
    assert owner.store.audit()==owner.store.replay()
