"""Actual protected budget writes; no paid model or runtime execution."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import threading
import inspect

import pytest

from rlflow.hybrid_budget import zero,account_key
from rlflow.hybrid_budget_ledger import SECTIONS,entry_key,reservation_key,scope
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_controller_service import ControllerService,ControllerToken
from rlflow.hybrid_preparation_service import PreparationService
from rlflow.hybrid_authority import timestamp
from rlflow.hybrid_goals import SECTIONS as GOALS,head_key
from rlflow.hybrid_preparation import SECTIONS as PREPARATION,intent_key
from rlflow.hybrid_control import ControlServices
from rlflow.web_api import create_app,Project
from rlflow.observation import rotate_epoch
from fastapi.testclient import TestClient
from tests.test_hybrid_control_api import login,post,prepare,submit_payload,approve_payload,ORIGIN
from rlflow.store import Store,Conflict,canonical,sha
from rlflow.snapshot_maintenance import maintain
from tests.test_hybrid_admission import admission
from tests.test_hybrid_preparation_service import owned
from tests.test_hybrid_preparation import prepared
from tests.test_execution_adapter import setup as native_setup


def actual(admission,amount=1):
    prep,control,_,_,value,_=admission
    owner=BudgetService(prep.store,prep.registry,control,prep)
    request={'project_id':prep.project_id,'data_mode':prep.data_mode,'store_epoch':prep.store_epoch,
        'goal_ref':value['sources']['goal_ref'],'idempotency_key':'actual-budget','expected_state_version':5,
        'action':'RESERVE','preparation_intent_key':value['preparation']['intent_key'],
        'amount':{**zero(),'wall_seconds':amount},'purpose':'EXECUTION'}
    return owner,request,control._tokens[value['controller']['fact_key']]


def cleanup(request,action,version=6,key='cleanup'):
    value={n:request[n] for n in ('project_id','data_mode','store_epoch','goal_ref')}
    return {**value,'idempotency_key':key,'expected_state_version':version,
        'action':action,'reservation_id':reservation_key(request)}


def test_actual_reserve_audit_snapshot_recover(admission):
    owner,request,token=actual(admission);result=owner.record(request,token)
    assert result['entry']['decision']=='HELD' and result['execution_enabled'] is False
    goal=owner.store.get(SECTIONS[1],account_key(scope(request)))
    assert goal['balance']['wall_seconds']['reserved']==1
    assert not owner.store.objects('sessions') and not owner.store.objects('tasks')
    state=owner.store.audit();assert state==owner.store.replay()
    owner.store.snapshot();assert Store(owner.store.root).recover()==state
    assert owner._active is None and owner.controller._token_active is None


@pytest.mark.parametrize('action,status,retained',[('MARK_UNKNOWN','UNKNOWN',1),('CANCEL_BEFORE_RUNTIME','CANCELLED',0)])
def test_cleanup_is_atomic_terminal_and_never_executes(admission,action,status,retained):
    owner,request,token=actual(admission);owner.record(request,token)
    command=cleanup(request,action);result=owner.record(command,token)
    assert result['entry']['decision']==status
    goal=owner.store.get(SECTIONS[1],account_key(scope(request)))
    assert goal['balance']['wall_seconds']['reserved']==retained
    assert goal['balance']['wall_seconds']['unknown_exposure']==(1 if status=='UNKNOWN' else 0)
    assert owner.store.audit()==owner.store.replay()
    assert owner.record(command,token)=={**result,'duplicate':True}
    with pytest.raises(Conflict):owner.record(cleanup(request,'CANCEL_BEFORE_RUNTIME',7,'other'),token)
    assert owner.store.version()==7


def test_actual_denial_retains_last_quota(admission):
    owner,request,token=actual(admission,240);owner.record(request,token)
    next_request={**request,'idempotency_key':'next','expected_state_version':6,'amount':{**zero(),'wall_seconds':1}}
    assert owner.record(next_request,token)['entry']['decision']=='DENIED'
    goal=owner.store.get(SECTIONS[1],account_key(scope(request)))
    assert goal['balance']['wall_seconds']['reserved']==240
    assert owner.store.audit()==owner.store.replay()


def test_duplicate_is_historical_not_current_lease(admission,monkeypatch):
    owner,request,token=actual(admission);result=owner.record(request,token)
    expired=timestamp(result['entry']['policy_source']['expires_at'])+timedelta(days=1)
    monkeypatch.setattr(owner.controller,'clock',lambda:expired)
    assert owner.record(request,token)=={**result,'duplicate':True}
    with pytest.raises(Conflict,match='idempotency'):owner.record({**request,'expected_state_version':6},token)
    assert owner.store.version()==6


@pytest.mark.parametrize('section',SECTIONS)
def test_direct_generic_budget_write_is_refused(admission,section):
    owner,request,token=actual(admission);before=owner.store.audit()
    with pytest.raises(PermissionError):
        owner.store.transact_objects('FAKE','bypass',[(section,'fake')],
            lambda state:state.setdefault(section,{}).update(fake={}),expected=5)
    assert owner.store.audit()==before


def test_final_controller_expiry_rolls_back_every_budget_object(admission,monkeypatch):
    owner,request,token=actual(admission);before=owner.store.audit();commit=owner.store._commit
    def expire(*args,**kwargs):
        result=commit(*args,**kwargs)
        monkeypatch.setattr(owner.controller,'monotonic_ns',lambda:1000*10**9)
        return result
    monkeypatch.setattr(owner.store,'_commit',expire)
    with pytest.raises(Conflict):owner.record(request,token)
    assert owner.store.audit()==before and owner._active is None and owner.controller._token_active is None


@pytest.mark.parametrize('action',['MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'])
def test_rolled_back_old_held_head_cannot_reuse_exposure(admission,action):
    owner,request,token=actual(admission);owner.record(request,token)
    old=deepcopy(owner.store.get(SECTIONS[2],reservation_key(request)))
    owner.record(cleanup(request,action),token)
    with owner.store.connect() as db:
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',
            (canonical(old).decode(),SECTIONS[2],reservation_key(request)))
    with pytest.raises(Conflict,match='indexed tip'):
        owner.record(cleanup(request,'CANCEL_BEFORE_RUNTIME',7,'reuse'),token)
    assert owner.store.version()==7


@pytest.mark.parametrize('damage',['entry_hash','wrong_scope','wrong_reservation','noncanonical','duplicate_key'])
def test_original_metadata_corruption_refuses_all_closure(admission,damage):
    owner,request,token=actual(admission);owner.record(request,token);store=owner.store;key=entry_key(request)
    with store.connect() as db:
        original=db.execute('SELECT input_versions FROM events WHERE idempotency_key=?',(key,)).fetchone()[0]
        inputs=json.loads(original)
        if damage=='entry_hash':inputs['budget_entry_hash']='sha256:'+'0'*64
        elif damage=='wrong_scope':inputs['budget_goal_account_key']='other'
        elif damage=='wrong_reservation':inputs['budget_reservation_id']='other'
        raw=canonical(inputs).decode()
        if damage=='noncanonical':raw=json.dumps(inputs,indent=2)
        elif damage=='duplicate_key':raw=raw[:-1]+',"budget_reservation_id":"other"}'
        trigger=db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET input_versions=? WHERE idempotency_key=?',(raw,key))
        db.execute(trigger);db.execute('UPDATE snapshot_due SET due_version=6')
    for operation in (store.audit,store.snapshot,store.recover,lambda:owner.record(request,token)):
        with pytest.raises(ValueError):operation()
    assert maintain(store) is False


@pytest.mark.parametrize('damage',['whole_domain','nonlatest_entry','extra_head'])
def test_rehashed_snapshot_cannot_omit_or_invent_budget_history(admission,damage):
    owner,request,token=actual(admission);owner.record(request,token)
    owner.record(cleanup(request,'MARK_UNKNOWN'),token);state=owner.store.audit()
    if damage=='whole_domain':
        for section in SECTIONS:state.pop(section)
    elif damage=='nonlatest_entry':del state[SECTIONS[0]][entry_key(request)]
    else:
        head=deepcopy(next(iter(state[SECTIONS[2]].values())));head['reservation_id']='orphan'
        state[SECTIONS[2]]['orphan']=head
    raw=canonical(state)
    with owner.store.connect() as db:
        db.execute('INSERT INTO snapshots VALUES(?,?,?)',(7,raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises(ValueError):owner.store.recover()


def test_old_snapshot_new_tail_and_controller_revision_preserve_exposure(admission):
    owner,request,token=actual(admission);owner.record(request,token);owner.store.snapshot()
    renewed=owner.controller.renew(token,'renew-after-budget',expected_version=6)
    next_request={**request,'idempotency_key':'reserve-new-controller','expected_state_version':7}
    owner.record(next_request,renewed['token']);state=owner.store.audit()
    assert state==owner.store.replay()==Store(owner.store.root).recover()
    assert state[SECTIONS[1]][account_key(scope(request))]['balance']['wall_seconds']['reserved']==2
    with owner.store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=8')
    assert maintain(owner.store) is True
    assert owner.store.recover()==state


def test_last_budget_quota_race_has_one_reservation_and_one_denial(admission):
    owner,request,token=actual(admission,239);owner.record(request,token)
    barrier=threading.Barrier(2);outcomes=[]
    def compete(name):
        command={**request,'idempotency_key':name,'expected_state_version':6,'amount':{**zero(),'wall_seconds':1}}
        barrier.wait()
        try:result=owner.record(command,token)
        except Conflict:
            command['expected_state_version']=owner.store.version();result=owner.record(command,token)
        outcomes.append(result['entry']['decision'])
    threads=[threading.Thread(target=compete,args=(name,)) for name in ('race-a','race-b')]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=10);assert not thread.is_alive()
    assert sorted(outcomes)==['DENIED','HELD'] and owner.store.version()==8
    assert owner.store.audit()==owner.store.replay()


@pytest.mark.parametrize('damage',['index','head','consent','stop'])
def test_changes_after_final_controller_check_roll_back_budget(admission,monkeypatch,damage):
    owner,request,token=actual(admission);before=owner.store.audit();check=owner.controller.check_token_in_transaction;seen=[0]
    def change(db,passed,budget):
        result=check(db,passed,budget)
        if db.execute('SELECT 1 FROM projection WHERE section=? AND object_key=?',(SECTIONS[0],entry_key(request))).fetchone():
            seen[0]+=1
            if seen[0]==2:
                if damage=='index':db.execute('DROP INDEX events_budget_reservation_tip')
                elif damage=='head':
                    db.execute('DELETE FROM projection WHERE section=?',(SECTIONS[2],))
                elif damage=='consent':
                    late=timestamp(admission[4]['sources']['expires_at'])
                    monkeypatch.setattr(owner.controller,'clock',lambda:late)
                else:monkeypatch.setattr('rlflow.hybrid_controller_service.stopped',lambda *args:True)
        return result
    monkeypatch.setattr(owner.controller,'check_token_in_transaction',change)
    with pytest.raises(Conflict):owner.record(request,token)
    assert seen[0]>=2 and owner.store.audit()==before and owner._active is None


@pytest.mark.parametrize('action',['MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'])
def test_expired_policy_and_new_controller_do_not_reset_or_block_cleanup(admission,action):
    owner,request,token=actual(admission);reserved=owner.record(request,token)['entry']
    late=timestamp(reserved['policy_source']['expires_at'])+timedelta(seconds=1)
    store=Store(owner.store.root);old=owner.preparation
    prep=PreparationService(store,owner.registry,old.builder,old.adapter,project_id=owner.project_id,
        data_mode=owner.data_mode,store_epoch=owner.store_epoch,clock=lambda:late)
    control=ControllerService(store,owner.registry,project_id=owner.project_id,data_mode=owner.data_mode,
        store_epoch=owner.store_epoch,clock=lambda:late,monotonic_ns=lambda:10**15)
    acquired=control.acquire('new-owner-after-expiry',expected_version=6)
    assert acquired['fact']['controller_epoch']==2
    fresh=BudgetService(store,owner.registry,control,prep)
    assert fresh.record(cleanup(request,action,7),acquired['token'])['entry']['decision']==(
        'UNKNOWN' if action=='MARK_UNKNOWN' else 'CANCELLED')
    state=store.audit();assert state==store.replay()
    assert len(state[SECTIONS[1]])==1
    assert state[SECTIONS[1]][account_key(scope(request))]['balance']['wall_seconds']['reserved']==(
        1 if action=='MARK_UNKNOWN' else 0)
    with pytest.raises(Conflict):
        fresh.record({**request,'idempotency_key':'expired-reserve','expected_state_version':8},acquired['token'])
    assert store.version()==8


@pytest.mark.parametrize('damage',['copied_token','purpose','scope','stale_version','bool_amount'])
def test_forged_or_stale_reservation_does_not_write(admission,damage):
    owner,request,token=actual(admission);before=owner.store.audit()
    if damage=='copied_token':token=ControllerToken(token.key,token.raw)
    elif damage=='purpose':request['purpose']='FINAL_VALIDATION'
    elif damage=='scope':request['project_id']='other'
    elif damage=='stale_version':request['expected_state_version']=4
    else:request['amount']['wall_seconds']=True
    with pytest.raises((ValueError,PermissionError)):owner.record(request,token)
    assert owner.store.audit()==before and owner._active is None


def test_missing_current_goal_head_cannot_initialize_fresh_budget(admission):
    owner,request,token=actual(admission);owner.record(request,token)
    with owner.store.connect() as db:
        db.execute('DELETE FROM projection WHERE section=? AND object_key=?',
            (SECTIONS[1],account_key(scope(request))))
    with pytest.raises(Conflict,match='head missing'):
        owner.record({**request,'idempotency_key':'reset','expected_state_version':6},token)
    assert owner.store.version()==6


@pytest.mark.parametrize('damage',['mono','utc','stop'])
@pytest.mark.parametrize('action',['RESERVE','MARK_UNKNOWN','CANCEL_BEFORE_RUNTIME'])
def test_last_callback_read_cannot_outlive_actual_controller(admission,monkeypatch,damage,action):
    owner,request,token=actual(admission)
    if action!='RESERVE':
        owner.record(request,token);request=cleanup(request,action)
    before=owner.store.audit();point=owner._point;seen=[0]
    def last_read(db,key,budget):
        value=point(db,key,budget)
        if key==entry_key(request):
            seen[0]+=1
            # postbody _point is first; final owned callback is second.
            if seen[0]==2:
                if damage=='mono':monkeypatch.setattr(owner.controller,'monotonic_ns',lambda:1000*10**9)
                elif damage=='utc':
                    late=timestamp(json.loads(token.raw)['expires_at'])
                    monkeypatch.setattr(owner.controller,'clock',lambda:late)
                else:monkeypatch.setattr('rlflow.hybrid_controller_service.stopped',lambda *args:True)
        return value
    monkeypatch.setattr(owner,'_point',last_read)
    with pytest.raises(Conflict):owner.record(request,token)
    assert seen[0]==2 and owner.store.audit()==before
    assert owner._active is None and owner.controller._token_active is None


def test_large_legal_prepared_schema_actual_budget_closure(owned,monkeypatch):
    prep,preparation_request,clock,_=owned
    schema={'type':'object','description':'budget literal capacity fixture',
        'examples':[{'$rlflow_blob':0} for _ in range(180000)]}
    assert len(canonical(schema))<4*1024**2
    monkeypatch.setattr('rlflow.execution_adapter.role_schema',lambda role:schema)
    prepared=prep.prepare(preparation_request)
    control=ControllerService(prep.store,prep.registry,project_id=prep.project_id,data_mode=prep.data_mode,
        store_epoch=prep.store_epoch,clock=lambda:clock[0],monotonic_ns=lambda:100*10**9)
    acquired=control.acquire('large-controller',expected_version=4)
    owner=BudgetService(prep.store,prep.registry,control,prep)
    from rlflow.hybrid_preparation import intent_key
    request={'project_id':prep.project_id,'data_mode':prep.data_mode,'store_epoch':prep.store_epoch,
        'goal_ref':preparation_request['goal_ref'],'idempotency_key':'large-reserve','expected_state_version':5,
        'action':'RESERVE','preparation_intent_key':intent_key(preparation_request),
        'amount':{**zero(),'wall_seconds':1},'purpose':'EXECUTION'}
    result=owner.record(request,acquired['token']);assert result['entry']['decision']=='HELD'
    assert owner.record(request,acquired['token'])=={**result,'duplicate':True}
    assert owner.record(cleanup(request,'MARK_UNKNOWN'),acquired['token'])['entry']['decision']=='UNKNOWN'
    state=owner.store.audit();owner.store.snapshot();assert owner.store.recover()==state==owner.store.replay()
    with owner.store.connect() as db:
        assert db.execute('SELECT MAX(length(data)) FROM blobs').fetchone()[0]>16*1024**2
        db.execute('UPDATE snapshot_due SET due_version=7')
    assert maintain(owner.store,seconds=30,max_bytes=64*1024**2,max_nodes=8*1024**2)
    assert owner.store.recover()==state and prepared['result']['status']=='PREPARED'


def test_final_sample_checks_consent_even_when_controller_remains_live(admission,monkeypatch):
    owner,request,token=actual(admission)
    early=timestamp(admission[4]['sources']['evaluated_at'])+timedelta(seconds=10)
    monkeypatch.setattr(owner.controller,'clock',lambda:early)
    token=owner.controller.renew(token,'long-controller',expected_version=5,ttl_seconds=60)['token']
    request['expected_state_version']=6;before=owner.store.audit();live=owner.controller._owner_live;seen=[0]
    def change_after_final_owner():
        live()
        if inspect.currentframe().f_back.f_code.co_name=='_final_token_freshness':
            seen[0]+=1
            late=timestamp(admission[4]['sources']['expires_at'])
            assert late<timestamp(json.loads(token.raw)['expires_at'])
            monkeypatch.setattr(owner.controller,'clock',lambda:late)
    monkeypatch.setattr(owner.controller,'_owner_live',change_after_final_owner)
    with pytest.raises(Conflict,match='consent expired at final'):owner.record(request,token)
    assert seen[0]==1 and owner.store.audit()==before


def approve_proposal(owner,proposal,key,monkeypatch):
    store=owner.store;approval=store._hybrid_authority_service
    pair=ControlServices(store._hybrid_draft_service,approval)
    app=create_app([Project(owner.project_id,str(store.root),owner.data_mode)],approval.auth,
        origin=ORIGIN,control_services={owner.project_id:pair})
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client)
        result=post(client,submit_payload(proposal,store.version()),headers,key+'-draft')
        assert result.status_code==202,result.text
        view=prepare(client,proposal,headers)
        result=post(client,approve_payload(view),headers,key+'-approve')
        assert result.status_code==202,result.text
    from rlflow.hybrid_authority import SECTIONS as AUTHORITY
    fact=store.get(AUTHORITY[0],result.json()['result']['fact_key']);now=timestamp(fact['approved_at'])
    monkeypatch.setattr(owner.preparation,'clock',lambda:now)
    monkeypatch.setattr(owner.controller,'clock',lambda:now)
    return head_key(owner.project_id,owner.data_mode,proposal['goal_id'])


def next_preparation(owner,request,goal_ref,key):
    original=owner.store.get(PREPARATION[0],request['preparation_intent_key'])['request']
    command={**original,'goal_ref':goal_ref,'idempotency_key':key}
    owner.preparation.prepare(command)
    return intent_key(command)


def test_approved_revision_lower_limit_preserves_exposure_and_denial(admission,monkeypatch):
    owner,request,token=actual(admission,240);result=owner.record(request,token)['entry']
    proposal=deepcopy(owner.store.get(GOALS[0],result['policy_source']['contract_key'])['contract']['proposal'])
    proposal['contract_version']=2;proposal['budget']['wall_seconds']=100
    proposal['stop_rules']=['fixture '+('x'*3992)]*55
    goal_ref=approve_proposal(owner,proposal,'lower',monkeypatch)
    ik=next_preparation(owner,request,goal_ref,'lower-preparation')
    command={**request,'idempotency_key':'lower-reserve','expected_state_version':owner.store.version(),
        'preparation_intent_key':ik,'amount':{**zero(),'wall_seconds':1}}
    result=owner.record(command,token)['entry'];assert result['decision']=='DENIED'
    balance=owner.store.get(SECTIONS[1],account_key(scope(request)))['balance']['wall_seconds']
    assert balance['limit']==100 and balance['reserved']==240 and balance['overrun']==140
    assert owner.store.audit()==owner.store.replay()
    owner.record(cleanup(request,'CANCEL_BEFORE_RUNTIME',owner.store.version()),token)
    balance=owner.store.get(SECTIONS[1],account_key(scope(request)))['balance']['wall_seconds']
    assert balance['limit']==100 and balance['reserved']==balance['overrun']==0
    state=owner.store.audit();owner.store.snapshot();assert owner.store.recover()==state


def test_multiple_goals_share_exact_project_exposure_without_invented_cap(admission,monkeypatch):
    owner,request,token=actual(admission);result=owner.record(request,token)['entry']
    proposal=deepcopy(owner.store.get(GOALS[0],result['policy_source']['contract_key'])['contract']['proposal'])
    proposal['goal_id']='budget-second-goal'
    goal_ref=approve_proposal(owner,proposal,'other-goal',monkeypatch)
    ik=next_preparation(owner,request,goal_ref,'other-preparation')
    command={**request,'goal_ref':goal_ref,'idempotency_key':'other-reserve',
        'expected_state_version':owner.store.version(),'preparation_intent_key':ik,'amount':{**zero(),'wall_seconds':2}}
    owner.record(command,token)
    project=owner.store.objects(SECTIONS[3])[0][1]
    assert project['reserved']['wall_seconds']==3 and 'limit' not in project
    owner.record(cleanup(request,'CANCEL_BEFORE_RUNTIME',owner.store.version()),token)
    state=owner.store.audit();assert state==owner.store.replay()
    assert len(state[SECTIONS[1]])==2 and next(iter(state[SECTIONS[3]].values()))['reserved']['wall_seconds']==2


def test_observation_epoch_change_keeps_unknown_budget_exposure(admission):
    owner,request,token=actual(admission);owner.record(request,token)
    epoch=rotate_epoch(owner.store)
    store=Store(owner.store.root);old=owner.preparation;now=owner.controller.clock()
    prep=PreparationService(store,owner.registry,old.builder,old.adapter,project_id=owner.project_id,
        data_mode=owner.data_mode,store_epoch=epoch,clock=lambda:now)
    controller=ControllerService(store,owner.registry,project_id=owner.project_id,data_mode=owner.data_mode,
        store_epoch=epoch,clock=lambda:now,monotonic_ns=lambda:100*10**9)
    acquired=controller.acquire('observation-new-epoch',expected_version=6)
    assert acquired['fact']['reason']=='NEW_STORE_EPOCH'
    fresh=BudgetService(store,owner.registry,controller,prep)
    command={**cleanup(request,'MARK_UNKNOWN',7),'store_epoch':epoch}
    assert fresh.record(command,acquired['token'])['entry']['decision']=='UNKNOWN'
    state=store.audit();assert state==store.replay()
    assert len(state[SECTIONS[1]])==1
    balance=state[SECTIONS[1]][account_key(scope(request))]['balance']['wall_seconds']
    assert balance['reserved']==balance['unknown_exposure']==1
    with pytest.raises(Conflict):owner.record({**request,'idempotency_key':'old-epoch','expected_state_version':8},token)
