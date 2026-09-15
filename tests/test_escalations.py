import json
from pathlib import Path
import pytest
from rlflow import engine, model_policy, escalations
from rlflow.store import Store, Conflict, canonical, atomic
from test_engine import harness, deliver, result_for


def enable_policy(tmp_path,monkeypatch):
    p=model_policy.load_policy();p.pop('sha256');p['astra']['enabled']=True
    f=tmp_path/'policy.yaml';f.write_text(json.dumps(p));monkeypatch.setattr(model_policy,'POLICY',f)


def spec(h,sid,cid='case-1',reason='E02_ARCHITECTURE_DECISION'):
    return {'id':cid,'task_id':h.task_id,'source_session':sid,'reason_code':reason,
            'evidence_refs':['E-'+sid],'question':'Which interpretation preserves the frozen contract?',
            'expected_output':'Discriminate alternatives or identify missing observations.',
            'competing_explanations':['An implementation boundary problem','A contract interpretation problem']}


def first(h):
    sid=engine.dispatch_one(h.store);deliver(h,sid);return sid


def test_sol_high_then_astra_is_fresh_and_keeps_authority(harness,tmp_path,monkeypatch):
    h=harness;enable_policy(tmp_path,monkeypatch)
    model_policy.set_budget(h.store,'CPU',7,1,'fixture stage allowance')
    sid=first(h)
    escalations.register_case(h.store,spec(h,sid))
    escalations.queue(h.store,'case-1')
    se2=engine.dispatch_one(h.store)
    state=h.store.replay();second=state['sessions'][se2]
    assert second['compute']['effort']=='high' and second['compute']['tier']=='sol'
    assert second['role_definition']==state['sessions'][sid]['role_definition']
    assert second['escalation_package']['source_session']==sid
    for f in second['escalation_package']['evidence_files']:
        assert Path(f['path']).is_relative_to(Path(second['directory'])/'evidence')
    deliver(h,se2)
    escalations.register_case(h.store,spec(h,se2,'case-2'))
    escalations.queue(h.store,'case-2')
    se3=engine.dispatch_one(h.store)
    state=h.store.replay();third=state['sessions'][se3]
    assert third['compute']['tier']=='astra' and third['compute']['effort']=='high'
    assert len({sid,se2,se3})==3
    assert third['role_definition']==second['role_definition']
    deliver(h,se3)
    state=h.store.replay()
    assert state['stages']['CPU']['compute']['used']=={'sol':2,'astra':1}
    assert state['stages']['CPU']['compute']['reserved_seconds']=={'sol':0,'astra':0}
    escalations.queue(Store(h.store.root),'case-2')
    assert h.store.replay()==state


def test_no_schema_or_infrastructure_failure_escalation(harness):
    h=harness;sid=engine.dispatch_one(h.store);deliver(h,sid,code=7)
    with pytest.raises(Conflict,match='valid completed'):escalations.register_case(h.store,spec(h,sid))


@pytest.mark.parametrize('tamper',['candidate','evidence','policy','authority'])
def test_escalation_pins_fail_closed(harness,tmp_path,monkeypatch,tamper):
    h=harness;sid=first(h);escalations.register_case(h.store,spec(h,sid))
    if tamper=='candidate':(h.repo/'parser.py').write_text('changed')
    elif tamper=='evidence':
        d=Path(h.store.replay()['sessions'][sid]['directory']);(d/'result.json').write_text('{}')
    elif tamper=='policy':enable_policy(tmp_path,monkeypatch)
    else:h.store.transact('FIXTURE','scope',lambda s:s['stages']['CPU'].update(module_roots=['parser.py']))
    with pytest.raises(Conflict):escalations.queue(h.store,'case-1')
    assert h.store.replay()['stages']['CPU']['used_calls']==1


def test_actor_recommendation_cannot_authorize_itself(harness):
    h=harness;sid=engine.dispatch_one(h.store);r=result_for(h,sid)
    r['requested_actions']=[{'action':'REQUEST_MODEL_ESCALATION','fields':['not-authorized'],
                             'evidence_ids':[],'purpose':'Resolve an uncertainty'}]
    state=deliver(h,sid,r)
    assert state['tasks'][h.task_id]['status']=='ESCALATION_PENDING'
    assert state['stages']['CPU']['used_calls']==1
    assert engine.dispatch_one(h.store) is None


def test_authorized_recommendation_routes_automatically(harness):
    h=harness;sid=first(h);escalations.register_case(h.store,spec(h,sid))
    h.store.transact('FIXTURE','reconsider',lambda s:s['tasks'][h.task_id].update(next_role='PI'))
    sid2=engine.dispatch_one(h.store);r=result_for(h,sid2)
    r['requested_actions']=[{'action':'REQUEST_MODEL_ESCALATION','fields':['case-1'],
                             'evidence_ids':['E-'+sid],'purpose':'Resolve authorized interpretation question'}]
    state=deliver(h,sid2,r)
    assert state['tasks'][h.task_id]['status']=='QUEUED'
    sid3=engine.dispatch_one(h.store)
    assert h.store.replay()['sessions'][sid3]['compute']['effort']=='high'


def test_inconclusive_alone_never_authorizes_astra(harness,tmp_path,monkeypatch):
    h=harness;enable_policy(tmp_path,monkeypatch);sid=first(h)
    escalations.register_case(h.store,spec(h,sid));escalations.queue(h.store,'case-1')
    high=engine.dispatch_one(h.store);deliver(h,high)
    with pytest.raises(Conflict,match='alone'):escalations.register_case(h.store,spec(h,high,'case-2','E06_SOL_HIGH_INCONCLUSIVE'))


def test_exhausted_astra_does_not_consume_sol_or_call(harness,tmp_path,monkeypatch):
    h=harness;enable_policy(tmp_path,monkeypatch);sid=first(h)
    escalations.register_case(h.store,spec(h,sid));escalations.queue(h.store,'case-1')
    high=engine.dispatch_one(h.store);deliver(h,high)
    escalations.register_case(h.store,spec(h,high,'case-2'))
    before=h.store.replay()
    with pytest.raises(Conflict,match='astra compute budget exhausted'):escalations.queue(h.store,'case-2')
    assert h.store.replay()==before


def test_case_id_cannot_be_rebound(harness):
    h=harness;sid=first(h);request=spec(h,sid)
    c=escalations.register_case(h.store,request)
    assert escalations.register_case(h.store,request)==c
    request['expected_output']='Different question'
    with pytest.raises(Conflict,match='different content'):escalations.register_case(h.store,request)


def test_scout_cannot_get_astra_case(harness):
    h=harness;sid=first(h)
    # A role-incompatible reason is rejected before any budget reservation.
    with pytest.raises(Conflict,match='reason not permitted'):
        escalations.register_case(h.store,spec(h,sid,reason='E07_SOURCE_AMBIGUITY'))
