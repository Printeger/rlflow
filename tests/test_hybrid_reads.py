from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from rlflow.hybrid_goals import SECTIONS as GOALS, head_key, revision_key, validate_complete
from rlflow.hybrid_authority import SECTIONS as AUTHORITY
from rlflow.hybrid_reads import HybridReader, ReadBudget
from rlflow.hybrid_protocol import validate
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Conflict, canonical
from rlflow.web_auth import Principal
from tests.test_hybrid_control_api import setup, login, post, prepare, approve_payload, submit_payload, BASE, ORIGIN
from tests.test_hybrid_registry import catalog


def ref(p):return head_key(p['project_id'],p['data_mode'],p['goal_id'])


def reader(pair,clock=None):
    d=pair.drafts
    return HybridReader(d.store,project_id=d.project_id,data_mode=d.data_mode,store_epoch=d.store_epoch,clock=clock)


def test_list_is_small_summary_private_review_proves_source_and_no_business_write(tmp_path):
    store,auth,p,app,pair,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        before=store.replay();page=client.get(BASE+'/goals')
        assert page.status_code==200,page.text
        item=page.json()['items'][0]
        assert item['goal_ref']==ref(p) and item['source_coverage']=='HEAD_ONLY'
        assert not any(v in page.text for v in (p['objective'],'submitted_by','proposal','writable_paths','registry_witness'))
        response=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert response.status_code==200,response.text
        view=response.json()
        assert view['contract']['proposal']==p and view['source_coverage']=='ORIGINAL_EVENT_VERIFIED'
        assert view['submitted_state_version']==1 and view['as_of_state_version']==1
        assert view['execution_enabled'] is False and view['authority'] is None
        assert 'source_command_key' not in response.text and 'registry_witness' not in response.text
        assert store.replay()==before


@pytest.mark.parametrize('principal',['viewer','operator','approver','both'])
def test_private_review_requires_either_explicit_human_role(tmp_path,principal):
    store,auth,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
        login(client,principal)
        assert client.get(BASE+'/goals').status_code==200
        response=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert response.status_code==(403 if principal=='viewer' else 200)
        if principal=='viewer':assert p['objective'] not in response.text


def test_bearer_and_unscoped_principal_cannot_read_full_proposal(tmp_path):
    store,auth,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
        token,_=auth.issue_bearer(Principal('probe','agent',{'viewer'},{'project_fixture'}),ttl=60)
        headers={'Authorization':'Bearer '+token}
        assert client.get(BASE+'/goals',headers=headers).status_code==200
        response=client.get(BASE+'/goals/'+ref(p)+'/review',headers=headers)
        assert response.status_code==403 and p['objective'] not in response.text
        other,_=auth.issue_bearer(Principal('other','agent',{'viewer'},{'elsewhere'}),ttl=60)
        assert client.get(BASE+'/goals',headers={'Authorization':'Bearer '+other}).status_code==404


@pytest.mark.parametrize('query',['limit=0','limit=51','limit=1&limit=2','limit=+2','limit=true','after=bad/path','extra=secret'])
def test_closed_page_queries(tmp_path,query):
    _,_,_,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        login(client)
        response=client.get(BASE+'/goals?'+query)
        assert response.status_code==400
        validate('Error',response.json())


def test_list_keyset_never_expands_contracts_or_scans_original_events(tmp_path,monkeypatch):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client)
        for i in range(4):
            proposal=deepcopy(p);proposal['goal_id']='fixture_goal_'+str(i)
            assert post(client,submit_payload(proposal,store.version()),headers,'draft_'+str(i)).status_code==202
        actual=ReadBudget.object;sections=[]
        def checked(self,section,key):
            sections.append(section)
            assert section in (GOALS[1],AUTHORITY[2])
            return actual(self,section,key)
        monkeypatch.setattr(ReadBudget,'object',checked)
        first=client.get(BASE+'/goals?limit=2').json()
        second=client.get(BASE+'/goals',params={'limit':2,'after':first['next_after']}).json()
        assert len(first['items'])==len(second['items'])==2 and second['next_after'] is None
        assert {r['goal_ref'] for r in first['items']}.isdisjoint(r['goal_ref'] for r in second['items'])
        assert sections


