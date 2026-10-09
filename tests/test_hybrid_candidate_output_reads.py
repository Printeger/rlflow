"""Actual fixed candidate output through owner-free authenticated read API."""
import json
import pytest
from fastapi.testclient import TestClient
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
from rlflow.hybrid_candidate_output import SECTIONS,result_key
from rlflow.store import Store,Conflict,canonical
from rlflow.web_api import Project,create_app
from rlflow.web_auth import AuthStore,Credential,Principal
from tests.test_hybrid_engineering_output import engineering_runtime,stopped
from tests.test_execution_adapter import setup as native_setup

ORIGIN='http://127.0.0.1:8765'
PHRASE='Private fixed candidate output evidence viewer passphrase'


def setup(context,*,origin=ORIGIN):
    owner,lease,service,args=stopped(context)
    value=service.apply(lease,context[2],**args)['fact'];key=result_key(value['request'])
    cold=Store.attach_existing(owner.store.root,project_id=owner.workspace.project_id,data_mode='fixture')
    reader=CandidateOutputReader(cold,owner.plans.registry,project_id=owner.workspace.project_id,store_epoch=owner.workspace.store_epoch)
    viewer=Principal('viewer','human',{'viewer'},{reader.project_id})
    auth=AuthStore([Credential.create(viewer,PHRASE)])
    app=create_app([Project(reader.project_id,str(cold.root),'fixture')],auth,origin=origin,candidate_output_readers={reader.project_id:reader})
    bearer,_=auth.issue_bearer(viewer)
    return owner,lease,service,reader,app,auth,{'Authorization':'Bearer '+bearer},'/api/v1/projects/'+reader.project_id+'/candidate-outputs',key


def test_actual_original_output_cold_HTTP_no_writer_and_owner_closed(engineering_runtime,monkeypatch):
    owner,lease,service,reader,app,auth,headers,base,key=setup(engineering_runtime)
    version=owner.store.version();origin=owner._issued(lease)['origin']
    assert reader.store._hybrid_candidate_output_service is None and reader.store._hybrid_budget_service is None
    with monkeypatch.context() as patch:
        for obj,name in ((owner,'start'),(owner,'poll'),(owner,'collect_engineering_patch'),(owner.sources,'poll'),(service,'apply'),(owner.store,'_commit')):
            patch.setattr(obj,name,lambda *a,**k:pytest.fail('readonly GET must not execute/poll/write'))
        with TestClient(app,base_url=ORIGIN) as client:
            page=client.get(base,headers=headers);assert page.status_code==200,page.text
            assert len(page.json()['items'])==1
            response=client.get(base+'/'+key,headers=headers);assert response.status_code==200,response.text
            row=response.json()['candidate'];assert row['baseline_failed_cases']==2 and row['actual_passed_cases']==3
            assert [r['actual'] for r in row['evidence']['actual_tests']]==[5,-2,0]
            assert row['current_activation']=='HISTORICAL_AUDIT_ONLY' and row['resource_release_status']=='NOT_OBSERVED'
            assert row['before_sha256']!=row['after_sha256'] and row['base_tree_sha256']!=row['output_tree_sha256']
            assert not row['goal_completed'] and not row['controls_available']
            for secret in (str(owner.store.root),origin['nonce'],'producer','lease_id','pool_free','target_identity'):
                assert secret not in response.text
            assert client.post(base+'/'+key,headers=headers,json={'action':'apply'}).status_code==405
    assert owner.store.version()==version
    owner.shutdown();owner.pool.shutdown()
    assert reader.output_detail(key)['candidate']['evidence']['candidate_write_fd_closed'] is True
    assert owner.store.version()==version


