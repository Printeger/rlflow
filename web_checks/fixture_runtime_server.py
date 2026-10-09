"""Disposable loopback browser runtime. Actual fixed CPU only, no model CLI."""
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_fixture_runtime import runtime
from tests.test_hybrid_fixture_runtime_control import setup
from rlflow.web_auth import Credential, Principal


def main():
    root = Path(sys.argv[1]).resolve()
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch = pytest.MonkeyPatch()
    native = native_setup.__wrapped__(root, patch)
    fixture = runtime.__wrapped__(root, native, SimpleNamespace(), patch)
    context = next(fixture)
    auth = context[0].store._hybrid_auth_owner
    auth.credentials['fixture_viewer'] = Credential.create(
        Principal('fixture_viewer', 'human', {'viewer'}, {context[0].workspace.project_id}),
        'Working plan isolated synthetic fixture passphrase')
    owner, lease, service, app, _, _, _, _ = setup(context, origin=origin)
    attempt = owner._issued(lease)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, proxy_headers=False))
    original_stop = owner.sources.stop_fixture
    stop_fault = [False]
    def stop_with_fault(source):
        if stop_fault[0]:
            stop_fault[0] = False
            raise OSError('isolated browser fixture cleanup fault after durable STOP')
        return original_stop(source)
    patch.setattr(owner.sources, 'stop_fixture', stop_with_fault)

    def inspect():
        producer = attempt.get('source')
        process = owner.sources._issued(producer)['producer'] if producer is not None and owner.sources._live else None
        return {'version':owner.store.version(), 'phase':service.reader.task(attempt['ready']['source_context']['budget_reservation']['reservation_id'])['task']['recorded_phase'],
                'spawn_entered':attempt['spawn_entered'], 'g_entered':attempt['release_entered'],
                'process_reaped':process is not None and process.returncode is not None,
                'occupied':owner.pool.snapshot()['occupied']}

    def controls():
        try:
            for line in sys.stdin:
                op = json.loads(line)['op']
                if op == 'stop': break
                if op == 'close_owner': owner.shutdown()
                elif op == 'fail_stop_once': stop_fault[0] = True
                elif op != 'inspect': raise ValueError('unknown operation')
                print(json.dumps(inspect()), flush=True)
        finally: server.should_exit = True

    threading.Thread(target=controls, daemon=True).start()
    print(json.dumps({'origin':origin, 'principal':'fixture_human',
                      'phrase':'Working plan isolated synthetic fixture passphrase'}), flush=True)
    try: server.run(sockets=[sock])
    finally:
        fixture.close(); patch.undo(); sock.close()


if __name__ == '__main__': main()