def test_recover_row_versions_do_not_rewrite_original_source_version(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        q=deepcopy(p);q['contract_version']=2;q['objective']+=' next revision'
        assert post(client,submit_payload(q,1),headers,'next').status_code==202
        store.snapshot();store.recover()
        with store.connect() as db:
            assert {r[0] for r in db.execute('SELECT DISTINCT version FROM projection')}=={2}
        view=client.get(BASE+'/goals/'+ref(p)+'/review').json()
        assert view['submitted_state_version']==2 and view['contract']['proposal']==q
        state=store.replay()
        with store.connect() as db:
            validate_complete(state,('project_fixture','fixture'),lambda k:store._goal_event(db,k),lambda k:store._goal_source(db,k))
        old=state[GOALS[0]][revision_key(p)]
        assert old['source_command_key']!=state[GOALS[0]][revision_key(q)]['source_command_key']


@pytest.mark.parametrize('damage',['timestamp','actor','pointer','remove_pointer','receipt','head'])
def test_rehashed_snapshot_cannot_forge_original_draft_objects(tmp_path,damage):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
    state=store.replay();record=state[GOALS[0]][revision_key(p)];ck=record['source_command_key']
    if damage=='timestamp':record['submitted_at']='2026-10-08T00:00:00Z'
    elif damage=='actor':record['submitted_by']['id']='another'
    elif damage=='pointer':record['source_command_key']='wrong_source'
    elif damage=='remove_pointer':record.pop('source_command_key');record['submitted_at']='2026-10-08T00:00:00Z'
    elif damage=='receipt':state[GOALS[2]][ck]['accepted_state_version']=2
    else:state[GOALS[1]][ref(p)]['contract_hash']='sha256:'+'0'*64
    raw=canonical(state);before=store.replay()
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)',(state['version'],raw,hashlib.sha256(raw).hexdigest()))
    with pytest.raises((ValueError,Conflict)):store.recover()
    assert store.replay()==before


def test_pointer_requires_callback_and_periodic_snapshot_keeps_due_on_corruption(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
    state=store.replay()
    with store.connect() as db:
        with pytest.raises(Conflict):validate_complete(state,('project_fixture','fixture'),lambda k:store._goal_event(db,k))
        record=state[GOALS[0]][revision_key(p)];record['submitted_at']='2026-10-08T00:00:00Z'
        db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(record).decode(),GOALS[0],revision_key(p)))
        db.execute('UPDATE snapshot_due SET due_version=1')
    assert maintain(store) is False
    with store.connect() as db:assert tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone())==(1,0)


def test_old_records_remain_partial_without_backfill_or_history_scan(tmp_path,monkeypatch):
    store,_,p,app,_,_,_=setup(tmp_path);actual=store._commit
    def historical(db,event_type,key,payload,*args,**kwargs):
        payload=deepcopy(payload)
        for section,objkey,value in payload['put']:
            if section==GOALS[0] and objkey:value.pop('source_command_key',None)
        return actual(db,event_type,key,payload,*args,**kwargs)
    monkeypatch.setattr(store,'_commit',historical)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'legacy').status_code==202
        before=store.replay();view=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert view.status_code==200,view.text
        assert view.json()['source_coverage']=='PARTIAL_NO_SOURCE_POINTER'
        assert view.json()['submitted_state_version'] is None
        store.snapshot();assert store.recover()==store.audit()==before
        assert 'source_command_key' not in store.get(GOALS[0],revision_key(p))


@pytest.mark.parametrize('damage',['malformed','missing_receipt','tampered_record','epoch'])
def test_source_faults_are_sanitized_503_not_client_validation(tmp_path,damage):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
        record=store.get(GOALS[0],revision_key(p))
        with store.connect() as db:
            if damage=='malformed':db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',('private_secret_invalid',GOALS[0],revision_key(p)))
            elif damage=='missing_receipt':db.execute('DELETE FROM projection WHERE section=? AND object_key=?',(GOALS[2],record['source_command_key']))
            elif damage=='epoch':db.execute("UPDATE observation_meta SET store_epoch='changed_epoch'")
            else:
                record['submitted_at']='2026-10-08T00:00:00Z'
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(record).decode(),GOALS[0],revision_key(p)))
        response=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert response.status_code==503,response.text
        assert 'private_secret' not in response.text and p['objective'] not in response.text
        validate('Error',response.json())


