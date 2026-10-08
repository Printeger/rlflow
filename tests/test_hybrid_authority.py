from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json

import pytest

from rlflow.hybrid_authority import ApprovalService, SECTIONS, command_key, fact_key, _head, validate_complete
from rlflow.hybrid_goals import propose, head_key, SECTIONS as GOALS, digest
from rlflow.hybrid_registry import Registry
from rlflow.observation import enable
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Store, Conflict
from rlflow.web_auth import Principal, AuthStore, Credential
from rlflow.hybrid_protocol import ProtocolError
from tests.test_hybrid_registry import bound, catalog

ORIGIN='http://127.0.0.1:8765'
PHRASE='synthetic approval service fixture passphrase'


def setup(tmp_path):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    config=catalog();registry,p=bound(config)
    actor=Principal('fixture_operator','agent',{'operator'},{'project_fixture'})
    propose(store,p,principal=actor,project_id='project_fixture',data_mode='fixture',idempotency_key='draft',expected_revision=0)
    human=Principal('fixture_human','human',{'approver'},{'project_fixture'})
    mono=[1.0];utc=[datetime(2026,10,9,tzinfo=timezone.utc)]
    auth=AuthStore([Credential.create(human,PHRASE)],ttl=100,clock=lambda:mono[0])
    token,access=auth.login(human.id,PHRASE)
    service=ApprovalService(store,auth,registry,project_id='project_fixture',data_mode='fixture',origin=ORIGIN,clock=lambda:utc[0])
    args={'token':token,'csrf':access.csrf,'origin':ORIGIN}
    return store,service,args,p,actor,mono,utc


def prepare(service,args,p):return service.prepare(**args,goal_id=p['goal_id'],ttl_seconds=60)


def test_real_fixture_session_consent_is_immutable_and_not_execution(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    old=deepcopy(store.get(GOALS[0],store.get(GOALS[1],head_key('project_fixture','fixture',p['goal_id']))['contract_key']))
    view=prepare(service,args,p);result=service.approve(view['confirmation'],**args,idempotency_key='approve1')
    assert result['duplicate'] is False and result['execution_status']=='LEASE_VALIDATION_PENDING'
    assert result['fact']['request']['actor']=={'id':'fixture_human','kind':'human'}
    assert result['fact']['expires_at']=='2026-10-09T00:01:00Z'
    assert store.get(GOALS[0],store.get(GOALS[1],head_key('project_fixture','fixture',p['goal_id']))['contract_key'])==old
    assert not store.objects('sessions') and not store.objects('tasks') and not store.objects('approvals')
    assert not set(SECTIONS)&set(store.view())
    assert store.audit()==store.replay()==store.recover()


def test_retry_after_cache_loss_and_expiry_returns_original_without_extension(tmp_path):
    store,service,args,p,_,_,utc=setup(tmp_path)
    c=prepare(service,args,p)['confirmation'];first=service.approve(c,**args,idempotency_key='same')
    service._confirmations.clear();utc[0]+=timedelta(days=1)
    again=service.approve(c,**args,idempotency_key='same')
    assert again=={**first,'duplicate':True}
    store.snapshot();assert store.recover()==store.audit()==store.replay()
    assert len(store.objects(SECTIONS[0]))==1
    with pytest.raises(Conflict,match='stale'):service.approve(c,**args,idempotency_key='different')


def test_revocation_appends_fact_and_snapshot_preserves_expired_consent(tmp_path):
    store,service,args,p,_,_,utc=setup(tmp_path)
    result=service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve')
    original=deepcopy(result['fact']);utc[0]+=timedelta(days=2)
    kwargs={**args,'goal_id':p['goal_id'],'approval_key':result['fact_key'],'expected_version':store.version(),
            'expected_authority_revision':1,'reason':'fixture explicit revoke','idempotency_key':'revoke'}
    rev=service.revoke(**kwargs)
    assert rev['execution_status']=='REVOKED' and store.get(SECTIONS[0],result['fact_key'])==original
    assert service.revoke(**kwargs)=={**rev,'duplicate':True}
    store.snapshot();assert store.recover()==store.audit()==store.replay()


@pytest.mark.parametrize('bad',['origin','csrf','expired','viewer','bearer','principal_json'])
def test_untrusted_authentication_cannot_confirm(tmp_path,bad):
    store,service,args,p,_,mono,_=setup(tmp_path);before=store.audit()
    c=prepare(service,args,p)['confirmation']
    if bad=='origin':args['origin']='http://evil.invalid'
    elif bad=='csrf':args['csrf']='forged_not_actual_csrf_token'
    elif bad=='expired':mono[0]=101.0
    elif bad=='viewer':
        viewer=Principal('viewer','human',{'viewer'},{'project_fixture'})
        other=AuthStore([Credential.create(viewer,PHRASE)])
        token,access=other.login(viewer.id,PHRASE);args.update(token=token,csrf=access.csrf)
    elif bad=='bearer':args['token']=service.auth.issue_bearer(Principal('viewer','human',{'viewer'},{'project_fixture'}),ttl=50)[0]
    else:args['token']={'kind':'human','roles':['approver']}
    with pytest.raises(PermissionError):service.approve(c,**args,idempotency_key='bad')
    assert store.audit()==before


@pytest.mark.parametrize('change',['new_draft','unrelated_version','epoch','policy'])
def test_confirmation_drift_denied_in_actual_writer(tmp_path,change):
    store,service,args,p,actor,_,_=setup(tmp_path);c=prepare(service,args,p)['confirmation']
    if change=='new_draft':
        p['contract_version']=2;p['objective']+=' changed'
        propose(store,p,principal=actor,project_id='project_fixture',data_mode='fixture',idempotency_key='draft2',expected_revision=1)
    elif change=='unrelated_version':store.transact_objects('USAGE_OBSERVED','other',[('usage','other')],lambda s:s.setdefault('usage',{}).update(other={}))
    elif change=='epoch':
        with store.connect() as db:db.execute("UPDATE observation_meta SET store_epoch='store_fixture_changed'")
    else:
        config=json.loads(service.registry._raw);config['project_policy']['configuration']['changed']=True
        # Simulate protected service replacement, not mutation of frozen registry bytes.
        service.registry=Registry(config);store._hybrid_registry=service.registry
    before=store.audit()
    with pytest.raises((Conflict,ProtocolError)):service.approve(c,**args,idempotency_key='drift')
    assert store.audit()==before


def test_same_confirmation_cannot_create_two_facts_with_different_keys(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path);c=prepare(service,args,p)['confirmation']
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(service.approve,c,**args,idempotency_key=key) for key in ('a','b')]
        results=[]
        for future in futures:
            try:results.append(future.result(timeout=3))
            except (Conflict,PermissionError):pass
    assert len(results)==1 and len(store.objects(SECTIONS[0]))==1
    assert store.audit()==store.replay()


