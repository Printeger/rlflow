import pytest
from rlflow import adoption,policy
from rlflow.store import Conflict
from test_engine import harness


def specification():
    return {'stage_id':'CPU','scope':'SANDBOX_ONLY','mechanism_id':'one','replacement':'existing component',
            'change':'one bounded mechanism','candidate_sha256':'a'*64,'evidence_ids':['e'],
            'counterevidence':['CPU does not prove behavior'],'stop_conditions':['one discriminating experiment']}


def approve(h,spec):
    pid=adoption.propose(h.store,spec);shown=policy.show_proposal(h.store,pid)
    return policy.decide(h.store,pid,shown['sha256'],'APPROVED','fixture')


def test_sandbox_and_mainline_adoption_are_distinct_with_cold_review(harness):
    h=harness;h.store.transact('FIXTURE_SOURCE','source',lambda s:s['evidence'].update(e={'accepted':True}))
    spec=specification();state=approve(h,spec)
    assert state['research']['CPU']['sandbox']['mechanism_id']=='one'
    spec={**spec,'scope':'MAINLINE_ADOPTION'}
    with pytest.raises(Conflict):adoption.propose(h.store,spec)
    h.store.transact('FIXTURE_COLD','cold',lambda s:s['research']['CPU'].update(cycles={'t':{'cold_reviews':[{'raw':{'candidate_sha256':'a'*64},'candidate_sha256':'a'*64}]}}))
    state=approve(h,spec)
    assert state['research']['CPU']['architecture']['hold_until_valid_cycle']==3
    assert state['stages']['CPU']['categories']==['ENGINEERING_FIX']
    assert len(state['approvals'])==2


def test_old_candidate_cold_review_does_not_authorize_new_adoption(harness):
    h=harness;h.store.transact('FIXTURE_SOURCE','source',lambda s:s['evidence'].update(e={'accepted':True}))
    spec=specification();approve(h,spec)
    h.store.transact('FIXTURE_OLD_COLD','old-cold',lambda s:s['research']['CPU'].update(cycles={'old':{'cold_reviews':[{'raw':{'candidate_sha256':'b'*64},'candidate_sha256':'b'*64}]}}))
    with pytest.raises(Conflict,match='matching candidate'):
        adoption.propose(h.store,{**spec,'scope':'MAINLINE_ADOPTION'})


def test_stale_sandbox_proposal_does_not_bypass_new_architecture_window(harness):
    h=harness;h.store.transact('FIXTURE_SOURCE','source',lambda s:s['evidence'].update(e={'accepted':True}))
    pid=adoption.propose(h.store,specification());shown=policy.show_proposal(h.store,pid)
    h.store.transact('FIXTURE_ARCHITECTURE','new-arch',lambda s:s.setdefault('research',{}).update(CPU={'architecture':{'hold_until_valid_cycle':3}}))
    with pytest.raises(Conflict,match='context changed'):
        policy.decide(h.store,pid,shown['sha256'],'APPROVED','stale fixture')