@pytest.mark.parametrize('stage',['body','final_meta'])
def test_logout_during_read_never_returns_private_body(tmp_path,monkeypatch,stage):
    _,auth,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        assert post(client,submit_payload(p),login(client),'draft').status_code==202
        token=client.cookies.get('rlflow_session')
        name='review' if stage=='body' else 'check_current';actual=getattr(HybridReader,name)
        def revoke(self,*args,**kwargs):
            result=actual(self,*args,**kwargs);auth.revoke(token);return result
        monkeypatch.setattr(HybridReader,name,revoke)
        response=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert response.status_code==401 and p['objective'] not in response.text


def test_fact_state_and_expiry_and_new_revision_are_separate_from_execution(tmp_path):
    store,_,p,app,pair,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        view=prepare(client,p,headers);approved=post(client,approve_payload(view),headers,'approve')
        assert approved.status_code==202
        fact=store.get(AUTHORITY[0],approved.json()['result']['fact_key'])
        now=[datetime.fromisoformat(fact['approved_at'].replace('Z','+00:00'))]
        r=reader(pair,clock=lambda:now[0]);a=r.review(ref(p))['authority']
        assert a['recorded_state']=='LEASE_VALIDATION_PENDING' and a['lifetime_status']=='UNEXPIRED'
        assert a['applies_to_current_contract'] and a['execution_enabled'] is False
        now[0]+=timedelta(seconds=61);assert r.review(ref(p))['authority']['lifetime_status']=='EXPIRED'
        q=deepcopy(p);q['contract_version']=2;q['objective']+=' revised'
        assert post(client,submit_payload(q,store.version()),headers,'next').status_code==202
        a=r.review(ref(p))['authority'];assert not a['applies_to_current_contract']
        revoke={'schema_version':'1.1','action':'revoke','target':{'kind':'approval','id':approved.json()['result']['fact_key']},
                'expected_version':store.version(),'parameters':{'goal_id':p['goal_id'],'expected_authority_revision':1,'reason':'fixture'}}
        assert post(client,revoke,headers,'revoke').status_code==202
        a=r.review(ref(p))['authority'];assert a['recorded_state']=='REVOKED' and a['revoked_at']
        assert a['lifetime_status']=='EXPIRED' and a['execution_enabled'] is False


def test_large_legal_goal_diff_and_literal_registry_review_remain_readable(tmp_path):
    config=catalog();config['runtime_profile']['configuration']={'metadata':[{'$rlflow_blob':0}]*13000}
    store,_,p,app,_,_,_=setup(tmp_path,config=config);p['stop_rules']=['fixture '+('x'*3992)]*55
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        q=deepcopy(p);q['contract_version']=2;q['stop_rules']=['fixture '+('y'*3992)]*55
        assert post(client,submit_payload(q,1),headers,'next').status_code==202
        view=prepare(client,q,headers);assert post(client,approve_payload(view),headers,'approve').status_code==202
        response=client.get(BASE+'/goals/'+ref(p)+'/review')
        assert response.status_code==200,response.text
        assert response.json()['contract']['proposal']==q and response.json()['changes']
        assert response.json()['authority']['source_coverage']=='ORIGINAL_EVENT_VERIFIED'
        assert 'registry_witness' not in response.text and '$rlflow_blob' not in response.text


def test_cached_aliases_are_charged_before_any_canonical_expansion(tmp_path):
    store,_,_,_,_,_,_=setup(tmp_path)
    raw=canonical('x'*65536);key=hashlib.sha256(raw).hexdigest()
    with store.connect() as db:
        db.execute('INSERT INTO blobs VALUES(?,?)',(key,raw))
        budget=ReadBudget(db,128*1024)
        descriptors=budget.parse(canonical([{'$rlflow_blob':key}]*10))
        with pytest.raises(Conflict,match='expanded source budget'):
            budget.decode(descriptors)
        assert (key,False) in budget.blobs and budget.remaining>0


