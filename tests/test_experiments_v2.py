import copy
import sys
import time
from pathlib import Path
import pytest
from rlflow import experiments as ex,policy
from rlflow.store import Conflict,sha
from test_engine import harness


def spec(h):
    if not ex.DISPATCHER.is_file():
        pytest.skip("External reviewed dispatcher excluded from standalone distribution")
    script=h.repo/'probe.py';script.write_text("from pathlib import Path\np=Path('starts.txt')\np.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nprint('runner CPU observation')\n")
    pin=ex.file_pin(script)
    return {'id':'cpu-adapter','stage_id':'CPU','backend':'runner_cpu',
            'argv':['/usr/bin/python3.12','-c',f'import runpy; runpy.run_path({str(script)!r},run_name="__main__")'],'cwd':str(h.repo),
            'pins':{'dispatcher':ex.file_pin(ex.DISPATCHER),'executable':ex.file_pin('/usr/bin/python3.12'),
                    'product':pin,'workload':pin,'runtime':pin,'authorization':pin},
            'method':'fixed-cpu','evaluation':'exit-and-raw-observation','runtime':'cpu-only','seed':1,
            'resources':{'starts':1,'wall_seconds':5,'gpu_seconds':0,'transitions':0},
            'conditions':[{'evidence_id':'condition','sha256':'1'*64}],'observations':['stdout','exit_code']}


def approve(h,value):
    h.store.transact('FIXTURE_CONDITION','condition',lambda s:s['evidence'].update(condition={'id':'condition','sha256':'1'*64,'accepted':True}))
    pid=ex.propose(h.store,value);shown=policy.show_proposal(h.store,pid)
    policy.decide(h.store,pid,shown['sha256'],'APPROVED','isolated CPU only')
    return 'A-'+shown['sha256'][:16]


def wait(h,jid):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        job=ex.reconcile(h.store,jid)
        if job['status'] in {'SUCCEEDED','FAILED','STOPPED'}:return job
        time.sleep(.03)
    pytest.fail('runner supervisor did not finish')


def test_actual_h1_dispatcher_drives_cpu_substitute_once(harness):
    h=harness;value=spec(h);approve(h,value)
    job=ex.submit(h.store,value);jid=job['id'];finished=wait(h,jid)
    assert finished['status']=='SUCCEEDED',finished
    assert (h.repo/'starts.txt').read_text()=='1'
    assert ex.submit(h.store,value)['id']==jid
    evidence=ex.collect(h.store,jid)
    assert evidence['scientific_validity']=='UNASSESSED'
    assert 'process-identity.json' in evidence['artifacts'] and 'held-child.json' in evidence['artifacts']
    assert finished['used_resources']['starts']==1 and not finished['reserved_resources']
    assert 'runner CPU observation' in (h.store.root/'jobs'/jid/'supervisor.log').read_text()
    assert (h.repo/'starts.txt').read_text()=='1'


@pytest.mark.parametrize('mutation',[
    lambda h,v:v.update(backend='real'),
    lambda h,v:v.update(seed=2),
    lambda h,v:v['resources'].update(gpu_seconds=1),
    lambda h,v:(h.repo/'probe.py').write_text('changed'),
    lambda h,v:h.store.transact('FIXTURE_DRIFT','drift',lambda s:s['evidence']['condition'].update(sha256='2'*64))])
def test_condition_or_spec_drift_never_launches(harness,mutation):
    h=harness;v=spec(h);approve(h,v);mutation(h,v)
    with pytest.raises(Conflict):ex.submit(h.store,v)
    assert not h.store.replay()['jobs'] and not (h.repo/'starts.txt').exists()


def test_revoked_experiment_cannot_launch(harness):
    from rlflow.authorizations import revoke
    h=harness;v=spec(h);aid=approve(h,v);revoke(h.store,aid,'cancel test')
    with pytest.raises(Conflict):ex.submit(h.store,v)
    assert not h.store.replay()['jobs']


def test_missing_launch_identity_is_uncertain_never_resubmitted(harness,monkeypatch):
    h=harness;v=spec(h);approve(h,v)
    original=ex.subprocess.Popen
    def crash(argv,*a,**kw):
        if 'rlflow.experiments' in argv:raise OSError('boundary crash')
        return original(argv,*a,**kw)
    monkeypatch.setattr(ex.subprocess,'Popen',crash)
    with pytest.raises(OSError):ex.submit(h.store,v)
    result=ex.submit(h.store,v)
    assert result['status']=='RECONCILE' and result['reserved_resources']==v['resources']
    assert not (h.repo/'starts.txt').exists()
