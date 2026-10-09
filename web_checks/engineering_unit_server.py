"""Private finite original engineering Unit fixture. No model/GPU/production state."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
import uvicorn
from tests.test_execution_adapter import setup as native_setup
from tests.test_hybrid_engineering_output import engineering_runtime
from tests.test_hybrid_engineering_unit_control import setup,PHRASE
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader,install
from rlflow.web_api import Project

def main():
    root=Path(sys.argv[1]).resolve();sock=socket.socket();sock.bind(('127.0.0.1',0))
    origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
    patch=pytest.MonkeyPatch();native=native_setup.__wrapped__(root,patch)
    fixture=engineering_runtime.__wrapped__(root,native,SimpleNamespace(),patch);context=next(fixture)
    owner,execution,service,app,token,headers,path,body=setup(context,origin=origin)
    reader=CandidateOutputReader(owner.store,owner.plans.registry,project_id=service.project_id,
                               store_epoch=service.store_epoch,clock=lambda:context[6][0])
    install(app,{service.project_id:reader},{service.project_id:Project(service.project_id,str(owner.store.root),'fixture')},service.auth)
    spawn=subprocess.Popen;launches=[];writes=[];pwrite=os.pwrite
    def counted(*args,**kwargs):launches.append(args[0]);return spawn(*args,**kwargs)
    patch.setattr(subprocess,'Popen',counted)
    patch.setattr(os,'pwrite',lambda fd,data,offset:(writes.append(True),pwrite(fd,data,offset))[1])
    initial=owner.store.version();attempt=owner._issued(execution.lease)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    def inspect():
        # Original issued Source dictionary was captured before closure below.
        source=source_record
        return {'version':owner.store.version(),'initial_version':initial,'launches':len(launches),
            'writes':len(writes),'occupied':owner.pool.snapshot()['occupied'],'released':attempt['release_entered'],
            'returncode':None if source['producer'] is None else source['producer'].returncode,
            'fds_closed':all(fd is None for fd in source['fds'].values()),
            'status':None if execution._last is None else execution._last['status']}
    source_record=owner.sources._issued(attempt['source'])
    def controls():
        try:
            for line in sys.stdin:
                op=json.loads(line)['op']
                if op=='stop':break
                if op=='close_owner':owner.shutdown()
                elif op!='inspect':raise ValueError('unknown private operation')
                print(json.dumps(inspect()),flush=True)
        finally:server.should_exit=True
    threading.Thread(target=controls,daemon=True).start()
    print(json.dumps({'origin':origin,'principal':'fixture_human','phrase':PHRASE}),flush=True)
    try:server.run(sockets=[sock])
    finally:fixture.close();patch.undo();sock.close()

if __name__=='__main__':main()