def test_review_and_actual_confirmation_reject_small_raw_large_expanded_blob(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        record=store.get(GOALS[0],revision_key(p));raw=canonical('x'*(1024*1024));key=hashlib.sha256(raw).hexdigest()
        record['contract']['proposal']['stop_rules']=[{'$rlflow_blob':key}]*25
        with store.connect() as db:
            db.execute('INSERT INTO blobs VALUES(?,?)',(key,raw))
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(record).decode(),GOALS[0],revision_key(p)))
        reviewed=client.get(BASE+'/goals/'+ref(p)+'/review')
        confirmed=client.post(BASE+'/goals/'+p['goal_id']+'/approval-confirmations',headers=headers,json={'ttl_seconds':60})
        assert reviewed.status_code==confirmed.status_code==503
        assert p['objective'] not in reviewed.text and p['objective'] not in confirmed.text


@pytest.mark.parametrize('damage',['record_schema','current_head_hash'])
def test_actual_confirmation_storage_schema_fault_is_not_client_400(tmp_path,damage):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        section,key=(GOALS[0],revision_key(p)) if damage=='record_schema' else (GOALS[1],ref(p))
        record=store.get(section,key)
        if damage=='record_schema':record['contract']['state']='READY'
        else:record['contract_hash']='sha256:'+'0'*64
        with store.connect() as db:
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(record).decode(),section,key))
        response=client.post(BASE+'/goals/'+p['goal_id']+'/approval-confirmations',headers=headers,json={'ttl_seconds':60})
        assert response.status_code==503,response.text
        validate('Error',response.json())
        assert p['objective'] not in response.text


def test_owned_loopback_loaded_private_config_actual_goal_review_and_shutdown(tmp_path):
    import asyncio
    import socket
    import threading
    import time
    import httpx
    import uvicorn
    from rlflow.web import load_server_config
    from rlflow.web_api import create_app
    from tests.test_web_control_config import fixture_config, write_config
    from tests.test_hybrid_control_api import PHRASE
    from tests.test_hybrid_registry import bound
    store,config=fixture_config(tmp_path)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(16)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1]);config['origin']=origin
    loaded,projects,auth,controls=load_server_config(write_config(tmp_path,config))
    app=create_app(projects,auth,origin=loaded,control_services=controls)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,server_header=False,loop='asyncio',lifespan='on'))
    failures=[]
    def serve():
        try:asyncio.run(server.serve(sockets=[listener]))
        except BaseException as error:failures.append(error)
    thread=threading.Thread(target=serve,name='owned-configured-hybrid-read',daemon=False)
    thread.start()
    try:
        deadline=time.monotonic()+4
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        assert server.started and thread.is_alive() and not failures
        _,p=bound()
        with httpx.Client(base_url=origin,timeout=3) as client:
            logged=client.post('/api/v1/login',headers={'Origin':origin},json={'principal_id':'both','passphrase':PHRASE})
            assert logged.status_code==200
            headers={'Origin':origin,'X-CSRF-Token':logged.json()['csrf_token']}
            assert post(client,submit_payload(p),headers,'configured-draft').status_code==202
            page=client.get(BASE+'/goals');assert page.status_code==200
            reviewed=client.get(BASE+'/goals/'+page.json()['items'][0]['goal_ref']+'/review')
            assert reviewed.status_code==200 and reviewed.json()['contract']['proposal']==p
            assert reviewed.json()['source_coverage']=='ORIGINAL_EVENT_VERIFIED'
            assert reviewed.json()['execution_enabled'] is False and store.version()==1
        assert store.replay()==store.audit() and not store.objects('sessions')
    finally:
        server.should_exit=True;thread.join(timeout=5);listener.close()
    assert not thread.is_alive() and not failures and app.state.hybrid_control_pool.pending==0
