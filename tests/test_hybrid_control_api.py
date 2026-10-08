import asyncio
from copy import deepcopy
import json
import threading
import socket
import time

import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_authority import ApprovalService, SECTIONS as AUTHORITY
from rlflow.hybrid_drafts import DraftService
from rlflow.hybrid_control import ControlServices, ControlPool, ControlError
from rlflow.hybrid_protocol import validate, schemas
from rlflow.observation import enable
from rlflow.store import Store
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Credential, Principal
from tests.test_hybrid_registry import bound, catalog

ORIGIN='http://127.0.0.1:8765'
PHRASE='synthetic HTTP control fixture passphrase'
BASE='/api/v1/projects/project_fixture'


def setup(tmp_path,origin=ORIGIN,max_jobs=4,config=None):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    registry,p=bound(catalog() if config is None else config);mono=[1.0]
    principals=[Principal(name,'human',roles,{'project_fixture'}) for name,roles in
        (('operator',{'operator'}),('approver',{'approver'}),('both',{'operator','approver'}),('viewer',{'viewer'}))]
    auth=AuthStore([Credential.create(a,PHRASE) for a in principals],ttl=100,clock=lambda:mono[0])
    draft=DraftService(store,auth,project_id='project_fixture',data_mode='fixture',origin=origin)
    approval=ApprovalService(store,auth,registry,project_id='project_fixture',data_mode='fixture',origin=origin)
    projects=[Project('project_fixture',str(store.root),'fixture')]
    pair=ControlServices(draft,approval)
    app=create_app(projects,auth,origin=origin,control_services={'project_fixture':pair},max_control_jobs=max_jobs)
    return store,auth,p,app,pair,projects,mono


def login(client,principal='both'):
    result=client.post('/api/v1/login',headers={'Origin':ORIGIN},json={'principal_id':principal,'passphrase':PHRASE})
    assert result.status_code==200
    return {'Origin':ORIGIN,'X-CSRF-Token':result.json()['csrf_token']}


def submit_payload(p,version=0):return {'schema_version':'1.1','action':'submit_goal','target':{'kind':'project','id':'project_fixture'},
    'expected_version':version,'parameters':{'goal':p,'expected_revision':p['contract_version']-1}}


def post(client,payload,headers,key):return client.post(BASE+'/commands',headers={**headers,'Idempotency-Key':key},json=payload)


def prepare(client,p,headers):
    result=client.post(BASE+'/goals/'+p['goal_id']+'/approval-confirmations',headers=headers,json={'ttl_seconds':60})
    assert result.status_code==200,result.text
    return result.json()


def approve_payload(view):return {'schema_version':'1.1','action':'approve','target':{'kind':'goal','id':view['confirmation']['goal_id']},
    'expected_version':view['confirmation']['expected_version'],'parameters':{'confirmation':view['confirmation']}}


def test_actual_http_fixture_submit_prepare_approve_revoke_and_receipts(tmp_path):
    store,auth,p,app,pair,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);draft=post(client,submit_payload(p),headers,'draft')
        assert draft.status_code==202 and draft.json()['result']['state']=='DRAFT'
        view=prepare(client,p,headers);before=store.version()
        assert view['execution_enabled'] is False and 'registry_witness' not in json.dumps(view)
        assert store.version()==before
        payload=approve_payload(view);approved=post(client,payload,headers,'approve')
        assert approved.status_code==202,approved.text
        dto=approved.json();assert dto['status']=='SUCCEEDED' and dto['result']['state']=='LEASE_VALIDATION_PENDING'
        assert dto['result']['execution_enabled'] is False
        assert 'registry_witness' not in approved.text and 'runtime_profile' not in approved.text and PHRASE not in approved.text
        assert client.get(BASE+'/commands/'+dto['command_id']).json()==dto
        repeat=post(client,payload,headers,'approve')
        assert repeat.json()=={**dto,'duplicate':True}
        revoke={'schema_version':'1.1','action':'revoke','target':{'kind':'approval','id':dto['result']['fact_key']},
            'expected_version':store.version(),'parameters':{'goal_id':p['goal_id'],'expected_authority_revision':1,'reason':'fixture explicit revoke'}}
        revoked=post(client,revoke,headers,'revoke');assert revoked.status_code==202 and revoked.json()['result']['state']=='REVOKED'
        assert not store.objects('tasks') and not store.objects('sessions') and not store.objects('approvals')
        assert len(store.objects(AUTHORITY[0]))==len(store.objects(AUTHORITY[1]))==1
        store.snapshot();assert store.recover()==store.audit()==store.replay()
    assert app.state.hybrid_control_pool.pending==0 and not pair.drafts._active_writes and not pair.approvals._active_writes


