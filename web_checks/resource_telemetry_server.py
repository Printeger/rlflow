"""Private two-project real OS/SSE fixture; finite fixed CPU only."""
import json
from pathlib import Path
import socket
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_host_execution import shared, requests
from rlflow.hybrid_resource_telemetry import FixedUnitTelemetry
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Credential, Principal


def main():
    root=Path(sys.argv[1]).resolve();root.chmod(0o700)
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch=pytest.MonkeyPatch();native=native_setup.__wrapped__(root,patch)
    fixture=shared.__wrapped__(root,native,patch)
    host,units=next(fixture)
    observers=[FixedUnitTelemetry(host,u.lease) for u in units]
    for observer in observers: assert observer.sample()
    principal=Principal('viewer','human',{'viewer'},{o.project_id for o in observers})
    phrase='Isolated synthetic fixed resource telemetry passphrase'
    auth=AuthStore([Credential.create(principal,phrase)])
    app=create_app([Project(o.project_id,str(o.root),'fixture') for o in observers],auth,origin=origin,
        fixed_unit_telemetry={o.project_id:o for o in observers})
    versions=[u.runtime.store.version() for u in units]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    def inspect():
        return {'versions':[u.runtime.store.version() for u in units],'initial_versions':versions,
                'samples':[o.latest() for o in observers]}
    def controls():
        try:
            for line in sys.stdin:
                op=json.loads(line)['op']
                if op=='stop':break
                if op=='sample':assert observers[0].sample()
                elif op=='close_owner':units[0].runtime.shutdown()
                elif op!='inspect':raise ValueError('unknown private fixture operation')
                print(json.dumps(inspect()),flush=True)
        finally:server.should_exit=True
    threading.Thread(target=controls,daemon=True).start()
    print(json.dumps({'origin':origin,'principal':'viewer','phrase':phrase,'projects':[o.project_id for o in observers]}),flush=True)
    try:server.run(sockets=[sock])
    finally:fixture.close();patch.undo();sock.close()


if __name__=='__main__':main()
