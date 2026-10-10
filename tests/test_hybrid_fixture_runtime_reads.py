"""Actual fixed CPU facts through opt-in read-only HTTP, no execution control."""
import json
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_budget_ledger import SECTIONS, derived_heads, entry_key
from rlflow.hybrid_fixture_runtime_reads import FixtureTaskReader
from rlflow.store import Conflict, Store, canonical
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Credential, Principal
from tests.test_hybrid_fixture_runtime import runtime, native_setup, register, observed

ORIGIN = 'http://127.0.0.1:8765'
PHRASE = 'synthetic fixture Task reading passphrase'


def setup(context, origin=ORIGIN):
    owner = context[0]; project = owner.workspace.project_id
    reader = FixtureTaskReader(owner.store, project_id=project, store_epoch=owner.workspace.store_epoch)
    viewer = Principal('viewer', 'human', {'viewer'}, {project})
    other = Principal('other', 'human', {'viewer'}, {'another_project'})
    auth = AuthStore([Credential.create(p, PHRASE) for p in (viewer, other)])
    app = create_app([Project(project, str(owner.store.root), 'fixture')], auth,
                     origin=origin, fixture_task_readers={project: reader})
    token, _ = auth.issue_bearer(viewer)
    return reader, app, auth, {'Authorization': 'Bearer ' + token}, '/api/v1/projects/' + project + '/fixture-tasks'


def selector(owner, lease):
    return owner._issued(lease)['ready']['source_context']['budget_reservation']['reservation_id']


def test_actual_running_and_stopped_facts_read_without_poll_or_capability(runtime, monkeypatch):
    owner = runtime[0]; lease = register(runtime, 'running')
    owner.start(lease); observed(owner, lease)
    reader, app, auth, headers, base = setup(runtime)
    key = selector(owner, lease); origin = owner._issued(lease)['origin']
    before = owner.store.version()
    with monkeypatch.context() as patch:
        patch.setattr(owner, 'poll', lambda *a, **k: pytest.fail('GET must not poll/write'))
        patch.setattr(owner.sources, 'poll', lambda *a, **k: pytest.fail('GET must not read private live source'))
        with TestClient(app, base_url=ORIGIN) as client:
            page = client.get(base, headers=headers)
            assert page.status_code == 200 and len(page.json()['items']) == 1
            response = client.get(base + '/' + key + '/timeline', headers=headers)
            assert response.status_code == 200
            body = response.json(); task = body['task']
            assert task['id'] == origin['task_id'] and task['recorded_phase'] == 'STARTED_AS_OBSERVED'
            assert task['current_execution_status'] == 'UNKNOWN' and task['controls_available'] is False
            assert [event['recorded_phase'] for event in body['events']] == [
                'REGISTER_NO_HANDOFF', 'HANDOFF_UNKNOWN', 'PROCESS_REGISTERED', 'RELEASE_INTENT', 'STARTED_AS_OBSERVED']
            wire = response.text
            for secret in (origin['nonce'], str(owner.store.root), 'producer', 'boot_id', 'program_sha256', 'lease_id'):
                assert secret not in wire
            assert owner.store.version() == before
    owner.stop_to_terminal(lease)
    final = reader.task(key, timeline=True)
    assert final['task']['recorded_phase'] == 'FIXTURE_SCOPE_STOPPED'
    assert final['task']['resource_release_status'] == 'NOT_OBSERVED'
    assert len(final['events']) == 7 and final['task']['recorded_wall_seconds'] >= 0
    cold = Store.attach_existing(owner.store.root, project_id=reader.project_id, data_mode='fixture')
    historical = FixtureTaskReader(cold, project_id=reader.project_id, store_epoch=reader.store_epoch)
    assert historical.task(key, timeline=True) == final
    assert not owner.store.objects('tasks') and not owner.store.objects('sessions')


def test_default_api_disabled_and_auth_scope_closed_queries(runtime):
    owner = runtime[0]; lease = register(runtime)
    reader, app, auth, headers, base = setup(runtime); key = selector(owner, lease)
    default = create_app([Project(reader.project_id, str(owner.store.root), 'fixture')], auth)
    with TestClient(default, base_url=ORIGIN) as client:
        assert client.get(base, headers=headers).status_code == 404
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(base).status_code == 401
        other, _ = auth.login('other', PHRASE)
        assert client.get(base, cookies={'rlflow_session': other}).status_code == 404
        for query in ('?limit=0', '?limit=21', '?limit=01&limit=1', '?limit=1.0', '?x=1', '?after=../bad'):
            assert client.get(base+query, headers=headers).status_code == 400
        assert client.get(base+'/'+key+'?poll=1', headers=headers).status_code == 400
        assert client.get(base+'/missing', headers=headers).status_code == 404
        assert client.post(base+'/'+key, headers=headers, json={'action':'start'}).status_code == 405
        assert client.get(base, headers={**headers, 'Origin':'https://other.invalid'}).status_code == 403
        auth.revoke(headers['Authorization'].split(' ', 1)[1])
        assert client.get(base, headers=headers).status_code == 401


def test_epoch_and_startup_project_mismatch_fail_closed(runtime):
    owner = runtime[0]; register(runtime)
    reader, app, auth, headers, base = setup(runtime)
    wrong = FixtureTaskReader(owner.store, project_id=reader.project_id, store_epoch='another_epoch')
    with pytest.raises(Conflict): wrong.tasks()
    with pytest.raises(Conflict):
        create_app([Project(reader.project_id, str(owner.store.root), 'fixture')], auth,
                   fixture_task_readers={reader.project_id: wrong})
    with pytest.raises(ValueError):
        create_app([Project(reader.project_id, str(owner.store.root), 'live')], auth,
                   fixture_task_readers={reader.project_id: reader})