def test_http_same_actor_client_key_is_unified_across_actions(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'one_key').status_code==202
        view=prepare(client,p,headers);before=store.audit()
        result=post(client,approve_payload(view),headers,'one_key')
        assert result.status_code==409 and result.json()['code']=='IDEMPOTENCY_CONFLICT'
        assert store.audit()==before
        assert post(client,approve_payload(view),headers,'other_key').status_code==202


@pytest.mark.parametrize('principal,action',[('viewer','submit'),('approver','submit'),('operator','prepare'),('viewer','prepare')])
def test_http_roles_do_not_inherit_write_or_approval(tmp_path,principal,action):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client,principal);before=store.audit()
        if action=='submit':result=post(client,submit_payload(p),headers,'denied')
        else:result=client.post(BASE+'/goals/'+p['goal_id']+'/approval-confirmations',headers=headers,json={'ttl_seconds':60})
        assert result.status_code==403 and result.json()['code']=='PERMISSION_DENIED'
        assert store.audit()==before


@pytest.mark.parametrize('bad',['origin_missing','csrf','bearer','actor','root','unknown_action','old_command','global_float','target','cross_project','missing_key','duplicate_json','oversize'])
def test_http_closed_authentication_and_payload_boundaries(tmp_path,bad):
    store,auth,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);payload=submit_payload(p);before=store.audit();url=BASE+'/commands';key='denied'
        if bad=='origin_missing':headers.pop('Origin')
        elif bad=='csrf':headers['X-CSRF-Token']='incorrect_csrf_token_value'
        elif bad=='bearer':headers['Authorization']='Bearer '+auth.issue_bearer(Principal('reader','human',{'viewer'},{'project_fixture'}),ttl=50)[0]
        elif bad=='actor':payload['actor']={'kind':'human','id':'approver'}
        elif bad=='root':payload['parameters']['root']='/DO_NOT_OPEN'
        elif bad=='unknown_action':payload['action']='stop'
        elif bad=='old_command':payload['schema_version']='1.0'
        elif bad=='global_float':payload['expected_version']=0.0
        elif bad=='target':payload['target']['id']='other_project'
        elif bad=='cross_project':url=url.replace('project_fixture','foreign_project')
        all_headers={**headers,**({'Idempotency-Key':key} if bad!='missing_key' else {})}
        if bad=='duplicate_json':result=client.post(url,headers={**all_headers,'Content-Type':'application/json'},content='{"action":"submit_goal","action":"approve"}')
        elif bad=='oversize':result=client.post(url,headers={**all_headers,'Content-Type':'application/json'},content='x'*(256*1024+1))
        else:result=client.post(url,headers=all_headers,json=payload)
        assert result.status_code in (400,403,404,413),result.text
        if result.status_code!=403 or bad!='origin_missing':validate('Error',result.json())
        assert store.audit()==before and PHRASE not in result.text and '/DO_NOT_OPEN' not in result.text


def test_default_app_is_still_readonly_and_startup_rejects_mismatched_owners(tmp_path):
    store,auth,p,_,pair,projects,_=setup(tmp_path)
    with TestClient(create_app(projects,auth),base_url=ORIGIN) as client:
        headers=login(client);before=store.audit()
        assert post(client,submit_payload(p),headers,'not_enabled').status_code==404
        assert store.audit()==before
    with pytest.raises(ValueError):create_app(projects,AuthStore(),control_services={'project_fixture':pair})
    with pytest.raises(ValueError):create_app([Project('project_fixture','/DO_NOT_OPEN','fixture')],auth,control_services={'project_fixture':pair})
    with pytest.raises(ValueError):create_app(projects,auth,origin='http://127.0.0.1:9999',control_services={'project_fixture':pair})


def test_command_read_is_project_scoped_bearer_readonly_and_bounded(tmp_path):
    store,auth,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);dto=post(client,submit_payload(p),headers,'read').json();url=BASE+'/commands/'+dto['command_id']
        token=auth.issue_bearer(Principal('reader','human',{'viewer'},{'project_fixture'}),ttl=50)[0]
        assert client.get(url,headers={'Authorization':'Bearer '+token}).json()==dto
        assert client.get(url.replace('project_fixture','foreign_project')).status_code==404
        assert client.get(BASE+'/commands/not_found').status_code==404
        from rlflow.hybrid_goals import SECTIONS
        with store.connect() as db:db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',('x'*(4*1024*1024+1),SECTIONS[2],dto['command_id']))
        assert client.get(url).status_code==503


