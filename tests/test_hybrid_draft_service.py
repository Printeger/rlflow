from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import copy
from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from rlflow.hybrid_drafts import DraftService
from rlflow.hybrid_goals import propose, SECTIONS, digest
from rlflow.hybrid_authority import ApprovalService
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Store, Conflict
from rlflow.observation import enable
from rlflow.web_auth import Principal, Credential, AuthStore
from tests.test_hybrid_registry import catalog

ORIGIN='http://127.0.0.1:8765'
PHRASE='synthetic draft service fixture passphrase'


def setup(tmp_path,roles=('operator',)):
    store=Store(tmp_path/'state');enable(store,'project_fixture',data_mode='fixture')
    p=json.loads(Path('docs/rlflow_hybrid_spec_v1/examples/goal.fixture.json').read_text())
    actor=Principal('fixture_operator','human',roles,{'project_fixture'});mono=[1.0]
    auth=AuthStore([Credential.create(actor,PHRASE)],ttl=100,clock=lambda:mono[0])
    token,access=auth.login(actor.id,PHRASE)
    service=DraftService(store,auth,project_id='project_fixture',data_mode='fixture',origin=ORIGIN)
    args={'token':token,'csrf':access.csrf,'origin':ORIGIN,'idempotency_key':'draft',
          'expected_revision':0,'expected_state_version':0}
    return store,service,p,args,mono


def rows(store):
    with store.connect() as db:
        return {table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in
            ('observation_meta','observation_events','observation_projection','observation_counters')}


def test_operator_session_creates_only_draft_and_original_retry(tmp_path):
    store,service,p,args,_=setup(tmp_path);first=service.submit(p,**args)
    assert first['contract']['state']=='DRAFT' and first['contract']['approval_id'] is None
    assert store.objects(SECTIONS[0])[0][1]['submitted_by']=={'id':'fixture_operator','kind':'human'}
    assert not store.objects('approvals') and not store.objects('tasks') and not store.objects('sessions')
    assert not service._active_writes and not service.auth._operator_guards
    store.transact_objects('USAGE_OBSERVED','other',[('usage','other')],lambda s:s.setdefault('usage',{}).update(other={}))
    assert service.submit(p,**args)=={**first,'duplicate':True}
    store.snapshot();assert store.audit()==store.recover()==store.replay()


@pytest.mark.parametrize('bad',['viewer','approver','csrf','origin','bearer','principal','access','expired','none_version','float_version'])
def test_untrusted_or_wrong_role_submission_has_no_effect(tmp_path,bad):
    roles=(bad,) if bad in ('viewer','approver') else ('operator',)
    store,service,p,args,mono=setup(tmp_path,roles);before=store.audit();public=rows(store)
    if bad=='csrf':args['csrf']='incorrect_actual_csrf_token'
    elif bad=='origin':args['origin']='http://evil.invalid'
    elif bad=='bearer':args['token']=service.auth.issue_bearer(Principal('reader','human',{'viewer'},{'project_fixture'}),ttl=50)[0]
    elif bad=='principal':args['token']=Principal('fake','human',{'operator'},{'project_fixture'})
    elif bad=='access':args['token']=service.auth.resolve(args['token'],'session')
    elif bad=='expired':mono[0]=101.0
    elif bad=='none_version':args['expected_state_version']=None
    elif bad=='float_version':args['expected_state_version']=0.0
    with pytest.raises((PermissionError,ProtocolError)):service.submit(p,**args)
    assert store.audit()==before and rows(store)==public
    assert not service._active_writes and not service.auth._operator_guards


@pytest.mark.parametrize('change',['revoke','expiry'])
def test_duplicate_still_requires_actual_fresh_operator_session(tmp_path,change):
    store,service,p,args,mono=setup(tmp_path);service.submit(p,**args);before=store.audit()
    if change=='revoke':service.auth.revoke(args['token'])
    else:mono[0]=101.0
    with pytest.raises(PermissionError):service.submit(p,**args)
    assert store.audit()==before


def test_operator_guard_cannot_impersonate_approval_or_other_issuer(tmp_path):
    store,service,p,args,_=setup(tmp_path,('operator','approver'));auth=service.auth
    with auth.operator_guard(args['token'],project_id='project_fixture',csrf=args['csrf']) as guard:
        assert auth.check_operator_guard(guard,project_id='project_fixture').principal.id=='fixture_operator'
        for bad in (copy(guard),replace(guard)):
            with pytest.raises(PermissionError):auth.check_operator_guard(bad,project_id='project_fixture')
        with pytest.raises(PermissionError):auth.check_approval_guard(guard,project_id='project_fixture')
        with pytest.raises(PermissionError):AuthStore().check_operator_guard(guard,project_id='project_fixture')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(auth.check_operator_guard,guard,project_id='project_fixture')
            with pytest.raises(PermissionError):future.result(timeout=2)
    with pytest.raises(PermissionError):auth.check_operator_guard(guard,project_id='project_fixture')
    with auth.approval_guard(args['token'],project_id='project_fixture',csrf=args['csrf']) as approval:
        with pytest.raises(PermissionError):auth.check_operator_guard(approval,project_id='project_fixture')
    assert not auth._operator_guards and not auth._approval_guards