def test_sparse_indexed_page_advances_scanned_key_and_read_budget(runtime, monkeypatch):
    owner = runtime[0]
    reader, *_ = setup(runtime)
    assert reader.tasks(limit=1)['items'] == []  # real HELD, not yet a Task
    lease = register(runtime); key = selector(owner, lease)
    with owner.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # A deliberately corrupt fake projection cannot become a real Task.
        db.execute('INSERT INTO projection(section,object_key,value,version) VALUES(?,?,?,?)',
                   (SECTIONS[2], 'a_nonruntime', canonical({}).decode(), owner.store.version()))
        db.commit()
    with pytest.raises(Conflict): reader.tasks(limit=1)
    with owner.store.connect() as db:
        db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], 'a_nonruntime'))
    assert reader.tasks(after=key)['items'] == []
    assert reader.tasks(limit=1)['next_after'] is None
    with owner.store.read_connection() as db:
        plans = [row['detail'] for row in db.execute('EXPLAIN QUERY PLAN SELECT object_key FROM projection '
            'WHERE section=? AND object_key>? ORDER BY object_key LIMIT ?', (SECTIONS[2], '', 2))]
    assert any('SEARCH' in plan and 'INDEX' in plan for plan in plans)


@pytest.mark.parametrize('damage', ['head', 'event', 'missing_head'])
def test_whole_original_source_proof_rejects_corruption(runtime, damage):
    owner = runtime[0]; lease = register(runtime)
    reader, *_ = setup(runtime); key = selector(owner, lease)
    with owner.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        original_head = tuple(db.execute('SELECT * FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], key)).fetchone())
        if damage == 'head':
            row = db.execute('SELECT value FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], key)).fetchone()
            value = json.loads(row['value']); value['last_entry_hash'] = 'sha256:'+'0'*64
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?', (canonical(value).decode(), SECTIONS[2], key))
        elif damage == 'missing_head':
            db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], key))
        else:
            # Private disposable fixture only; restore exact original event
            # and immutable trigger before original-owner teardown.
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='events' AND sql LIKE '%UPDATE%'").fetchone()[0]
            name = db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events' AND sql LIKE '%UPDATE%'").fetchone()[0]
            db.execute('DROP TRIGGER "'+name+'"')
            fact = owner._issued(lease)['entries']['REGISTER_NO_HANDOFF']; event_key = entry_key(fact['request'])
            row = db.execute('SELECT input_versions FROM events WHERE idempotency_key=?', (event_key,)).fetchone()
            db.execute('UPDATE events SET input_versions=? WHERE idempotency_key=?', ('{}', event_key))
        db.commit()
    try:
        with pytest.raises(Conflict): reader.task(key, timeline=True)
        _, app, _, headers, base = setup(runtime)
        with TestClient(app, base_url=ORIGIN) as client:
            response = client.get(base+'/'+key+'/timeline', headers=headers)
            assert response.status_code == 503 and response.json()['code'] == 'UNSUPPORTED_CAPABILITY'
    finally:
        with owner.store.connect() as db:
            if damage == 'event':
                db.execute('UPDATE events SET input_versions=? WHERE idempotency_key=?', (row[0], event_key)); db.execute(trigger)
            else:
                db.execute('INSERT OR REPLACE INTO projection VALUES(?,?,?,?,?)', original_head)


def test_sql_key_byte_bound_and_post_read_revocation(runtime, monkeypatch):
    owner = runtime[0]; lease = register(runtime)
    reader, app, auth, headers, base = setup(runtime)
    huge_key = 'a' * (2*1024**2)
    with owner.store.connect() as db:
        db.execute('INSERT INTO projection(section,object_key,value,version) VALUES(?,?,?,?)',
                   (SECTIONS[2], huge_key, '{}', owner.store.version()))
    try:
        with pytest.raises(Conflict): reader.tasks(limit=1)
        with TestClient(app, base_url=ORIGIN) as client:
            assert client.get(base+'?limit=1', headers=headers).status_code == 503
    finally:
        with owner.store.connect() as db:
            db.execute('DELETE FROM projection WHERE section=? AND object_key=?', (SECTIONS[2], huge_key))
    task = reader.task
    def revoked(*args, **kwargs):
        result = task(*args, **kwargs)
        auth.revoke(headers['Authorization'].split(' ', 1)[1])
        return result
    monkeypatch.setattr(reader, 'task', revoked)
    # The previous application's lifespan drained and permanently closed its
    # workers. A new server lifetime needs fresh startup-bound read capacity.
    app = create_app([Project(reader.project_id, str(owner.store.root), 'fixture')], auth,
                     origin=ORIGIN, fixture_task_readers={reader.project_id: reader})
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get(base+'/'+selector(owner, lease), headers=headers).status_code == 401


def test_actual_owned_loopback_socket_serves_original_task(runtime):
    import uvicorn
    owner = runtime[0]; lease = register(runtime)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(8)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    reader, app, auth, headers, base = setup(runtime, origin)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False,
                                          proxy_headers=False, loop='asyncio'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]})
    thread.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        with httpx.Client(base_url=origin, trust_env=False, timeout=5) as client:
            response = client.get(base+'/'+selector(owner, lease)+'/timeline', headers=headers)
            assert response.status_code == 200
            assert response.json()['events'][0]['recorded_phase'] == 'REGISTER_NO_HANDOFF'
            assert response.headers['cache-control'] == 'no-store'
    finally:
        server.should_exit = True; thread.join(5); listener.close()
        assert not thread.is_alive()