def test_confirmation_outer_version_and_target_must_match(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);post(client,submit_payload(p),headers,'draft');view=prepare(client,p,headers);before=store.audit()
        for field in ('version','target'):
            payload=approve_payload(view)
            if field=='version':payload['expected_version']+=1
            else:payload['target']['id']='other_goal'
            assert post(client,payload,headers,'bad_'+field).status_code==400
        assert store.audit()==before


def test_pool_disconnect_keeps_capacity_until_actual_worker_terminal():
    async def scenario():
        pool=ControlPool(1);entered=threading.Event();release=threading.Event()
        def worker():
            entered.set();assert release.wait(timeout=3)
            return 'actual_done'
        task=asyncio.create_task(pool.run(worker))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert pool.pending==1
            with pytest.raises(ControlError) as exc:await pool.run(lambda:None)
            assert exc.value.status==429
        finally:
            release.set();await pool.close()
        assert pool.pending==0
    asyncio.run(scenario())


def test_command_schema_preserves_old_schema_and_rejects_actor():
    assert schemas()['command']['$id']=='urn:rlflow:spec:command:1.0'
    assert schemas()['command_v1_1']['$id']=='urn:rlflow:spec:command:1.1'
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schemas()['command_v1_1'])


def test_legal_high_structure_registry_approval_receipt_and_retry(tmp_path):
    config=catalog();config['runtime_profile']['configuration']={'metadata':[0]*60000}
    store,_,p,app,_,_,_=setup(tmp_path,config=config)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        view=prepare(client,p,headers);payload=approve_payload(view)
        first=post(client,payload,headers,'approve');assert first.status_code==202,first.text
        assert 'metadata' not in first.text and 'registry_witness' not in first.text
        dto=first.json();assert client.get(BASE+'/commands/'+dto['command_id']).json()==dto
        assert post(client,payload,headers,'approve').json()=={**dto,'duplicate':True}
        assert len(store.objects(AUTHORITY[0]))==1 and store.recover()==store.audit()==store.replay()


def test_legal_literal_blob_encoding_expansion_and_large_request_remain_readable(tmp_path):
    config=catalog();config['runtime_profile']['configuration']={'metadata':[{'$rlflow_blob':0}]*13000}
    store,_,p,app,_,_,_=setup(tmp_path,config=config);p['stop_rules']=['fixture '+('x'*3992)]*55
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);draft=post(client,submit_payload(p),headers,'draft');assert draft.status_code==202,draft.text
        assert client.get(BASE+'/commands/'+draft.json()['command_id']).json()==draft.json()
        assert post(client,submit_payload(p),headers,'draft').json()=={**draft.json(),'duplicate':True}
        view=prepare(client,p,headers);payload=approve_payload(view)
        first=post(client,payload,headers,'approve');assert first.status_code==202,first.text
        dto=first.json();assert client.get(BASE+'/commands/'+dto['command_id']).json()==dto
        assert post(client,payload,headers,'approve').json()=={**dto,'duplicate':True}
        assert '$rlflow_blob' not in first.text and 'metadata' not in first.text
        assert store.replay()==store.audit() and len(store.objects(AUTHORITY[0]))==1


def test_corrupt_current_version_is_never_echoed_in_conflict_summary(tmp_path):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client)
        with store.connect() as db:db.execute("UPDATE projection_meta SET version='private_secret_corrupt_version'")
        result=post(client,submit_payload(p),headers,'corrupt')
        assert result.status_code==503 and result.json()['details']=={}
        assert 'private_secret' not in result.text


def test_stale_global_and_goal_cas_reports_only_authorized_current_version(tmp_path):
    store,auth,p,app,pair,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=login(client);assert post(client,submit_payload(p),headers,'draft').status_code==202
        p2=deepcopy(p);p2['contract_version']=2
        for payload in (submit_payload(p2,0),submit_payload(p,1)):
            result=post(client,payload,headers,'stale_'+str(payload['expected_version']))
            assert result.status_code==409 and result.json()['code']=='VERSION_CONFLICT'
            assert result.json()['details']=={'current_version':store.version()}
            validate('Error',result.json())
            assert 'registry_witness' not in result.text
        token=client.cookies.get('rlflow_session');auth.revoke(token)
        result=post(client,submit_payload(p2,0),headers,'after_revoke')
        assert result.status_code==401 and result.json()['details']=={}


