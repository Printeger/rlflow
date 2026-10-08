"""Private startup opt-in; no approval or execution is implied by loading."""
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from rlflow.observation import enable
from rlflow.store import Conflict, Store
from rlflow.web import load_config, load_server_config, main, provision
from rlflow.web_api import create_app
from rlflow.web_auth import Credential, Principal
from tests.test_hybrid_control_api import ORIGIN, PHRASE, login, post, submit_payload, prepare, approve_payload
from tests.test_hybrid_registry import bound, catalog


def fixture_config(tmp_path, roles=('operator','approver')):
    store = Store(tmp_path/'state')
    enable(store,'project_fixture',data_mode='fixture')
    # The workspace umask may allow group writes; controlled startup requires
    # an explicitly protected trust boundary, not an implicit chmod on serve.
    store.root.chmod(0o700)
    (store.root/'runtime').chmod(0o700)
    store.db.chmod(0o600)
    (store.root/'runtime/writer.lock').chmod(0o600)
    credential = Credential.create(Principal('both','human',frozenset(roles),{'project_fixture'}),PHRASE)
    config = {'schema_version':'1.1','origin':ORIGIN,
              'projects':[{'id':'project_fixture','root':str(store.root),'data_mode':'fixture'}],
              'credentials':[{'principal_id':'both','kind':'human','roles':list(roles),
                              'projects':['project_fixture'],'salt':credential.salt,'digest':credential.digest}],
              'controls':{'project_fixture':catalog()}}
    return store, config


def write_config(tmp_path, config):
    path = tmp_path/'private.json'
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    return path


def logical_state(store):
    with store.read_connection() as db:
        return {name:tuple(tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')) for name in
                ('events','projection','projection_meta','observation_meta','observation_events',
                 'observation_projection','observation_counters','snapshot_due','snapshots','blobs','sqlite_master')}


def test_private_loader_actual_submit_confirmation_approval_and_original_receipt(tmp_path):
    original, config = fixture_config(tmp_path)
    before = logical_state(original)
    origin, projects, auth, controls = load_server_config(write_config(tmp_path,config))
    assert logical_state(original) == before
    pair = controls['project_fixture']
    assert pair.drafts.store is pair.approvals.store
    assert pair.drafts.auth is pair.approvals.auth is auth
    assert pair.drafts.store._existing_identity is not None
    _, proposal = bound()
    with TestClient(create_app(projects,auth,origin=origin,control_services=controls),base_url=origin) as client:
        headers = login(client)
        result = post(client,submit_payload(proposal),headers,'configured-draft')
        assert result.status_code == 202, result.text
        assert result.json()['result']['state'] == 'DRAFT'
        view = prepare(client,proposal,headers)
        approved = post(client,approve_payload(view),headers,'configured-approve')
        assert approved.status_code == 202, approved.text
        assert approved.json()['result']['state'] == 'LEASE_VALIDATION_PENDING'
        assert approved.json()['result']['execution_enabled'] is False
        command = approved.json()['command_id']
        assert client.get('/api/v1/projects/project_fixture/commands/'+command).json() == approved.json()
    assert not original.objects('sessions') and not original.objects('jobs')


def test_legacy_loader_preserves_three_tuple_and_never_constructs_store(tmp_path,monkeypatch):
    original = Store(tmp_path/'state')
    path = tmp_path/'legacy.json'
    provision(original.root,'project_fixture',path,PHRASE,data_mode='fixture')
    before = logical_state(original)
    def forbidden(*args,**kwargs): raise AssertionError('readonly startup constructed Store')
    monkeypatch.setattr(Store,'__init__',forbidden)
    monkeypatch.setattr(Store,'attach_existing',forbidden)
    assert len(load_config(path)) == 3
    _,_,auth,controls = load_server_config(path)
    assert controls == {} and auth.credentials['local'].principal.roles == {'viewer'}
    assert logical_state(original) == before
    config = json.loads(path.read_text());config['controls']={}
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError): load_server_config(path)


def test_empty_controls_never_attach_or_upgrade_roles(tmp_path,monkeypatch):
    _,config = fixture_config(tmp_path,roles=('viewer',))
    config['controls'] = {}
    def forbidden(*args,**kwargs): raise AssertionError('readonly startup attached Store')
    monkeypatch.setattr(Store,'attach_existing',forbidden)
    _,_,auth,controls = load_server_config(write_config(tmp_path,config))
    assert controls == {} and auth.credentials['both'].principal.roles == {'viewer'}


