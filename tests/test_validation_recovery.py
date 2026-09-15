import json,os,signal,subprocess,sys,time
from pathlib import Path
from rlflow import validation_job
from rlflow.jobs import owns


def wait_for(predicate):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.03)
    raise AssertionError('bounded validation condition not reached')


def test_validation_survives_caller_sigkill_and_never_repeats(tmp_path):
    out=tmp_path/'validation';count=tmp_path/'starts'
    command=[sys.executable,'-c',f'from pathlib import Path;import time;p=Path({str(count)!r});p.write_text("x");time.sleep(.5)']
    args=[str(out),command,str(tmp_path),'fixture-code',str(tmp_path),10]
    program='import json,sys,time;from rlflow.validation_job import poll;poll(*json.loads(sys.argv[1]));print("ready",flush=True);time.sleep(30)'
    caller=subprocess.Popen([sys.executable,'-c',program,json.dumps(args)],stdout=subprocess.PIPE,text=True)
    assert caller.stdout.readline().strip()=='ready'
    os.kill(caller.pid,signal.SIGKILL);caller.wait(timeout=3)
    result=wait_for(lambda:validation_job.poll(*args))
    assert result['exit_code']==0 and count.read_text()=='x'
    assert validation_job.poll(*args)==result


def test_killed_validation_worker_reclaims_child_and_holds_unknown(tmp_path):
    out=tmp_path/'validation';count=tmp_path/'starts'
    command=[sys.executable,'-c',f'from pathlib import Path;import time;Path({str(count)!r}).write_text("x");time.sleep(30)']
    args=[str(out),command,str(tmp_path),'fixture-code',str(tmp_path),20]
    assert validation_job.poll(*args) is None
    wait_for(count.exists);worker=json.loads((out/'identity.json').read_text());child=json.loads((out/'command-child-identity.json').read_text())
    os.kill(worker['pid'],signal.SIGKILL);wait_for(lambda:not owns(child))
    assert validation_job.poll(*args) is None and count.read_text()=='x'
    assert not (out/'result.json').exists()
