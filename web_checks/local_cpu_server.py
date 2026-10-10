"""Disposable actual local CPU browser fixture; no model/test imports."""
import json
from pathlib import Path
import socket
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_local_cpu_reads import LocalCpuPublicTaskReader
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.web_api import Project,create_app
from rlflow.web_auth import AuthStore,Credential,Principal


def main():
    spec={'purpose':'research','code':"import json,statistics; d=json.loads(open(WORK+'/samples.json').read()); print(json.dumps({'median':statistics.median(d)}))",
        'inputs':{'samples.json':'[8,2,4,7,1]'},'seconds':10,
        'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
        'acceptance':{'method':'JSON_METRICS_RANGE','metrics':{'median':{'min':3.9,'max':4.1}},'stderr_empty':True}}
    with isolated_session(Path(sys.argv[1]),spec,approved=True,confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash']) as session:
        runtime=session['runtime'];project='isolated_local_cpu';reservation=reservation_key(session['reserve'])
        reader=LocalCpuPublicTaskReader(runtime.store,project_id=project,store_epoch=runtime.plans.workspace.store_epoch)
        principal=Principal('dashboard_reader','human',{'operator','viewer'},{project})
        phrase='Synthetic local CPU dashboard fixture phrase'
        auth=AuthStore([Credential.create(principal,phrase)])
        sock=socket.socket();sock.bind(('127.0.0.1',0));origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
        app=create_app([Project(project,str(runtime.store.root),'fixture')],auth,origin=origin,fixture_task_readers={project:reader})
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
        def commands():
            try:
                for line in sys.stdin:
                    op=json.loads(line)['op']
                    if op=='stop':break
                    if op=='run':runtime.run_local_cpu(session['lease'])
                    elif op!='inspect':raise ValueError('unknown browser fixture op')
                    print(json.dumps({'fixture_inspection':True,'view':reader.task(reservation,timeline=True),
                        'occupied':runtime.pool.snapshot()['occupied'],'version':runtime.store.version()}),flush=True)
            finally:server.should_exit=True
        threading.Thread(target=commands,daemon=True).start()
        print(json.dumps({'browser_ready':True,'origin':origin,'principal':principal.id,'phrase':phrase}),flush=True)
        try:server.run(sockets=[sock])
        finally:sock.close()


if __name__=='__main__':main()