def test_original_dependency_damage_large_key_and_final_epoch_cannot_be_success(engineering_runtime,monkeypatch):
    from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET
    from rlflow.hybrid_preparation import SECTIONS as PREPARATION
    from rlflow.hybrid_controller import SECTIONS as CONTROL
    owner,lease,service,reader,app,auth,headers,base,key=setup(engineering_runtime)
    version=owner.store.version();value=owner.store.get(SECTIONS[1],key)
    terminal=owner.store.get(BUDGET[0],value['request']['terminal_key'])
    dependencies=[(SECTIONS[1],key),(SECTIONS[0],value['request']['intent_key']),
        (BUDGET[0],value['request']['terminal_key']),
        (PREPARATION[0],terminal['preparation']['intent_key']),
        (PREPARATION[1],terminal['preparation']['result_key']),
        (CONTROL[0],value['controller']['fact_key'])]
    with TestClient(app,base_url=ORIGIN) as client:
        for section,depkey in dependencies:
            with owner.store.connect() as db:
                original=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,depkey)).fetchone()[0]
                broken=owner.store._decode_value(db,json.loads(original));broken['accepted_state_version']+=1
                db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',
                    (canonical(owner.store._encode_value(db,broken)).decode(),section,depkey))
            try:
                assert client.get(base+'/'+key,headers=headers).status_code==503,(section,depkey)
            finally:
                with owner.store.connect() as db:db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(original,section,depkey))
        # One SQL-bounded hostile key; account for its count so rejection must
        # still hold, rather than assuming the count check is the only fence.
        huge='z'*4096
        with owner.store.connect() as db:db.execute('UPDATE projection SET object_key=? WHERE section=? AND object_key=?',(huge,SECTIONS[1],key))
        try:assert client.get(base,headers=headers).status_code==503
        finally:
            with owner.store.connect() as db:db.execute('UPDATE projection SET object_key=? WHERE section=? AND object_key=?',(key,SECTIONS[1],huge))
        original=reader.check_current
        def changed_epoch(v):
            with owner.store.connect() as db:db.execute("UPDATE observation_meta SET store_epoch='replaced_epoch' WHERE singleton=1")
            return original(v)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(reader,'check_current',changed_epoch)
                assert client.get(base+'/'+key,headers=headers).status_code==503
        finally:
            with owner.store.connect() as db:db.execute('UPDATE observation_meta SET store_epoch=? WHERE singleton=1',(reader.store_epoch,))
        assert client.get(base+'?limit=5',headers=headers).status_code==200
    assert owner.store.version()==version and owner.store.audit()==owner.store.replay()
    owner.shutdown();owner.pool.shutdown()
    assert reader.output_detail(key)['candidate']['evidence']['candidate_write_fd_closed'] is True
    assert owner.store.version()==version


def test_auth_closed_query_dual_domain_corruption_and_final_auth(engineering_runtime,monkeypatch):
    owner,lease,service,reader,app,auth,headers,base,key=setup(engineering_runtime)
    version=owner.store.version()
    with TestClient(app,base_url=ORIGIN) as client:
        assert client.get(base).status_code==401
        for query in ('?limit=0','?limit=6','?limit=01','?limit=1&limit=2','?path=/tmp','?after=../bad'):
            assert client.get(base+query,headers=headers).status_code==400
        assert client.get(base+'/missing',headers=headers).status_code==404
        assert client.get(base+'/'+key+'?poll=1',headers=headers).status_code==400
        assert client.get(base,headers={**headers,'Origin':'https://other.invalid'}).status_code==403
        for section in SECTIONS:
            with owner.store.connect() as db:
                rows=db.execute('SELECT section,object_key,value,version,object_status FROM projection WHERE section=?',(section,)).fetchall()
                db.execute('DELETE FROM projection WHERE section=?',(section,))
            try:
                assert client.get(base,headers=headers).status_code==503
                assert client.get(base+'/'+key,headers=headers).status_code==503
            finally:
                with owner.store.connect() as db:db.executemany('INSERT INTO projection VALUES(?,?,?,?,?)',[tuple(r) for r in rows])
        with owner.store.connect() as db:db.execute('UPDATE projection_meta SET version=?',(version+1,))
        assert client.get(base,headers=headers).status_code==503
        with owner.store.connect() as db:db.execute('UPDATE projection_meta SET version=?',(version,))
        original=reader.output_detail
        def revoke(*args):
            result=original(*args);auth.revoke(headers['Authorization'].split(' ',1)[1]);return result
        with monkeypatch.context() as patch:
            patch.setattr(reader,'output_detail',revoke)
            assert client.get(base+'/'+key,headers=headers).status_code==401
    disabled=create_app([Project(reader.project_id,str(reader.store.root),'fixture')],auth,origin=ORIGIN)
    with TestClient(disabled,base_url=ORIGIN) as client:assert client.get(base).status_code==404
    assert owner.store.version()==version
