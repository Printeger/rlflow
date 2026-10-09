"""Human commands reach actual fixed CPU Popen/G/ACK/STOP, no model called."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import json
import os
import select
import signal
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from rlflow.hybrid_fixture_runtime_control import FixtureRuntimeControlService
from rlflow.store import Conflict
from rlflow.web_auth import AuthStore, Credential, Principal
from rlflow.web_api import Project, create_app
from tests.test_hybrid_fixture_runtime import runtime, native_setup, register

ORIGIN = 'http://127.0.0.1:8765'
PHRASE = 'Working plan isolated synthetic fixture passphrase'


def setup(context, scenario='running', *, origin=ORIGIN, max_jobs=4):
    owner = context[0]; lease = register(context, scenario)
    auth = owner.store._hybrid_auth_owner
    token, access = auth.login('fixture_human', PHRASE)
    service = FixtureRuntimeControlService(owner, auth, origin=origin)
    project = owner.workspace.project_id
    app = create_app([Project(project, str(owner.store.root), 'fixture')], auth,
        origin=origin, max_control_jobs=max_jobs, fixture_task_readers={project:service.reader}, fixture_runtime_services={project:service})
    headers = {'Origin':origin, 'X-CSRF-Token':access.csrf, 'Idempotency-Key':'start'}
    attempt = owner._issued(lease)
    selector = attempt['ready']['source_context']['budget_reservation']['reservation_id']
    path = '/api/v1/projects/'+project+'/fixture-tasks/'+selector+'/commands'
    body = {'action':'START_FIXED_CPU', 'task_id':attempt['origin']['task_id'],
            'expected_state_version':owner.store.version()}
    return owner, lease, service, app, token, headers, path, body


def execute(service, body, token, headers, key='start'):
    return service.execute(body, token=token, csrf=headers['X-CSRF-Token'],
                           origin=headers['Origin'], idempotency_key=key)


def test_actual_human_start_stop_and_original_receipts(runtime):
    owner, lease, service, app, token, headers, path, body = setup(runtime)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 202, response.text
        receipt = response.json()
        assert receipt['status'] == 'ACCEPTED' and receipt['recorded_phase'] == 'HANDOFF_UNKNOWN'
        attempt = owner._issued(lease)
        assert owner._current(attempt)['fixture_runtime']['phase'] == 'STARTED_AS_OBSERVED'
        process = owner.sources._issued(attempt['source'])['producer']
        before = owner.store.version()
        duplicate = client.post(path, headers=headers, json=body)
        assert duplicate.status_code == 202 and duplicate.json()['duplicate']
        assert owner.store.version() == before and owner.sources._issued(attempt['source'])['producer'] is process
        conflicting = {**body, 'action':'STOP_FIXED_SCOPE'}
        assert client.post(path, headers=headers, json=conflicting).status_code == 409
        assert client.post(path, headers={**headers,'Idempotency-Key':'another-start'}, json=body).status_code == 409
        stop = {**conflicting, 'expected_state_version':owner.store.version()}
        stopped = client.post(path, headers={**headers,'Idempotency-Key':'stop'}, json=stop)
        assert stopped.status_code == 202, stopped.text
        assert stopped.json()['recorded_phase'] == 'STOP_REQUESTED'
        assert process.poll() is not None and owner.pool.snapshot()['occupied'] == 0
        assert owner._current(attempt)['fixture_runtime']['phase'] == 'FIXTURE_SCOPE_STOPPED'
        get = client.get('/api/v1/projects/'+service.project_id+'/fixture-commands/'+receipt['command_id'])
        assert get.status_code == 200 and get.json()['request_hash'] == receipt['request_hash']
        assert owner.store.audit()['version'] == owner.store.version()


def test_scope_auth_body_and_bound_original_owner_deny_bypass(runtime):
    owner, lease, service, app, token, headers, path, body = setup(runtime)
    with pytest.raises(PermissionError): owner.start(lease)
    with pytest.raises(Conflict): FixtureRuntimeControlService(owner, service.auth, origin=ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post(path, headers=headers, json=body).status_code == 401
        bearer, _ = service.auth.issue_bearer(Principal('viewer', 'human', {'viewer'}, {service.project_id}), ttl=60)
        assert client.post(path, headers={**headers,'Authorization':'Bearer '+bearer}, json=body).status_code == 403
        client.cookies.set('rlflow_session', token)
        assert client.post(path, headers={**headers,'X-CSRF-Token':'wrong'}, json=body).status_code == 403
        assert client.post(path, headers={**headers,'Origin':'https://other.invalid'}, json=body).status_code == 403
        assert client.post(path, headers=headers, json={**body,'command':'unsafe'}).status_code == 400
        assert client.post(path, headers=headers, json={**body,'expected_state_version':True}).status_code == 400
    assert not owner._issued(lease)['spawn_entered']


def test_actual_writer_wait_session_revoke_denies_before_acceptance(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    authenticated = threading.Event(); original = service._session
    def preauth(*args):
        result = original(*args); authenticated.set(); return result
    monkeypatch.setattr(service, '_session', preauth)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with owner.store.lock():
            future = worker.submit(execute, service, body, token, headers)
            assert authenticated.wait(3)
            service.auth.revoke(token)
        with pytest.raises(PermissionError): future.result(timeout=5)
    assert owner._current(owner._issued(lease))['fixture_runtime']['phase'] == 'REGISTER_NO_HANDOFF'
    assert not owner._issued(lease)['spawn_entered']


@pytest.mark.parametrize('phase', ['HANDOFF_UNKNOWN', 'RELEASE_INTENT'])
def test_last_actual_effect_session_expiry_denies_spawn_or_g(runtime, monkeypatch, phase):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    clock = [service.auth.clock()]; monkeypatch.setattr(service.auth, 'clock', lambda:clock[0])
    original = owner._final_effect_gate; reached = []
    def expire(guard):
        if json.loads(guard.raw)['request']['fixture_runtime']['phase'] == phase:
            clock[0] += 1000; reached.append(phase)
        return original(guard)
    monkeypatch.setattr(owner, '_final_effect_gate', expire)
    receipt = execute(service, body, token, headers)
    attempt = owner._issued(lease)
    assert reached and receipt['status'] == 'ACCEPTED' and not attempt['release_entered']
    if phase == 'HANDOFF_UNKNOWN':
        assert not attempt['spawn_entered']
        owner.shutdown_safety()
        assert owner.pool.snapshot()['occupied'] == 1
    else:
        assert attempt['spawn_entered'] and attempt['producer_identity'] is not None


def test_original_post_g_ack_after_session_and_controller_expiry_is_observation_only(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    clock = [service.auth.clock()]; monkeypatch.setattr(service.auth, 'clock', lambda:clock[0])
    release = owner.sources._runtime_release
    def expired_after_real_g(*args):
        result = release(*args); clock[0] += 1000; return result
    monkeypatch.setattr(owner.sources, '_runtime_release', expired_after_real_g)
    receipt = execute(service, body, token, headers)
    assert receipt['status'] == 'ACCEPTED' and owner._issued(lease)['release_entered']
    runtime[6][0] += timedelta(seconds=120); runtime[7][0] += 120*10**9
    deadline = time.monotonic()+4
    while time.monotonic()<deadline:
        observed = owner.poll(lease)
        if observed['phase'] == 'STARTED_AS_OBSERVED': break
        time.sleep(.01)
    assert observed['phase'] == 'STARTED_AS_OBSERVED'
    with pytest.raises(PermissionError): owner.start(lease)
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0


def test_accepted_stop_continues_real_reap_free_after_session_expiry(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    execute(service, body, token, headers)
    process = owner.sources._issued(owner._issued(lease)['source'])['producer']
    clock = [service.auth.clock()]; monkeypatch.setattr(service.auth, 'clock', lambda:clock[0])
    committed = service._committed; expired = []
    def expire_after_acceptance(value):
        committed(value)
        if value['request']['fixture_runtime']['phase'] == 'STOP_REQUESTED':
            expired.append(True); clock[0] += 1000
    monkeypatch.setattr(service, '_committed', expire_after_acceptance)
    receipt = execute(service, {**body,'action':'STOP_FIXED_SCOPE','expected_state_version':owner.store.version()}, token, headers, 'stop')
    assert expired and receipt['recorded_phase'] == 'STOP_REQUESTED'
    assert process.poll() is not None and owner.pool.snapshot()['occupied'] == 0
    assert owner._current(owner._issued(lease))['fixture_runtime']['phase'] == 'FIXTURE_SCOPE_STOPPED'


def test_actual_accept_commit_lost_return_retry_receipt_only_and_no_backfill(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    transaction = owner.controller.token_transaction; injected = []
    @contextmanager
    def lost(*args, **kwargs):
        with transaction(*args, **kwargs) as context: yield context
        guard = owner._active
        if guard is not None and json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'HANDOFF_UNKNOWN' and not injected:
            injected.append(True); raise OSError('actual accept COMMIT lost return')
    with monkeypatch.context() as patch:
        patch.setattr(owner.controller, 'token_transaction', lost)
        receipt = execute(service, body, token, headers)
    before = owner.store.version()
    duplicate = execute(service, body, token, headers)
    assert injected and duplicate['duplicate'] and duplicate['command_id'] == receipt['command_id']
    assert not owner._issued(lease)['spawn_entered'] and owner.store.version() == before
    with pytest.raises(Conflict, match='idempotency'):
        execute(service, {**body,'task_id':'another_task'}, token, headers)
    with pytest.raises(Conflict, match='already'):
        execute(service, body, token, headers, 'new-key')
    owner.shutdown_safety()
    assert owner.pool.snapshot()['occupied'] == 1
    assert service.receipt(receipt['command_id'])['status'] == 'ACCEPTED'
    with pytest.raises(PermissionError): execute(service, body, token, headers)


def test_actual_loopback_disconnect_retry_one_popen_and_stop(runtime, monkeypatch):
    import uvicorn
    listener = socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(16)
    origin = 'http://127.0.0.1:'+str(listener.getsockname()[1])
    owner, lease, service, app, token, headers, path, body = setup(runtime, origin=origin)
    arrived, release = threading.Event(), threading.Event(); calls = []
    gate = owner._final_effect_gate; spawn = owner.sources._runtime_spawn
    def paused(guard):
        if json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'HANDOFF_UNKNOWN':
            arrived.set(); assert release.wait(5)
        return gate(guard)
    def count(*args):
        result = spawn(*args); calls.append(result); return result
    monkeypatch.setattr(owner, '_final_effect_gate', paused)
    monkeypatch.setattr(owner.sources, '_runtime_spawn', count)
    server = uvicorn.Server(uvicorn.Config(app, loop='asyncio', log_level='error', access_log=False, proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}); thread.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        raw = json.dumps(body).encode()
        request = ('POST '+path+' HTTP/1.1\r\nHost: '+origin.split('://')[1]+'\r\nOrigin: '+origin+
            '\r\nCookie: rlflow_session='+token+'\r\nX-CSRF-Token: '+headers['X-CSRF-Token']+
            '\r\nIdempotency-Key: start\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+
            '\r\nConnection: close\r\n\r\n').encode()+raw
        with socket.create_connection(listener.getsockname(), timeout=3) as disconnected:
            disconnected.sendall(request)
        assert arrived.wait(5) and app.state.fixture_start_pool.pending == 1
        release.set()
        with httpx.Client(base_url=origin, trust_env=False, timeout=15, cookies={'rlflow_session':token}) as client:
            response = client.post(path, headers=headers, json=body)
            assert response.status_code == 202, response.text
            assert response.json()['duplicate'] and len(calls) == 1
            stop = {**body,'action':'STOP_FIXED_SCOPE','expected_state_version':owner.store.version()}
            stopped = client.post(path, headers={**headers,'Idempotency-Key':'stop'}, json=stop)
            assert stopped.status_code == 202, stopped.text
            assert owner.pool.snapshot()['occupied'] == 0
    finally:
        release.set(); server.should_exit = True; thread.join(5); listener.close()
        assert not thread.is_alive()


def test_retained_failed_acceptance_cannot_be_rebound_to_new_key_or_actor(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    commit = owner.store._commit; injected = []
    def fail_before(db, *args, **kwargs):
        guard = kwargs.get('_authorization')
        if guard is not None and guard.owner is owner and json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'HANDOFF_UNKNOWN':
            injected.append(True); raise OSError('acceptance before COMMIT')
        return commit(db, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(owner.store, '_commit', fail_before)
        with pytest.raises(OSError): execute(service, body, token, headers)
    raw = owner._issued(lease)['entries']['HANDOFF_UNKNOWN']
    with pytest.raises(Conflict, match='idempotency'): execute(service, body, token, headers, 'different-key')
    other = Principal('other_operator', 'human', {'operator'}, {service.project_id})
    service.auth.credentials[other.id] = Credential.create(other, PHRASE)
    other_token, other_access = service.auth.login(other.id, PHRASE)
    with pytest.raises(Conflict, match='idempotency'):
        execute(service, body, other_token, {**headers,'X-CSRF-Token':other_access.csrf})
    assert injected and not owner._issued(lease)['spawn_entered']
    assert owner._issued(lease)['entries']['HANDOFF_UNKNOWN'] == raw
    accepted = execute(service, body, token, headers)
    assert accepted['actor_id'] == 'fixture_human' and owner._issued(lease)['release_entered']
    owner.stop_to_terminal(lease)


@pytest.mark.parametrize('failure', ['commit_return', 'pool_return'])
def test_original_http_stop_retry_finishes_known_durable_acceptance(runtime, monkeypatch, failure):
    owner, lease, service, app, token, headers, path, body = setup(runtime)
    execute(service, body, token, headers)
    process = owner.sources._issued(owner._issued(lease)['source'])['producer']
    committed = service._committed; pool_change = owner.pool._fixture_runtime_change; failed = []
    def lost_commit(value):
        if value['request']['fixture_runtime']['phase'] == 'STOP_REQUESTED' and not failed:
            failed.append(True); raise OSError('STOP actual COMMIT lost return before accepted flag')
        return committed(value)
    def lost_pool(*args):
        result = pool_change(*args)
        if args[2] == 'FIXTURE_STOP_REQUESTED' and not failed:
            failed.append(True); raise OSError('STOP actual Pool COMMIT lost return')
        return result
    stop = {**body,'action':'STOP_FIXED_SCOPE','expected_state_version':owner.store.version()}
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        with monkeypatch.context() as patch:
            if failure == 'commit_return': patch.setattr(service, '_committed', lost_commit)
            else: patch.setattr(owner.pool, '_fixture_runtime_change', lost_pool)
            first = client.post(path, headers={**headers,'Idempotency-Key':'stop'}, json=stop)
        assert first.status_code == 202 and failed
        assert owner._current(owner._issued(lease))['fixture_runtime']['phase'] == 'STOP_REQUESTED'
        second = client.post(path, headers={**headers,'Idempotency-Key':'stop'}, json=stop)
        assert second.status_code == 202 and second.json()['duplicate'], second.text
        assert second.json()['command_id'] == first.json()['command_id']
        assert process.poll() is not None and owner.pool.snapshot()['occupied'] == 0
        assert owner._current(owner._issued(lease))['fixture_runtime']['phase'] == 'FIXTURE_SCOPE_STOPPED'


def test_final_actual_accept_commit_session_expiry_rolls_back(runtime, monkeypatch):
    owner, lease, service, _, token, headers, _, body = setup(runtime)
    clock = [service.auth.clock()]; monkeypatch.setattr(service.auth, 'clock', lambda:clock[0])
    final = owner._final_deadlines; expired = []
    def expires_before_commit(guard, now, mono):
        if json.loads(guard.raw)['request']['fixture_runtime']['phase'] == 'HANDOFF_UNKNOWN':
            expired.append(True); clock[0] += 1000
        return final(guard, now, mono)
    monkeypatch.setattr(owner, '_final_deadlines', expires_before_commit)
    before = owner.store.version()
    with pytest.raises(PermissionError): execute(service, body, token, headers)
    assert expired and owner.store.version() == before
    assert not owner._issued(lease)['spawn_entered']
    assert owner._current(owner._issued(lease))['fixture_runtime']['phase'] == 'REGISTER_NO_HANDOFF'


def test_stop_reserved_lane_and_actual_pool_lock_wait_finish_without_start_capacity(runtime, monkeypatch):
    owner, lease, service, app, token, headers, path, body = setup(runtime, max_jobs=1)
    execute(service, body, token, headers)
    busy, finish, stop_seen = threading.Event(), threading.Event(), threading.Event()
    def busy_start_lane():
        busy.set(); return finish.wait(10)
    session = service._session
    def noticed(*args):
        result = session(*args); stop_seen.set(); return result
    monkeypatch.setattr(service, '_session', noticed)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        blocked = client.portal.start_task_soon(app.state.fixture_start_pool.run, busy_start_lane)
        assert busy.wait(3) and app.state.fixture_start_pool.pending == 1
        try:
            stop = {**body,'action':'STOP_FIXED_SCOPE','expected_state_version':owner.store.version()}
            with ThreadPoolExecutor(max_workers=1) as http:
                with owner.pool._lock:
                    future = http.submit(client.post, path, headers={**headers,'Idempotency-Key':'stop'}, json=stop)
                    assert stop_seen.wait(3)
                    assert not future.done() and app.state.fixture_stop_pool.pending == 1
                response = future.result(timeout=8)
            assert response.status_code == 202, response.text
            assert owner.pool.snapshot()['occupied'] == 0
            assert app.state.fixture_start_pool.pending == 1  # actual busy future retained
        finally:
            finish.set(); assert blocked.result(timeout=3)


def test_actual_fork_with_inherited_locked_auth_denies_before_sql_and_parent_still_works(runtime):
    owner, lease, service, app, token, headers, path, body = setup(runtime)
    assert app.state.fixture_start_pool.executor.submit(lambda:True).result(timeout=3)
    held, release = threading.Event(), threading.Event()
    def holder():
        with service.auth._lock:
            held.set(); assert release.wait(10)
    thread = threading.Thread(target=holder); thread.start()
    assert held.wait(3)
    read_fd, write_fd = os.pipe(); child = None; reaped = False
    try:
        child = os.fork()
        if child == 0:
            os.close(read_fd)
            try:
                def forbidden(*args, **kwargs): raise AssertionError('child must not reach SQL/Popen/G')
                owner.store.connect = owner.store.read_connection = forbidden
                owner.sources._runtime_spawn = owner.sources._runtime_release = forbidden
                try: execute(service, body, token, headers)
                except PermissionError: pass
                else: raise AssertionError('fork child direct command not denied')
                with TestClient(app, base_url=ORIGIN) as client:
                    client.cookies.set('rlflow_session', token)
                    response = client.post(path, headers=headers, json=body)
                    assert response.status_code == 403
                os.write(write_fd, b'DENIED_BEFORE_AUTH_SQL')
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(write_fd); write_fd = None
        assert select.select([read_fd], [], [], 5)[0], 'child inherited Auth lock caused unbounded wait'
        assert os.read(read_fd, 64) == b'DENIED_BEFORE_AUTH_SQL'
        pid, status = os.waitpid(child, 0); reaped = True
        assert pid == child and os.waitstatus_to_exitcode(status) == 0
    finally:
        release.set(); thread.join(3)
        if child not in (None, 0) and not reaped:
            os.kill(child, signal.SIGKILL); os.waitpid(child, 0)
        os.close(read_fd)
        if write_fd is not None: os.close(write_fd)
        assert not thread.is_alive()
    assert owner._live and not owner._issued(lease)['spawn_entered']
    assert app.state.fixture_start_pool.executor.submit(lambda:True).result(timeout=3)
    receipt = execute(service, body, token, headers)
    assert receipt['status'] == 'ACCEPTED' and owner._issued(lease)['release_entered']
    owner.stop_to_terminal(lease)
    assert owner.pool.snapshot()['occupied'] == 0
