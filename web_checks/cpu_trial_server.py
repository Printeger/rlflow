"""Finite private CPU evidence browser fixture, no model or GPU execution."""
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_cpu_trial_runtime import trial_runtime
from tests.test_hybrid_cpu_assessment_reads import setup


def main():
    root=Path(sys.argv[1]).resolve()
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch=pytest.MonkeyPatch();native=native_setup.__wrapped__(root,patch)
    fixture=trial_runtime.__wrapped__(root,native,SimpleNamespace(),patch)
    context=next(fixture)
    owner,lease,service,reader,app,auth,_,_,key=setup(context,actual=True,origin=origin)
    initial=owner.store.version()
    attempt=owner._issued(lease)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    def inspect():
        return {'version':owner.store.version(),'occupied':owner.pool.snapshot()['occupied'],
                'spawn_entered':attempt['spawn_entered'],'initial_version':initial}
    def controls():
        try:
            for line in sys.stdin:
                op=json.loads(line)['op']
                if op=='stop':break
                if op=='append_assessment':
                    service.assess(lease,context[2],idempotency_key='second_browser',expected_state_version=owner.store.version())
                elif op=='close_owner':owner.shutdown()
                elif op!='inspect':raise ValueError('unknown private fixture operation')
                print(json.dumps(inspect()),flush=True)
        finally:server.should_exit=True
    threading.Thread(target=controls,daemon=True).start()
    print(json.dumps({'origin':origin,'principal':'viewer','phrase':'Isolated synthetic original CPU evidence viewer passphrase','key':key}),flush=True)
    try:server.run(sockets=[sock])
    finally:fixture.close();patch.undo();sock.close()


if __name__=='__main__':main()