def test_failed_commit_keeps_confirmation_retryable(tmp_path,monkeypatch):
    store,service,args,p,_,_,_=setup(tmp_path);c=prepare(service,args,p)['confirmation'];before=store.audit()
    from rlflow import observation
    original=observation.commit
    def failing(*args,**kwargs):raise RuntimeError('fixture commit failure')
    monkeypatch.setattr(observation,'commit',failing)
    with pytest.raises(RuntimeError):service.approve(c,**args,idempotency_key='retry')
    assert store.audit()==before and c['id'] in service._confirmations
    assert not service._active_writes and not service.auth._approval_guards
    monkeypatch.setattr(observation,'commit',original)
    assert service.approve(c,**args,idempotency_key='retry')['duplicate'] is False


def test_generic_writer_cannot_impersonate_approved_fact_or_guard(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path);result=service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='real')
    receipt=store.objects(SECTIONS[3])[0][1]
    before=store.audit()
    class ForgedGuard:
        def check(self):return service.auth.resolve(args['token'],'session')
    @contextmanager
    def forged():yield ForgedGuard()
    for factory in (None,forged):
        with pytest.raises(PermissionError):
            store.transact_objects('HYBRID_GOAL_APPROVED',command_key(receipt['request']),[],lambda s:None,
                object_id=digest(receipt['request']),producer='hybrid-core',_authorization=factory)
    with pytest.raises(PermissionError):
        store.transact_objects('FORGED','overwrite',[(SECTIONS[0],result['fact_key'])],
            lambda s:s[SECTIONS[0]][result['fact_key']].update(approved_at='2099-01-01T00:00:00Z',expires_at='2099-01-01T00:01:00Z'),producer='hybrid-core')
    assert store.audit()==before


def test_legacy_whole_state_duplicate_or_noop_cannot_bypass_authority_guard(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='real')
    key,receipt=store.objects(SECTIONS[3])[0];before=store.audit()
    for event_key in (key,'new_noop'):
        with pytest.raises(PermissionError):store.transact('HYBRID_GOAL_APPROVED',event_key,lambda s:None,
            object_id=receipt['request_hash'],producer='hybrid-core')
    assert store.audit()==before