def test_enabled_controls_do_not_upgrade_viewer_roles(tmp_path):
    _,config = fixture_config(tmp_path,roles=('viewer',))
    origin,projects,auth,controls = load_server_config(write_config(tmp_path,config))
    _,proposal = bound()
    with TestClient(create_app(projects,auth,origin=origin,control_services=controls),base_url=origin) as client:
        headers = login(client)
        assert post(client,submit_payload(proposal),headers,'viewer-draft').status_code == 403


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(extra='private'),
    lambda c:c['projects'][0].update(extra=True),
    lambda c:c['credentials'][0].update(extra=True),
    lambda c:c['credentials'][0].update(projects=['unknown']),
    lambda c:c['credentials'].append(deepcopy(c['credentials'][0])),
    lambda c:c['projects'].append(deepcopy(c['projects'][0])),
    lambda c:c['projects'].append({**c['projects'][0],'id':'alias'}),
    lambda c:c['controls'].update(unknown=deepcopy(c['controls']['project_fixture'])),
    lambda c:c['controls']['project_fixture'].update(project_id='mismatch'),
    lambda c:c['controls']['project_fixture'].update(data_mode='live'),
    lambda c:c['controls']['project_fixture']['commands']['fixture_test'].update(tool_id='unknown'),
    lambda c:c.update(origin='http://0.0.0.0:8765'),
])
def test_invalid_config_rejected_without_domain_or_schema_changes(tmp_path,mutation):
    store,config = fixture_config(tmp_path);before = logical_state(store)
    mutation(config)
    with pytest.raises(ValueError): load_server_config(write_config(tmp_path,config))
    assert logical_state(store) == before


def test_legacy_api_rejects_new_config_instead_of_discarding_controls(tmp_path):
    _,config = fixture_config(tmp_path)
    with pytest.raises(ValueError):load_config(write_config(tmp_path,config))


@pytest.mark.parametrize('raw',[
    '{"schema_version":"1.1","schema_version":"1.0"}',
    '{"schema_version":"1.1","x":NaN}',
    '{"schema_version":"1.1","x":Infinity}',
    '{"schema_version":"1.1","x":1e309}',
    '['*49+'0'+']'*49,
    ' '* (2*1024*1024+1),
])
def test_bounded_strict_json(raw,tmp_path):
    path=tmp_path/'private.json';path.write_text(raw);path.chmod(0o600)
    with pytest.raises(ValueError):load_server_config(path)


def test_protected_configuration_file(tmp_path):
    _,config = fixture_config(tmp_path)
    path=write_config(tmp_path,config)
    path.chmod(0o644)
    with pytest.raises(ValueError):load_server_config(path)
    path.chmod(0o600)
    link=tmp_path/'alias.json';link.symlink_to(path)
    with pytest.raises(OSError):load_server_config(link)


def test_fifo_configuration_is_rejected_without_waiting_for_a_writer(tmp_path):
    path=tmp_path/'private.fifo';os.mkfifo(path,0o600)
    code = ('import sys\nfrom rlflow.web import load_server_config\n'
            'try: load_server_config(sys.argv[1])\n'
            'except ValueError: pass\n'
            'else: raise AssertionError("FIFO accepted")\n')
    result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,timeout=3)
    assert result.returncode==0,result.stderr


def test_later_invalid_store_does_not_migrate_earlier_project(tmp_path):
    store,config=fixture_config(tmp_path);before=logical_state(store)
    missing=tmp_path/'not_initialized';missing.mkdir(mode=0o700)
    config['projects'].append({'id':'second','root':str(missing),'data_mode':'fixture'})
    second=deepcopy(catalog());second['project_id']='second'
    config['controls']['second']=second
    with pytest.raises(OSError):load_server_config(write_config(tmp_path,config))
    assert logical_state(store)==before and not (missing/'runtime').exists()


def test_attach_trace_contains_no_creation_migration_or_business_writes(tmp_path,monkeypatch):
    store,config=fixture_config(tmp_path);before=logical_state(store);statements=[]
    actual=sqlite3.connect
    def traced(*args,**kwargs):
        db=actual(*args,**kwargs);db.set_trace_callback(statements.append);return db
    monkeypatch.setattr(sqlite3,'connect',traced)
    load_server_config(write_config(tmp_path,config))
    assert statements
    assert not any(s.lstrip().split()[0].upper() in {'CREATE','ALTER','DROP','INSERT','UPDATE','DELETE','REPLACE','VACUUM','REINDEX'} for s in statements)
    assert not any('JOURNAL_MODE=' in s.upper().replace(' ','') for s in statements)
    assert logical_state(store)==before


