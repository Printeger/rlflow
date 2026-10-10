"""Owned original finite CPU/engineering fixture, request client and human UI."""
import json
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from rlflow.agent_client import AgentClient
from rlflow.web_auth import Principal
from tests.test_execution_adapter import setup as native_setup
from tests import test_hybrid_finite_host_app as shared_app


def main():
    root = Path(sys.argv[1]).resolve()
    # Match the explicitly preprovisioned original fixture origin. Never kill
    # an incumbent listener or rebind an already approved service on collision.
    sock = socket.socket(); sock.bind(('127.0.0.1', 8765))
    origin = shared_app.ORIGIN
    patch = pytest.MonkeyPatch(); factory = shared_app.create_finite_host_app
    patch.setattr(shared_app, 'create_finite_host_app',
                  lambda *a, **kw: factory(*a, **kw, agent_requests=True))
    native = native_setup.__wrapped__(root, patch)
    fixture = shared_app.application.__wrapped__(root, native, patch)
    host, units, services, observers, app, _, _ = next(fixture)
    coordinator = app.state.finite_host_stop
    agent, _ = services[0].auth.issue_request_token(Principal('browser_stop_agent', 'agent',
        {'viewer'}, {s.project_id for s in services}), ttl=60)
    target = root/'target'; (target/'.rlflow').mkdir(parents=True)
    (target/'.rlflow/project.yaml').write_text(json.dumps({'schema_version': '1.0',
        'project_id': services[0].project_id, 'control_origin': origin}))
    client = AgentClient(cwd=target, environ={'RLFLOW_CONTROL_ORIGIN': origin,
                                             'RLFLOW_REQUEST_TOKEN': agent})
    scope = {'scope_sha256': coordinator._scope, 'items': [
        {'project_id': p, 'data_mode': 'fixture', 'store_epoch': e,
         'task_id': t, 'stop_action': a} for p, e, t, a, *_ in coordinator._signature]}
    entered = threading.Event(); register = units[0].runtime._register_release
    def waiting(attempt):
        entered.set(); assert units[0]._cancelled.wait(10)
        return register(attempt)
    patch.setattr(units[0].runtime, '_register_release', waiting)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False,
                                          proxy_headers=False))
    def inspect():
        attempt = units[0].runtime._issued(units[0].lease)
        source = None if not attempt['spawn_entered'] else units[0].runtime.sources._issued(attempt['source'])
        return {'versions': [s.store.version() for s in services],
            'occupied': host.pool.snapshot()['occupied'], 'pre_G_entered': entered.is_set(),
            'release_entered': attempt['release_entered'],
            'all_cancelled': all(u._cancelled.is_set() for u in units),
            'producer_reaped': source is not None and source['producer'].poll() is not None,
            'all_FDs_closed': source is not None and all(fd is None for fd in source['fds'].values())}
    def controls():
        try:
            for line in sys.stdin:
                command = json.loads(line); op = command['op']
                if op == 'stop': break
                if op == 'submit': value = client.request_finite_stop(scope, key='browser_original_stop')
                elif op == 'report': value = client.get_report(command['request_id'])
                elif op == 'inspect': value = inspect()
                else: raise ValueError('unknown private fixture operation')
                print(json.dumps(value), flush=True)
        finally: server.should_exit = True
    threading.Thread(target=controls, daemon=True).start()
    print(json.dumps({'origin': origin, 'principal': 'fixture_human', 'phrase': shared_app.PHRASE,
                      'projects': [s.project_id for s in services]}), flush=True)
    try: server.run(sockets=[sock])
    finally: fixture.close(); patch.undo(); sock.close()


if __name__ == '__main__': main()
