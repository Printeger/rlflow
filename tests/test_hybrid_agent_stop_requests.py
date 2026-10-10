"""Actual original finite owner; no paid model, GPU, or new Core authority."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from copy import copy, deepcopy
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from rlflow.hybrid_agent_stop_requests import validate_public
from rlflow.web_auth import Principal
from rlflow.hybrid_goals import digest
from tests.test_hybrid_finite_host_app import application, ORIGIN, path, start
from tests.test_execution_adapter import setup as native_setup


@pytest.fixture
def requested_application(request, monkeypatch):
    from tests import test_hybrid_finite_host_app as fixture_module
    original = fixture_module.create_finite_host_app
    monkeypatch.setattr(fixture_module, 'create_finite_host_app',
                        lambda *a, **kw: original(*a, **kw, agent_requests=True))
    return request.getfixturevalue('application')


def suggestion(client, services, agent, key='original_stop_suggestion'):
    coordinator = client.app.state.finite_host_stop
    scope = {'scope_sha256': coordinator._scope, 'items': [
        {'project_id': p, 'data_mode': 'fixture', 'store_epoch': e,
         'task_id': t, 'stop_action': a} for p, e, t, a, *_ in coordinator._signature]}
    base = f'/api/v1/projects/{services[0].project_id}/agent-requests'
    response = client.post(base, headers={'Authorization': 'Bearer '+agent,
        'Origin': ORIGIN, 'Idempotency-Key': key},
        json={'action': 'request_finite_stop', 'stop_scope': scope})
    assert response.status_code == 200, response.text
    saved = response.json()
    validate_public(saved, services[0].project_id)
    assert saved['status'] == 'AWAITING_HUMAN'
    return base, saved, scope


def test_actual_suggestion_no_execution_whole_authority_and_lost_STOP_return(requested_application, monkeypatch):
    host, units, services, observers, app, token, headers = requested_application
    auth = services[0].auth
    agent, _ = auth.issue_request_token(Principal('stop_agent', 'agent', {'viewer'},
        {s.project_id for s in services}), ttl=60)
    limited, _ = auth.issue_request_token(Principal('limited_stop_agent', 'agent', {'viewer'},
        {services[0].project_id}), ttl=60)
    coordinator = app.state.finite_host_stop
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        before = [s.store.version() for s in services]
        base, saved, scope = suggestion(client, services, agent)
        assert [s.store.version() for s in services] == before
        assert not any(u._cancelled.is_set() for u in units)
        # Direct SDK copies or a rebound inbox are not the captured authority.
        original_helpers = []
        for service in services:
            original_helpers.append(service.store._hybrid_agent_request_service.stop_requests)
        helper = original_helpers[0]
        for candidate in (copy(helper),):
            with pytest.raises(PermissionError): candidate.submit(scope, token=agent, key='copied_helper')
        anchor = helper.inbox
        try:
            helper.inbox = original_helpers[1].inbox
            with pytest.raises(PermissionError): helper.submit(scope, token=agent, key='rebound_helper')
        finally: helper.inbox = anchor
        assert [s.store.version() for s in services] == before
        assert not any(u._cancelled.is_set() for u in units)
        bad = client.post(base, headers={'Authorization': 'Bearer '+limited,
            'Origin': ORIGIN, 'Idempotency-Key': 'limited'},
            json={'action': 'request_finite_stop', 'stop_scope': scope})
        assert bad.status_code == 403, bad.text
        assert not any(u._cancelled.is_set() for u in units)
        rid = saved['request_id']; url = base+'/'+rid
        own = client.get(url, headers={'Authorization': 'Bearer '+agent})
        assert own.status_code == 200 and 'forwarded_by' not in own.json()
        assert client.get(url, headers={'Authorization': 'Bearer '+limited}).status_code == 404
        human = client.get(url)
        assert human.status_code == 200 and human.json()['original_owner_available']
        assert client.post(url+'/forward', headers=headers,
            json={'request_hash': saved['request_hash'], 'expected_version': before[0]}).status_code == 409
        entered = threading.Event(); register = units[0].runtime._register_release
        def waiting(attempt):
            entered.set(); assert units[0]._cancelled.wait(5)
            return register(attempt)
        monkeypatch.setattr(units[0].runtime, '_register_release', waiting)
        original = coordinator.execute_prepared
        def lost(*a, **kw):
            result = original(*a, **kw)
            assert result['status'] == 'ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
            raise OSError('synthetic lost return after original physical cleanup')
        with ThreadPoolExecutor(max_workers=1) as worker:
            running = worker.submit(client.post, path(services[0])+'/commands', headers=headers,
                                    json=start(services[0]))
            assert entered.wait(8)
            monkeypatch.setattr(coordinator, 'execute_prepared', lost)
            response = client.post(url+'/forward-stop', headers=headers,
                json={'request_hash': saved['request_hash'], 'resume_cleanup': False})
            assert response.status_code == 503, response.text
            assert running.result(timeout=10).status_code == 202
        source = units[0].runtime.sources._issued(units[0].runtime._issued(units[0].lease)['source'])
        assert source['producer'].poll() is not None and all(fd is None for fd in source['fds'].values())
        assert not units[0].runtime._issued(units[0].lease)['release_entered']
        assert all(u._cancelled.is_set() for u in units) and host.pool.snapshot()['occupied'] == 0
        proved = client.get(url, headers={'Authorization': 'Bearer '+agent}).json()
        validate_public(proved, services[0].project_id)
        assert proved['status'] == 'STOPPED_AS_OF_RETURN'
        versions = [s.store.version() for s in services]
        def forbidden(*a, **kw): pytest.fail('read-only retry repeated original STOP work')
        monkeypatch.setattr(coordinator, 'prepare', forbidden)
        for unit in units: monkeypatch.setattr(unit, 'cancel', forbidden)
        for resume in (False, True):
            retry = client.post(url+'/forward-stop', headers=headers,
                json={'request_hash': saved['request_hash'], 'resume_cleanup': resume})
            assert retry.status_code == 200, retry.text
            assert retry.json()['status'] == 'STOPPED_AS_OF_RETURN'
        assert [s.store.version() for s in services] == versions
        assert not proved['result']['goal_completed'] and not proved['result']['durable_aggregate_receipt']
    print('actual_agent_suggestion_STOP', dict(no_suggestion_Core_write=True,
        limited_scope_denied=True, original_CPU_G=False, all_FDs_closed=True,
        pool_occupied=0, lost_return_source_proved=True, retry_cleanup=False), flush=True)


def test_partial_original_cleanup_requires_explicit_resume_known_scope_not_repeated(requested_application, monkeypatch):
    host, units, services, observers, app, token, headers = requested_application
    agent, _ = services[0].auth.issue_request_token(Principal('partial_stop_agent', 'agent',
        {'viewer'}, {s.project_id for s in services}), ttl=60)
    coordinator = app.state.finite_host_stop
    calls = []; original = coordinator._scope_stop
    def partial(service, body, operation):
        calls.append(service)
        if service is services[1]: raise OSError('synthetic original scope unavailable')
        return original(service, body, operation)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        base, saved, _ = suggestion(client, services, agent)
        url = base+'/'+saved['request_id']
        payload = {'request_hash': saved['request_hash'], 'resume_cleanup': False}
        monkeypatch.setattr(coordinator, '_scope_stop', partial)
        response = client.post(url+'/forward-stop', headers=headers, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'PARTIAL_OR_UNKNOWN'
        validate_public(client.get(url, headers={'Authorization': 'Bearer '+agent}).json(), services[0].project_id)
        known_version = services[0].store.version()
        snapshot = tuple(calls)
        retry = client.post(url+'/forward-stop', headers=headers, json=payload)
        assert retry.status_code == 200 and retry.json()['status'] == 'PARTIAL_OR_UNKNOWN'
        assert tuple(calls) == snapshot
        def resumed(service, body, operation):
            calls.append(service)
            assert service is services[1], 'known original scope repeated'
            return original(service, body, operation)
        monkeypatch.setattr(coordinator, '_scope_stop', resumed)
        resumed_response = client.post(url+'/forward-stop', headers=headers,
            json={**payload, 'resume_cleanup': True})
        assert resumed_response.status_code == 200, resumed_response.text
        assert resumed_response.json()['status'] == 'STOPPED_AS_OF_RETURN'
        assert len(calls) == 3 and services[0].store.version() == known_version
        assert host.pool.snapshot()['occupied'] == 0
    print('actual_partial_suggestion_STOP', dict(ordinary_retry_read_only=True,
        explicit_resume_unknown_only=True, known_scope_Core_unchanged=True, pool_occupied=0), flush=True)


def test_disconnected_prepare_waiter_still_hands_off_STOP_and_final_read_does_not_block_loop(requested_application, monkeypatch):
    from rlflow.hybrid_agent_stop_requests import FiniteStopRequests
    from rlflow.hybrid_agent_requests import AgentRequestService
    host, units, services, observers, app, token, headers = requested_application
    agent, _ = services[0].auth.issue_request_token(Principal('disconnect_stop_agent', 'agent',
        {'viewer'}, {s.project_id for s in services}), ttl=60)
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        base, saved, _ = suggestion(client, services, agent)
        prepared = threading.Event(); release_prepare = threading.Event()
        reading = threading.Event(); release_read = threading.Event()
        original_prepare = FiniteStopRequests.prepare
        original_get = AgentRequestService.get
        original_list = AgentRequestService.list
        lists_started = threading.Event(); release_lists = threading.Event(); count = []; count_lock = threading.Lock()
        def held_list(self, *a, **kw):
            with count_lock:
                count.append(True)
                if len(count) == 2: lists_started.set()
            assert release_lists.wait(5)
            return original_list(self, *a, **kw)
        def held_prepare(self, *a, **kw):
            result = original_prepare(self, *a, **kw)
            assert all(u._cancelled.is_set() for u in units)
            prepared.set(); assert release_prepare.wait(5)
            return result
        def held_get(self, *a, **kw):
            if kw.get('method') == 'session':
                reading.set(); assert release_read.wait(5)
            return original_get(self, *a, **kw)
        monkeypatch.setattr(FiniteStopRequests, 'prepare', held_prepare)
        monkeypatch.setattr(AgentRequestService, 'get', held_get)
        monkeypatch.setattr(AgentRequestService, 'list', held_list)
        forward = next(r.endpoint for r in app.routes if getattr(r, 'path', None) ==
            '/api/v1/projects/{project_id}/agent-requests/{request_id}/forward-stop')
        profile = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/api/v1/finite-host')
        def request_for(path, body=None):
            raw = json.dumps(body).encode() if body is not None else b''
            async def receive(): return {'type': 'http.request', 'body': raw, 'more_body': False}
            return Request({'type': 'http', 'method': 'POST' if body else 'GET', 'path': path,
                'query_string': b'', 'headers': [(b'cookie', ('rlflow_session='+token).encode()),
                    (b'origin', ORIGIN.encode()), (b'x-csrf-token', headers['X-CSRF-Token'].encode()),
                    (b'content-type', b'application/json')], 'app': app}, receive)
        async def wait_event(event):
            async with asyncio.timeout(5):
                while not event.is_set(): await asyncio.sleep(.01)
        async def disconnected():
            waiter = asyncio.create_task(forward(request_for(base, {
                'request_hash': saved['request_hash'], 'resume_cleanup': False}),
                services[0].project_id, saved['request_id']))
            try:
                await wait_event(prepared)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError): await waiter
                release_prepare.set()
                await wait_event(reading)
                # Final receipt read is deliberately blocked in its finite
                # worker, yet this SAME event loop can serve the original route.
                reply = await asyncio.wait_for(profile(request_for('/api/v1/finite-host')), .5)
                assert reply.status_code == 200
                assert host.pool.snapshot()['occupied'] == 0
            finally:
                release_prepare.set(); release_read.set()
                await app.state.agent_request_stop_drain()
        with ThreadPoolExecutor(max_workers=4) as ordinary:
            ordinary_reads = [ordinary.submit(client.get, base) for _ in range(4)]
            try:
                assert lists_started.wait(2)  # Both Goal/inbox workers held.
                asyncio.run(disconnected())
            finally: release_lists.set()
            assert all(job.result(timeout=5).status_code == 200 for job in ordinary_reads)
        result = client.get(base+'/'+saved['request_id'], headers={'Authorization': 'Bearer '+agent})
        assert result.status_code == 200 and result.json()['status'] == 'STOPPED_AS_OF_RETURN'
        validate_public(result.json(), services[0].project_id)
        assert app.state.finite_host_stop_pool.pending == 0 and host.pool.snapshot()['occupied'] == 0
    print('actual_detached_STOP_handoff', dict(waiter_cancelled_after_all_latches=True,
        original_cleanup_returned=True, ordinary_inbox_workers_blocked=True,
        same_loop_profile_available=True, pool_occupied=0), flush=True)


def test_scope_drift_inbox_failure_and_cold_claim_never_prove_physical_STOP(requested_application, monkeypatch):
    from contextlib import contextmanager
    from rlflow.hybrid_agent_requests import AgentRequestService
    from rlflow.hybrid_drafts import DraftService
    from rlflow.store import Store
    from rlflow.web_auth import AuthStore, Credential
    host, units, services, observers, app, token, headers = requested_application
    agent, _ = services[0].auth.issue_request_token(Principal('cold_stop_agent', 'agent',
        {'viewer'}, {s.project_id for s in services}), ttl=60)
    coordinator = app.state.finite_host_stop
    inbox = services[0].store._hybrid_agent_request_service
    with TestClient(app, base_url=ORIGIN) as client:
        client.cookies.set('rlflow_session', token)
        before = [s.store.version() for s in services]
        base, saved, scope = suggestion(client, services, agent)
        for field, replacement in (('store_epoch','store_'+'f'*32),('task_id','foreign_task'),
                                   ('stop_action','CANCEL_FIXED_ENGINEERING')):
            drift = deepcopy(scope); drift['items'][0][field] = replacement
            drift['scope_sha256'] = digest([[r['project_id'],r['store_epoch'],r['task_id'],r['stop_action']] for r in drift['items']])
            rejected = client.post(base, headers={'Authorization':'Bearer '+agent,
                'Origin':ORIGIN,'Idempotency-Key':'drift_'+field},
                json={'action':'request_finite_stop','stop_scope':drift})
            assert rejected.status_code == 409, rejected.text
        url = base+'/'+saved['request_id']
        payload = {'request_hash':saved['request_hash'],'resume_cleanup':False}
        @contextmanager
        def unavailable(**kw):
            raise OSError('synthetic inbox unavailable before durable claim')
            yield
        with monkeypatch.context() as patch:
            patch.setattr(inbox, '_db', unavailable)
            assert client.post(url+'/forward-stop', headers=headers,json=payload).status_code == 503
        assert client.get(url).json()['status'] == 'AWAITING_HUMAN'
        assert not any(u._cancelled.is_set() for u in units)
        assert [s.store.version() for s in services] == before
        def no_handoff(*a, **kw): raise OSError('synthetic original owner handoff failure after durable claim')
        with monkeypatch.context() as patch:
            patch.setattr(coordinator,'prepare',no_handoff)
            assert client.post(url+'/forward-stop',headers=headers,json=payload).status_code == 503
        original_report = client.get(url).json()
        assert original_report['status'] == 'UNKNOWN' and original_report['result'] is None
        assert not any(u._cancelled.is_set() for u in units)
        assert [s.store.version() for s in services] == before
        # A separately provisioned cold reader gets only the persisted inbox,
        # not the original execution owner/cache or cleanup authority.
        cold = Store(services[0].store.root)
        phrase = 'isolated cold reader fixture passphrase'
        auth = AuthStore([Credential.create(Principal('fixture_human','human',{'operator'},
            {s.project_id for s in services}),phrase)])
        drafts = DraftService(cold,auth,project_id=services[0].project_id,data_mode='fixture',origin=ORIGIN)
        reader = AgentRequestService(drafts)
        fresh, _ = auth.login('fixture_human',phrase)
        result = reader.get(saved['request_id'],token=fresh,method='session')
        assert result['status']=='UNKNOWN' and result['result'] is None and not result['original_owner_available']
        assert reader.stop_requests is None and cold.version() == before[0]
    print('actual_finite_request_failclosed',dict(scope_drift_zero_latch=True,
        inbox_failure_not_forwarded=True,durable_claim_not_physical_proof=True,cold_result='UNKNOWN'),flush=True)
