import pytest
from rlflow import literature,research
from rlflow.store import Conflict
from test_engine import harness
from test_packages import approved,specification


def test_controlled_retrieval_approved_source_quota_and_provenance(harness):
    h=harness;spec=specification(h);spec['scout_sources']=['arxiv'];p=approved(h,spec);tid=p['tasks'][0]
    def consult(s):
        research.requests(s,s['tasks'][tid],{'role':'PI'},{'requested_actions':[{'action':'REQUEST_REVIEW','fields':['Scout'],'purpose':'fixed research question','evidence_ids':[]}]})
    h.store.transact('FIXTURE_SCOUT','scout',consult)
    calls=[]
    def fetch(q):calls.append(q);return {'sources':[{'title':'fixture source','url':'https://arxiv.org/abs/fixture','abstract':'untrusted'}]}
    evidence=literature.retrieve(h.store,tid,'fixed research question',fetch)
    assert literature.retrieve(h.store,tid,'same cycle renamed question',fetch)==evidence
    assert len(calls)==1 and evidence['scope']=='EXTERNAL_SOURCE'
    assert not h.store.replay()['jobs']


def test_external_retrieval_default_off(harness):
    h=harness;p=approved(h)
    with pytest.raises(Conflict):literature.retrieve(h.store,p['tasks'][0],'question',lambda _:pytest.fail('network must not run'))