def test_periodic_snapshot_validates_historical_witness_after_config_change(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve')
    config=json.loads(service.registry._raw);config['project_policy']['configuration']['changed']=True
    service.registry=Registry(config)
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=?',(store.version(),))
    assert maintain(store,seconds=5)
    assert store.recover()==store.audit()==store.replay()


def test_snapshot_corruption_of_registry_witness_or_original_receipt_denied(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path);service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve')
    from rlflow.hybrid_authority import validate_complete
    state=store.audit();fk=next(iter(state[SECTIONS[0]]))
    damaged=deepcopy(state);damaged[SECTIONS[0]][fk]['registry_witness']['runtime_profile']['changed']=True
    with pytest.raises((Conflict,ProtocolError)):validate_complete(damaged,('project_fixture','fixture'),lambda k:None)
    damaged=deepcopy(state);ck=next(iter(damaged[SECTIONS[3]]));damaged[SECTIONS[3]][ck]['accepted_state_version']+=1
    with pytest.raises((Conflict,ProtocolError)):validate_complete(damaged,('project_fixture','fixture'),lambda k:None)


def test_actual_session_and_served_nonce_cannot_forge_fact_outside_service(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    c=prepare(service,args,p)['confirmation']
    request={'action':'approve','project_id':'project_fixture','data_mode':'fixture','actor':{'id':'fixture_human','kind':'human'},
             'idempotency_key':'forged_future','confirmation':c}
    fk,ck=fact_key(request),command_key(request);hk=head_key('project_fixture','fixture',p['goal_id'])
    fact={'request':request,'approved_at':'2099-01-01T00:00:00Z','expires_at':'2099-01-01T00:01:00Z',
          'registry_witness':json.loads(service.registry._raw),'authority_revision':1,'previous_fact_key':None,'previous_fact_hash':None}
    def forge(state):
        state.setdefault(SECTIONS[0],{})[fk]=fact
        state.setdefault(SECTIONS[2],{})[hk]=_head(request,SECTIONS[0],fk,fact)
        state.setdefault(SECTIONS[3],{})[ck]={'request':request,'request_hash':digest(request),'fact_section':SECTIONS[0],
            'fact_key':fk,'fact_hash':digest(fact),'accepted_state_version':state['version']+1}
    before=store.audit()
    with pytest.raises(PermissionError,match='service-staged'):
        store.transact_objects('HYBRID_GOAL_APPROVED',ck,[(SECTIONS[0],fk),(SECTIONS[2],hk),(SECTIONS[3],ck)],forge,
            expected=c['expected_version'],object_id=digest(request),producer='hybrid-core',
            _authorization=lambda:service.auth.approval_guard(args['token'],project_id='project_fixture',csrf=args['csrf']))
    assert store.audit()==before


def shifted_snapshot(store):
    state=store.audit();fk=next(iter(state[SECTIONS[0]]));fact=state[SECTIONS[0]][fk]
    fact['approved_at']='2099-01-01T00:00:00Z';fact['expires_at']='2099-01-01T00:01:00Z'
    for receipt in state[SECTIONS[3]].values():
        if receipt['fact_key']==fk:receipt['fact_hash']=digest(fact)
    hk=head_key('project_fixture','fixture',fact['request']['confirmation']['goal_id'])
    state[SECTIONS[2]][hk]['fact_hash']=digest(fact)
    return state


def test_snapshot_shifted_lifetime_and_self_hashes_still_rejects_original_source(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve')
    damaged=shifted_snapshot(store)
    with store.connect() as db:
        with pytest.raises(Conflict,match='source'):validate_complete(damaged,('project_fixture','fixture'),lambda k:store._authority_event(db,k))
    from rlflow.store import canonical
    import hashlib
    raw=canonical(damaged)
    with store.connect() as db:db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)',(damaged['version'],raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises(Conflict,match='source'):store.recover()


def test_periodic_snapshot_shifted_projection_fails_without_clearing_due(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path)
    service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve')
    store.snapshot();damaged=shifted_snapshot(store)
    from rlflow.store import canonical
    with store.connect() as db:
        for section in SECTIONS:
            for key,value in damaged.get(section,{}).items():
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(value).decode(),section,key))
        db.execute('UPDATE snapshot_due SET due_version=?',(damaged['version'],))
        previous=tuple(db.execute('SELECT * FROM snapshots').fetchone())
    assert maintain(store,seconds=5) is False
    with store.connect() as db:
        assert tuple(db.execute('SELECT * FROM snapshots').fetchone())==previous
        assert db.execute('SELECT due_version FROM snapshot_due').fetchone()[0]==damaged['version']


