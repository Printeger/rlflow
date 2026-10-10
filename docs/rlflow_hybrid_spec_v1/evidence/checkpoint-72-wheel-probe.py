"""Disposable installed-console proof against original finite fixture."""
import json, os, socket, subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0, '/home/mint/rl_dev/rlflow_standalone')
import pytest, uvicorn
from rlflow.web_auth import Principal
from tests.test_execution_adapter import setup as native_setup
from tests import test_hybrid_finite_host_app as shared_app

root=Path('/tmp/rlflow-cp72-final-wheel-4ddJBQ'); scenario=root/'fixture-r2';scenario.mkdir(mode=0o700)
site=root/'site';real_popen=subprocess.Popen;real_run=subprocess.run
patch=pytest.MonkeyPatch();factory=shared_app.create_finite_host_app
patch.setattr(shared_app,'create_finite_host_app',lambda *a,**kw:factory(*a,**kw,agent_requests=True))
native=native_setup.__wrapped__(scenario,patch)
fixture=shared_app.application.__wrapped__(scenario,native,patch)
sock=socket.socket();sock.bind(('127.0.0.1',8765))
server=None;thread=None
try:
    host,units,services,observers,app,human,headers=next(fixture)
    agent,_=services[0].auth.issue_request_token(Principal('installed_stop_agent','agent',{'viewer'},
        {s.project_id for s in services}),ttl=60)
    coord=app.state.finite_host_stop
    scope={'scope_sha256':coord._scope,'items':[{'project_id':p,'data_mode':'fixture','store_epoch':e,
        'task_id':t,'stop_action':a} for p,e,t,a,*_ in coord._signature]}
    target=root/'target-r2';(target/'.rlflow').mkdir(parents=True,mode=0o700)
    (target/'.rlflow/project.yaml').write_text(json.dumps({'schema_version':'1.0',
        'project_id':services[0].project_id,'control_origin':shared_app.ORIGIN}))
    (target/'scope.json').write_text(json.dumps(scope))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
    assert server.started
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONPATH':str(site),
         'RLFLOW_CONTROL_ORIGIN':shared_app.ORIGIN,'RLFLOW_REQUEST_TOKEN':agent}
    outputs=[]
    def console(*args):
        with patch.context() as child_patch:
            child_patch.setattr(subprocess,'Popen',real_popen)
            child_patch.setattr(subprocess,'run',real_run)
            result=subprocess.run([str(site/'bin/rlflow'),'client',*args],cwd=target,
                env=env,capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        assert agent not in result.stdout+result.stderr
        outputs.append(result.stdout)
        return result.stdout
    with patch.context() as child_patch:
        child_patch.setattr(subprocess,'Popen',real_popen)
        child_patch.setattr(subprocess,'run',real_run)
        loaded=subprocess.run([sys.executable,'-c','import rlflow.agent_client;print(rlflow.agent_client.__file__)'],
            cwd=target,env=env,capture_output=True,text=True,timeout=10)
    assert loaded.returncode==0 and str(site) in loaded.stdout
    before=[s.store.version() for s in services]
    saved=json.loads(console('request-finite-stop','--scope',str(target/'scope.json'),'--key','installed_original_stop'))
    assert saved['status']=='AWAITING_HUMAN' and saved['stop_scope']==scope
    assert [s.store.version() for s in services]==before and not any(u._cancelled.is_set() for u in units)
    assert json.loads(console('status','--request',saved['request_id']))==saved
    helper=services[0].store._hybrid_agent_request_service.stop_requests
    batch=helper.prepare(saved['request_id'],request_hash=saved['request_hash'],token=human,
        csrf=headers['X-CSRF-Token'],origin=shared_app.ORIGIN,resume_cleanup=False)
    helper.execute(batch,resume_cleanup=False)
    report=json.loads(console('report','--request',saved['request_id']))
    assert report['status']=='STOPPED_AS_OF_RETURN' and report['result']['command_id']==batch.id
    assert host.pool.snapshot()['occupied']==0 and all(u._cancelled.is_set() for u in units)
    skill=Path(console('skill-path').strip());assert skill.is_file() and str(site) in str(skill)
    assert 'request-finite-stop' in skill.read_text() and 'Pause, arbitrary process-tree STOP' in skill.read_text()
    print(json.dumps({'installed_console':True,'import_outside_checkout':True,'scopes':len(scope['items']),
        'suggestion_Core_writes':0,'report':report['status'],'pool_occupied':0,'packaged_skill':True,
        'worker_started':False,'Goal_completed':False}),flush=True)
finally:
    if server is not None:server.should_exit=True
    if thread is not None:thread.join(10);assert not thread.is_alive()
    fixture.close();patch.undo();sock.close()