@pytest.mark.parametrize('damage',[
    "DROP TRIGGER no_update",
    "DROP TABLE snapshot_due",
    "UPDATE projection_meta SET version=version+1",
    "UPDATE observation_meta SET project_id='wrong'",
    "UPDATE observation_meta SET data_mode='live'",
    "UPDATE observation_meta SET store_epoch='invalid epoch'",
    "UPDATE observation_meta SET seq=seq+1",
    "UPDATE observation_meta SET floor=seq+1",
    "UPDATE observation_meta SET floor=-1",
    "UPDATE observation_meta SET enabled=2",
    "UPDATE observation_meta SET paused=2",
])
def test_attach_rejects_unsupported_or_damaged_existing_store_without_repair(tmp_path,damage):
    store,_=fixture_config(tmp_path)
    with store.connect() as db:db.execute(damage)
    with store.read_connection() as db:
        before=tuple(tuple(r) for r in db.execute('SELECT * FROM sqlite_master'))
    with pytest.raises(ValueError):Store.attach_existing(store.root,project_id='project_fixture',data_mode='fixture')
    with store.read_connection() as db:
        assert tuple(tuple(r) for r in db.execute('SELECT * FROM sqlite_master'))==before


@pytest.mark.parametrize('replacement',['TEXT PRIMARY KEY','INTEGER PRIMARY KEY DESC'])
def test_attach_rejects_empty_events_with_non_rowid_primary_key_without_writes(tmp_path,replacement):
    store,_=fixture_config(tmp_path)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
        sql=db.execute("SELECT sql FROM sqlite_master WHERE name='events'").fetchone()[0]
        db.execute('DROP TABLE events')
        db.execute(sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT',replacement))
        db.execute("CREATE TRIGGER no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append only'); END")
        db.execute("CREATE TRIGGER no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append only'); END")
    before=logical_state(store)
    with pytest.raises(Conflict):Store.attach_existing(store.root,project_id='project_fixture',data_mode='fixture')
    assert logical_state(store)==before


def test_attached_store_refuses_missing_or_replaced_database_and_lock(tmp_path):
    store,_=fixture_config(tmp_path)
    attached=Store.attach_existing(store.root,project_id='project_fixture',data_mode='fixture')
    moved=store.db.with_name('held.db');store.db.rename(moved)
    with pytest.raises(OSError):attached.connect()
    assert not store.db.exists()
    store.db.write_bytes(moved.read_bytes())
    with pytest.raises(Conflict):attached.connect()
    store.db.unlink();moved.rename(store.db)
    lock=store.root/'runtime/writer.lock';held=lock.with_name('held.lock');lock.rename(held)
    with pytest.raises(OSError):
        with attached.lock():pass
    assert not lock.exists()
    lock.write_text('')
    with pytest.raises(Conflict):
        with attached.lock():pass


@pytest.mark.parametrize('target',['root','runtime','database','lock'])
def test_attach_rejects_other_writable_paths(tmp_path,target):
    store,_=fixture_config(tmp_path)
    paths={'root':store.root,'runtime':store.root/'runtime','database':store.db,'lock':store.root/'runtime/writer.lock'}
    paths[target].chmod(paths[target].stat().st_mode | 0o020)
    with pytest.raises(ValueError):Store.attach_existing(store.root,project_id='project_fixture',data_mode='fixture')


def test_cli_uses_explicit_loader_and_never_echoes_private_error(tmp_path,monkeypatch,capsys):
    _,config=fixture_config(tmp_path);path=write_config(tmp_path,config);calls=[]
    import uvicorn
    monkeypatch.setattr(uvicorn,'run',lambda app,**kwargs:calls.append((app,kwargs)))
    main(['serve','--config',str(path)])
    assert len(calls)==1 and calls[0][1]['host']=='127.0.0.1'
    assert calls[0][1]['proxy_headers'] is False and calls[0][1]['access_log'] is False
    config['controls']['project_fixture']['commands']['fixture_test']['tool_id']='secret-private-invalid'
    path.write_text(json.dumps(config))
    with pytest.raises(SystemExit) as failure:main(['serve','--config',str(path)])
    assert failure.value.code==2
    error=capsys.readouterr().err
    assert str(path) not in error and 'secret-private-invalid' not in error and PHRASE not in error