@pytest.mark.parametrize('lock_kind',['writer','sqlite'])
@pytest.mark.parametrize('change',['revoke','expiry'])
def test_actual_writer_wait_rechecks_session_without_holding_auth(tmp_path,monkeypatch,lock_kind,change):
    store,service,p,args,mono=setup(tmp_path);before=store.audit();public=rows(store);attempt=threading.Event()
    original=store.lock
    @contextmanager
    def observed_lock():
        attempt.set()
        with original():yield
    monkeypatch.setattr(store,'lock',observed_lock)
    @contextmanager
    def sql_lock():
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:yield
            finally:db.rollback()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with original() if lock_kind=='writer' else sql_lock():
            future=executor.submit(service.submit,p,**args)
            assert attempt.wait(timeout=3)
            # Must not block behind an Auth lock taken before the Store writer.
            if change=='revoke':service.auth.revoke(args['token'])
            else:mono[0]=101.0
        with pytest.raises(PermissionError):future.result(timeout=4)
    assert store.audit()==before and rows(store)==public
    assert not service._active_writes and not service.auth._operator_guards


def test_expiry_after_actual_event_staging_rolls_back_all_tables(tmp_path,monkeypatch):
    store,service,p,args,mono=setup(tmp_path);before=store.audit();public=rows(store);original=store._commit
    def expire(*a,**kw):
        version=original(*a,**kw);mono[0]=101.0
        return version
    monkeypatch.setattr(store,'_commit',expire)
    with pytest.raises(PermissionError):service.submit(p,**args)
    assert store.audit()==before and rows(store)==public
    assert not service._active_writes and not service.auth._operator_guards


def test_commit_failure_cleans_both_contexts_and_can_retry(tmp_path,monkeypatch):
    store,service,p,args,_=setup(tmp_path);before=store.audit();public=rows(store)
    from rlflow import observation
    original=observation.commit
    def fail(*a,**kw):raise RuntimeError('fixture failure')
    monkeypatch.setattr(observation,'commit',fail)
    with pytest.raises(RuntimeError):service.submit(p,**args)
    assert store.audit()==before and rows(store)==public
    assert not service._active_writes and not service.auth._operator_guards
    monkeypatch.setattr(observation,'commit',original)
    assert service.submit(p,**args)['duplicate'] is False


def test_bound_draft_rejects_actual_guard_without_service_context_and_legacy_principal(tmp_path):
    store,service,p,args,_=setup(tmp_path);before=store.audit()
    principal=service.auth.resolve(args['token'],'session').principal
    for authorization in (None,lambda:service.auth.operator_guard(args['token'],project_id='project_fixture',csrf=args['csrf'])):
        with pytest.raises(PermissionError):
            propose(store,p,principal=principal,project_id='project_fixture',data_mode='fixture',idempotency_key='generic',
                expected_revision=0,expected_state_version=0,_authorization=authorization)
    assert store.audit()==before


def test_bound_draft_renamed_generic_writer_cannot_modify_private_records(tmp_path):
    store,service,p,args,_=setup(tmp_path);service.submit(p,**args);before=store.audit();key,value=store.objects(SECTIONS[0])[0]
    with pytest.raises((Conflict,PermissionError)):
        store.transact_objects('UNRELATED','rename',[(SECTIONS[0],key)],lambda s:s[SECTIONS[0]][key].update(submitted_by={'id':'fake','kind':'human'}))
    assert store.audit()==before


def test_legacy_duplicate_and_noop_cannot_bypass_bound_draft_guard(tmp_path):
    store,service,p,args,_=setup(tmp_path);service.submit(p,**args);before=store.audit();public=rows(store)
    key,receipt=store.objects(SECTIONS[2])[0]
    for event_key in (key,'new_noop'):
        with pytest.raises(PermissionError):store.transact('HYBRID_GOAL_DRAFTED',event_key,lambda s:None,
            object_id=receipt['request_hash'],producer='hybrid-core')
    assert store.audit()==before and rows(store)==public


def test_owner_registration_epoch_and_shared_auth_are_fixed(tmp_path):
    store,service,p,args,_=setup(tmp_path)
    with pytest.raises(Conflict):DraftService(store,service.auth,project_id='project_fixture',data_mode='fixture',origin=ORIGIN)
    with pytest.raises(Conflict):ApprovalService(store,AuthStore(),Registry(catalog()),project_id='project_fixture',data_mode='fixture',origin=ORIGIN)
    with pytest.raises(ValueError):DraftService(store,service.auth,project_id='other_project',data_mode='fixture',origin=ORIGIN)
    with store.connect() as db:db.execute("UPDATE observation_meta SET store_epoch='changed_fixture_epoch'")
    before=store.audit()
    with pytest.raises(Conflict,match='epoch'):service.submit(p,**args)
    assert store.audit()==before


def test_draft_operator_role_does_not_implicitly_approve(tmp_path):
    store,service,p,args,_=setup(tmp_path)
    approval=ApprovalService(store,service.auth,Registry(catalog()),project_id='project_fixture',data_mode='fixture',origin=ORIGIN)
    service.submit(p,**args)
    with pytest.raises(PermissionError):approval.prepare(token=args['token'],csrf=args['csrf'],origin=ORIGIN,goal_id=p['goal_id'],ttl_seconds=60)


def test_oversized_token_not_hashed_by_operator_guard(tmp_path,monkeypatch):
    _,service,_,args,_=setup(tmp_path);original=service.auth._key
    def bounded(value):
        assert len(value)<=128
        return original(value)
    monkeypatch.setattr(service.auth,'_key',bounded)
    with pytest.raises(PermissionError):
        with service.auth.operator_guard('x'*129,project_id='project_fixture',csrf=args['csrf']):pass
