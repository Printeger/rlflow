"""Private two-project original-pool HTTP/Chrome fixture; no paid/GPU state."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests import test_hybrid_finite_host_app as shared_app

def main():
    root=Path(sys.argv[1]).resolve();sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch=pytest.MonkeyPatch();patch.setattr(shared_app,'ORIGIN',origin)
    native=native_setup.__wrapped__(root,patch)
    fixture=shared_app.application.__wrapped__(root,native,patch)
    host,units,services,observers,app,token,headers=next(fixture)
    launches=[];writes=[];spawn=subprocess.Popen;pwrite=os.pwrite
    patch.setattr(subprocess,'Popen',lambda *a,**k:(launches.append(a[0]),spawn(*a,**k))[1])
    patch.setattr(os,'pwrite',lambda fd,data,offset:(writes.append(True),pwrite(fd,data,offset))[1])
    for u,observer in zip(units,observers):
        register=u.runtime._register_release
        def sample(attempt,_register=register,_observer=observer):
            result=_register(attempt);assert _observer.sample();return result
        patch.setattr(u.runtime,'_register_release',sample)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    def inspect():
        return {'launches':len(launches),'writes':len(writes),'occupied':host.pool.snapshot()['occupied'],
            'projects':[{'id':s.project_id,'version':s.store.version(),'cancelled':u._cancelled.is_set(),
                'status':None if u._last is None else u._last['status']} for s,u in zip(services,units)]}
    def controls():
        try:
            for line in sys.stdin:
                op=json.loads(line)['op']
                if op=='stop':break
                if op!='inspect':raise ValueError('unknown private operation')
                print(json.dumps(inspect()),flush=True)
        finally:server.should_exit=True
    threading.Thread(target=controls,daemon=True).start()
    print(json.dumps({'origin':origin,'principal':'fixture_human','phrase':shared_app.PHRASE,
        'projects':[s.project_id for s in services]}),flush=True)
    try:server.run(sockets=[sock])
    finally:fixture.close();patch.undo();sock.close()

if __name__=='__main__':main()
