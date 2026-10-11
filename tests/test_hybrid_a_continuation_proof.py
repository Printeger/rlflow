"""Historical memo ACK harness only; not model/runtime qualification."""
import threading
from types import SimpleNamespace

import pytest

from rlflow.store import Conflict,canonical
from rlflow.hybrid_goals import digest
from rlflow.hybrid_fixture_runtime_ledger import _ConditionLookupProof,_CONDITION_LOOKUP_FACTORY
from rlflow.hybrid_a_continuation_runtime import prove_historical_links


@pytest.mark.parametrize('fault',['none','preloaded','failed','foreign','copied_ack','changed_context'])
def test_only_original_successful_full_proof_ack_can_reuse(monkeypatch,fault):
    import rlflow.hybrid_a_condition_acceptance as condition
    from rlflow.hybrid_native_model_runtime import NativeModelOwner
    owner=object.__new__(NativeModelOwner)
    monkeypatch.setattr(NativeModelOwner,'_actual',lambda self:None)
    db=SimpleNamespace(in_transaction=True);read=SimpleNamespace(db=db)
    parent={'original':'parent'};value={'request':{k:k for k in
        ('project_id','data_mode','store_epoch','goal_ref','reviewer_terminal_key')},
        'parents':{'engineer':{'key':'p','hash':digest(parent)}}}
    cap=SimpleNamespace(raw=b'original');row={'child':owner,'material':'material','parent':'parent'}
    prior=SimpleNamespace(sources=SimpleNamespace(_live=False),_live=False,
        _continuation_roots={},_continuation_retirements={})
    root=(row,None,cap,cap.raw,row['material'],row['parent'],prior)
    # root material normally contains the original acceptance, not caller data.
    row['material']=canonical({'acceptance':value});root=(*root[:4],row['material'],*root[5:])
    retirement=(root,prior.sources,'close')
    prior._continuation_roots[id(cap)]=root;prior._continuation_retirements[id(cap)]=retirement
    owner._continuation_parent=(prior,cap,row,root)
    owner.controller=SimpleNamespace(_token_active=(db,object(),read,threading.get_ident()))
    store=SimpleNamespace(_hybrid_budget_service=SimpleNamespace(_fixture_runtime=owner))
    calls=[];fail=[False]
    monkeypatch.setattr(condition,'original_event',lambda *args:calls.append('event') or value)
    def validate(*args):
        calls.append('links')
        if fail[0]:raise Conflict('TEST first full authentication failed')
    monkeypatch.setattr(condition,'validate_links',validate)
    def factory():
        lookup=lambda *args:parent
        proof=_ConditionLookupProof(store,db,read,{},lookup,_factory=_CONDITION_LOOKUP_FACTORY)
        lookup._condition_proof=proof
        return proof
    first=factory()
    if fault in ('preloaded','failed'):
        if fault=='failed':
            fail[0]=True
            with pytest.raises(Conflict):prove_historical_links(first,value)
            assert first._completed is None
            fail[0]=False
        read._a_continuation_condition_links=(owner,root,retirement,canonical(value),first,None)
    else:
        prove_historical_links(first,value)
        assert calls==['event','links']
        if fault=='foreign':
            read._a_condition_lookup_contexts={}
        elif fault=='copied_ack':
            first._completed=tuple(list(first._completed))
        elif fault=='changed_context':
            first.state={}
    calls.clear();second=factory();prove_historical_links(second,value)
    assert calls==([] if fault=='none' else ['event','links'])
    if fault!='none':assert second._completed is not None


def test_transition_lookup_preserves_writer_but_never_caches_current_heads():
    from rlflow.hybrid_fixture_runtime import _FixtureRuntimeGuard
    db=SimpleNamespace(in_transaction=True);heads={'head':'first'}
    read=SimpleNamespace(db=db,object=lambda section,key:heads[key]);owner=SimpleNamespace()
    guard=object.__new__(_FixtureRuntimeGuard)
    guard.owner,guard.db,guard.read,guard.budget=owner,db,read,read
    guard.thread=threading.get_ident();owner._active=guard
    assert guard.transition_lookup('current','head')=='first'
    heads['head']='second'
    assert guard.transition_lookup('current','head')=='second'
    assert guard.transition_lookup.__self__ is guard
    owner._active=None
    with pytest.raises(PermissionError):guard.transition_lookup('current','head')
