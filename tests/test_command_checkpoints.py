from pathlib import Path
import pytest
from rlflow import isolation


def config(tmp_path):
    for d in ('repo','scratch','control'):(tmp_path/d).mkdir()
    return {'candidate':str(tmp_path/'repo'),'scratch':str(tmp_path/'scratch'),
            'role':'Engineer','audit':str(tmp_path/'control/audit.jsonl'),'command_seconds':1800}


def test_command_checkpoint_returns_completed_work_without_reexecution(tmp_path):
    c=config(tmp_path);target=tmp_path/'repo/count'
    args={'command_id':'once','command':f"echo x >> {target}", 'timeout':5}
    result=isolation.persistent_cpu_exec(c,args)
    assert result['exit_code']==0
    assert isolation.persistent_cpu_exec(c,args)==result
    assert target.read_text()=='x\n'
    directory=Path(result['checkpoint'])
    assert (directory/'identity.json').exists() and (directory/'stdout.log').exists()
    with pytest.raises(isolation.IsolationError):isolation.persistent_cpu_exec(c,{**args,'command':'true'})


def test_unknown_command_retains_intent_and_cannot_restart(tmp_path,monkeypatch):
    c=config(tmp_path);calls=[]
    def crash(*a,**kw):calls.append(1);raise OSError('crash after durable intent')
    monkeypatch.setattr(isolation,'cpu_exec',crash)
    args={'command_id':'unknown','command':'true'}
    with pytest.raises(OSError):isolation.persistent_cpu_exec(c,args)
    with pytest.raises(isolation.IsolationError,match='outcome unknown'):isolation.persistent_cpu_exec(c,args)
    assert len(calls)==1


def test_long_limit_is_explicit_and_legacy_limit_unchanged(tmp_path):
    c=config(tmp_path)
    with pytest.raises(isolation.IsolationError):isolation.cpu_exec('true',c['candidate'],c['scratch'],'PI',timeout=121)
    value=isolation.cpu_exec('sleep 0.1',c['candidate'],c['scratch'],'PI',timeout=1800,command_seconds=1800)
    assert value['exit_code']==0 and value['wall_seconds']>=.1


def test_actual_command_supervisor_sigkill_cleans_nested_child(tmp_path):
    import json,os,signal,subprocess,sys,time
    from rlflow.jobs import owns
    c=config(tmp_path);target=tmp_path/'repo/starts';guard=tmp_path/'control/process'
    cfg={'read':[c['candidate'],c['scratch']],'write':[c['candidate'],c['scratch']],
         'execute':[],'memory_bytes':2*1024**3,'command':f'echo x >> {target}; sleep 30',
         'timeout':20,'guard_directory':str(guard)}
    p=subprocess.Popen([sys.executable,'-I',str(Path(isolation.__file__).resolve()),'_supervised',json.dumps(cfg)],start_new_session=True)
    deadline=time.monotonic()+8
    while not target.exists() and time.monotonic()<deadline:time.sleep(.02)
    assert target.exists()
    child=json.loads((guard/'command-child-identity.json').read_text());assert owns(child)
    os.kill(p.pid,signal.SIGKILL);p.wait(timeout=3)
    while owns(child) and time.monotonic()<deadline:time.sleep(.02)
    assert not owns(child) and target.read_text()=='x\n'


def test_actual_command_caller_restart_reuses_completed_result(tmp_path):
    import json,subprocess,sys
    c=config(tmp_path);target=tmp_path/'repo/starts'
    args={'command_id':'survives-caller','command':f'echo x >> {target}','timeout':5}
    program='import json,sys;from rlflow.isolation import persistent_cpu_exec;print(json.dumps(persistent_cpu_exec(json.loads(sys.argv[1]),json.loads(sys.argv[2]))))'
    argv=[sys.executable,'-c',program,json.dumps(c),json.dumps(args)]
    first=subprocess.run(argv,capture_output=True,text=True,check=True)
    second=subprocess.run(argv,capture_output=True,text=True,check=True)
    assert json.loads(first.stdout)==json.loads(second.stdout) and target.read_text()=='x\n'


def test_file_write_root_is_usable_without_directory_or_sibling_rights(tmp_path):
    c=config(tmp_path);repo=Path(c['candidate']);allowed=repo/'README.md';protected=repo/'CONTRACT.md'
    allowed.write_text('old');protected.write_text('protected');c['write_roots']=[str(allowed)]
    result=isolation.persistent_cpu_exec(c,{'command_id':'file-root','command':f"printf new > {allowed}; cat {protected}",'timeout':5})
    assert result['exit_code']==0 and allowed.read_text()=='new' and protected.read_text()=='protected'
    for i,command in enumerate([f'printf bad > {protected}',f'touch {repo}/other',f'rm {allowed}']):
        denied=isolation.persistent_cpu_exec(c,{'command_id':'deny-'+str(i),'command':command,'timeout':5})
        assert denied['exit_code']!=0
    assert allowed.read_text()=='new' and protected.read_text()=='protected'


def test_command_stderr_cannot_spoof_setup_failure(tmp_path):
    c=config(tmp_path)
    value=isolation.persistent_cpu_exec(c,{'command_id':'spoof','command':"printf 'IsolationError: landlock add Invalid argument' >&2; exit 1",'timeout':5})
    assert value['infrastructure_error'] is None
