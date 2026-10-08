import json
import subprocess
import sys
import time
import pytest
from rlflow.store import Store
from rlflow.observation import enable
from rlflow.jobs import owns
from tests.acceptance_idle_v1 import prepare, measure


@pytest.fixture
def source(tmp_path):
    store=Store(tmp_path/'source');enable(store,'project_idle_test',data_mode='fixture')
    for i in range(1,5):
        store.transact_objects('USAGE_OBSERVED',str(i),[('usage','fixed')],lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':i}))
    return store


def test_strict_backup_and_finite_actual_daemon(source,tmp_path):
    result=measure(source.db,tmp_path/'probe',tasks=2,min_events=4,seconds=.2,warmup=.1)
    assert result['source_unchanged'] and result['business_unchanged'] and result['sessions']==0
    assert result['five_minute_interval'] is False and result['full_B1_pass'] is False
    last=result['sample_rows'][-1];first=result['baseline']
    assert result['elapsed_seconds']==last['time']-first['time']
    assert result['single_core_cpu_percent']==100*(last['cpu_seconds']-first['cpu_seconds'])/(last['time']-first['time'])


def test_fixture_label_cannot_authorize_arbitrary_source(source,tmp_path):
    source.transact_objects('UNSAFE','extra',[('historical','unexpected')],lambda s:s['historical'].update(unexpected=1))
    with pytest.raises(ValueError):prepare(source.db,tmp_path/'rejected',tasks=2,min_events=4)


def test_failed_initial_output_cleans_child_while_parent_survives(source,tmp_path,monkeypatch):
    from tests import acceptance_idle_v1 as probe
    launched=[];original=probe.launch
    def capture(*args):
        result=original(*args);launched.append(result);return result
    def failed(*args,**kwargs):raise BrokenPipeError('injected closed output')
    with monkeypatch.context() as patch:
        patch.setattr(probe,'launch',capture);patch.setattr('builtins.print',failed)
        with pytest.raises(BrokenPipeError):probe.measure(source.db,tmp_path/'broken-output',tasks=2,min_events=4,seconds=.1,warmup=0)
    child,record=launched[0]
    assert child.poll() is not None and not owns(record)


def test_parent_abrupt_exit_does_not_leave_daemon(source,tmp_path):
    output=tmp_path/'parentdeath'
    program="from tests.acceptance_idle_v1 import prepare,launch;import json,os,sys;store,_=prepare(sys.argv[1],sys.argv[2],tasks=2,min_events=4);child,record=launch(store.root,store.root.parent/'daemon.log');print(json.dumps(record),flush=True);os._exit(91)"
    result=subprocess.run([sys.executable,'-u','-c',program,str(source.db),str(output)],capture_output=True,text=True,timeout=15)
    assert result.returncode==91,result.stderr
    record=json.loads(result.stdout);deadline=time.monotonic()+5
    while owns(record) and time.monotonic()<deadline:time.sleep(.05)
    assert not owns(record)


@pytest.mark.parametrize('boundary',['ready','before_prctl'])
def test_parent_sigkill_at_setup_boundaries_leaves_no_running_daemon(source,tmp_path,boundary):
    import select
    output=tmp_path/boundary
    program=r'''
import json,sys,time
from tests import acceptance_idle_v1 as probe
if sys.argv[3]=='before_prctl':
    pause="""gate=Path(sys.argv[1]).parent/'early-ready.json';temporary=gate.with_suffix('.tmp')
temporary.write_text(json.dumps(witness(os.getpid())));os.replace(temporary,gate)
clock=__import__('time');deadline=clock.monotonic()+10
while os.getppid()==parent['pid']:
    if clock.monotonic()>=deadline:raise RuntimeError('test gate expired')
    clock.sleep(.01)
"""
    probe.WRAPPER=probe.WRAPPER.replace("if libc.prctl",pause+"if libc.prctl")
store,_=probe.prepare(sys.argv[1],sys.argv[2],tasks=2,min_events=4)
child,record=probe.launch(store.root,store.root.parent/'daemon.log')
print(json.dumps(record),flush=True);time.sleep(30)
'''
    parent=subprocess.Popen([sys.executable,'-u','-c',program,str(source.db),str(output),boundary],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    record=None
    try:
        if boundary=='ready':
            assert select.select([parent.stdout],[],[],10)[0],'parent readiness timed out'
            record=json.loads(parent.stdout.readline())
        else:
            marker=output/'early-ready.json';deadline=time.monotonic()+10
            while not marker.exists() and time.monotonic()<deadline and parent.poll() is None:time.sleep(.02)
            assert marker.exists(),'pre-prctl witness missing'
            record=json.loads(marker.read_text())
        assert owns(record),'child exited before SIGKILL boundary'
        parent.kill();parent.wait(5)
        deadline=time.monotonic()+5
        while owns(record) and time.monotonic()<deadline:time.sleep(.05)
        assert not owns(record)
        if boundary=='before_prctl':assert 'parent died during setup' in (output/'daemon.log').read_text()
    finally:
        if parent.poll() is None:parent.kill();parent.wait(5)
        parent.stdout.close();parent.stderr.close()