def test_concurrent_confirmation_capacity_is_atomic(tmp_path,monkeypatch):
    store,service,args,p,_,_,_=setup(tmp_path)
    view=prepare(service,args,p);cached=deepcopy(service._confirmations[view['confirmation']['id']])
    with service._confirmation_lock:service._confirmations={f'fixture_cache_{i}':deepcopy(cached) for i in range(127)}
    import threading
    from rlflow import hybrid_authority
    barrier=threading.Barrier(2);counter=iter(('a'*64,'b'*64))
    def next_nonce(*args):
        value=next(counter);barrier.wait(timeout=2)
        return value
    monkeypatch.setattr(hybrid_authority.secrets,'token_hex',next_nonce)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(prepare,service,args,p) for _ in range(2)]
        success=[];failures=[]
        for future in futures:
            try:success.append(future.result(timeout=3))
            except ProtocolError as error:failures.append(error)
    assert len(success)==len(failures)==1 and len(service._confirmations)==128
    assert success[0]['confirmation']['id'] in service._confirmations


@pytest.mark.parametrize('clock_kind',['nonce','absolute'])
def test_confirmation_expiry_after_event_preparation_rolls_back(tmp_path,monkeypatch,clock_kind):
    store,service,args,p,_,mono,utc=setup(tmp_path);view=prepare(service,args,p);before=store.audit()
    tables=('observation_meta','observation_events','observation_projection','observation_counters')
    def public_rows():
        with store.connect() as db:return {table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}
    public_before=public_rows()
    if clock_kind=='nonce':service._confirmations[view['confirmation']['id']]['expires']=2.0
    original=store._commit
    def expire_after_staging(*a,**kw):
        version=original(*a,**kw)
        if clock_kind=='nonce':mono[0]=2.0
        else:utc[0]+=timedelta(seconds=60)
        return version
    monkeypatch.setattr(store,'_commit',expire_after_staging)
    with pytest.raises(PermissionError):service.approve(view['confirmation'],**args,idempotency_key='expired')
    assert store.audit()==before and not service._active_writes
    assert public_rows()==public_before and not service.auth._approval_guards
    assert service.auth.resolve(args['token'],'session').principal.id=='fixture_human'


def test_confirmation_is_bound_to_session_not_only_human_subject(tmp_path):
    store,service,args,p,_,_,_=setup(tmp_path);c=prepare(service,args,p)['confirmation'];before=store.audit()
    token,access=service.auth.login('fixture_human',PHRASE)
    with pytest.raises(PermissionError):service.approve(c,token=token,csrf=access.csrf,origin=ORIGIN,idempotency_key='other_session')
    assert store.audit()==before and c['id'] in service._confirmations and not service._active_writes
    assert service.approve(c,**args,idempotency_key='original_session')['duplicate'] is False


def test_reapproval_after_revocation_preserves_chain_and_original_times(tmp_path):
    store,service,args,p,_,_,utc=setup(tmp_path)
    first=service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve1')
    revoked=service.revoke(**args,goal_id=p['goal_id'],approval_key=first['fact_key'],expected_version=store.version(),
        expected_authority_revision=1,reason='fixture revoke',idempotency_key='revoke')
    utc[0]+=timedelta(seconds=10)
    second=service.approve(prepare(service,args,p)['confirmation'],**args,idempotency_key='approve2')
    assert second['fact']['authority_revision']==3 and second['fact']['previous_fact_key']==revoked['fact_key']
    assert store.get(SECTIONS[0],first['fact_key'])==first['fact']
    assert second['execution_enabled'] is False
    store.snapshot();assert store.recover()==store.audit()==store.replay()
    damaged=store.audit();fact=damaged[SECTIONS[1]][revoked['fact_key']];fact['revoked_at']='2099-01-01T00:00:00Z'
    second_key=second['fact_key'];damaged[SECTIONS[0]][second_key]['previous_fact_hash']=digest(fact)
    for receipt in damaged[SECTIONS[3]].values():
        receipt['fact_hash']=digest(damaged[receipt['fact_section']][receipt['fact_key']])
    hk=head_key('project_fixture','fixture',p['goal_id']);damaged[SECTIONS[2]][hk]['fact_hash']=digest(damaged[SECTIONS[0]][second_key])
    with store.connect() as db:
        with pytest.raises(Conflict,match='source'):validate_complete(damaged,('project_fixture','fixture'),lambda k:store._authority_event(db,k))