@pytest.mark.parametrize('bad',['wrong_origin','duplicate_origin','duplicate_host','duplicate_authorization','duplicate_cookie','duplicate_csrf','duplicate_key'])
def test_opt_in_control_boundary_errors_use_closed_error_contract(tmp_path,bad):
    store,_,p,app,_,_,_=setup(tmp_path)
    with TestClient(app,base_url=ORIGIN) as client:
        headers=list(login(client).items())+[('Idempotency-Key','test')];before=store.audit()
        if bad=='wrong_origin':headers=[(k,'http://private_secret.invalid' if k=='Origin' else v) for k,v in headers]
        else:
            name={'duplicate_origin':'Origin','duplicate_host':'Host','duplicate_authorization':'Authorization',
                'duplicate_cookie':'Cookie','duplicate_csrf':'X-CSRF-Token','duplicate_key':'Idempotency-Key'}[bad]
            if not any(k.lower()==name.lower() for k,v in headers):headers.append((name,'private_secret'))
            headers.append((name,'private_secret_second'))
        result=client.post(BASE+'/commands',headers=headers,json=submit_payload(p))
        assert result.status_code==403,result.text
        validate('Error',result.json());assert result.json()['code']=='PERMISSION_DENIED'
        assert 'private_secret' not in result.text and store.audit()==before


def test_owned_real_loopback_http_disconnect_does_not_release_writer_capacity(tmp_path,monkeypatch):
    import httpx
    import uvicorn
    from rlflow.hybrid_goals import control_command_key
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(16)
    origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    store,auth,p,app,pair,_,_=setup(tmp_path,origin,max_jobs=1)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,loop='asyncio',lifespan='on'))
    failures=[];entered=threading.Event();release=threading.Event();original=pair.drafts.submit
    def delayed(*a,**kw):
        entered.set()
        if not release.wait(timeout=5):raise RuntimeError('fixture worker release timeout')
        return original(*a,**kw)
    monkeypatch.setattr(pair.drafts,'submit',delayed)
    def serve():
        try:asyncio.run(server.serve(sockets=[listener]))
        except BaseException as error:failures.append(error)
    thread=threading.Thread(target=serve,name='owned-control-http-fixture',daemon=False)
    thread.start()
    try:
        deadline=time.monotonic()+4
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        assert server.started and thread.is_alive() and not failures
        with httpx.Client(base_url=origin,timeout=2) as client:
            logged=client.post('/api/v1/login',headers={'Origin':origin},json={'principal_id':'both','passphrase':PHRASE})
            assert logged.status_code==200
            headers={'Origin':origin,'X-CSRF-Token':logged.json()['csrf_token']}
            with pytest.raises(httpx.ReadTimeout):
                client.post(BASE+'/commands',headers={**headers,'Idempotency-Key':'disconnect'},json=submit_payload(p),timeout=.15)
            assert entered.wait(timeout=2) and app.state.hybrid_control_pool.pending==1
            overloaded=post(client,submit_payload(p),headers,'other')
            assert overloaded.status_code==429 and store.version()==0
            release.set();deadline=time.monotonic()+4
            while app.state.hybrid_control_pool.pending and time.monotonic()<deadline:time.sleep(.01)
            assert app.state.hybrid_control_pool.pending==0 and store.version()==1
            command_id=control_command_key({'id':'both','kind':'human'},'project_fixture','fixture','disconnect')
            receipt=client.get(BASE+'/commands/'+command_id)
            assert receipt.status_code==200 and receipt.json()['result']['state']=='DRAFT'
            assert post(client,submit_payload(p),headers,'disconnect').json()=={**receipt.json(),'duplicate':True}
            view=client.post(BASE+'/goals/'+p['goal_id']+'/approval-confirmations',headers=headers,json={'ttl_seconds':60})
            assert view.status_code==200
            approved=post(client,approve_payload(view.json()),headers,'approve')
            assert approved.status_code==202 and approved.json()['result']['execution_enabled'] is False
            assert not store.objects('tasks') and not store.objects('sessions')
        assert store.audit()==store.replay()
    finally:
        release.set();server.should_exit=True;thread.join(timeout=8);listener.close()
    assert not thread.is_alive() and not failures and app.state.hybrid_control_pool.closed
