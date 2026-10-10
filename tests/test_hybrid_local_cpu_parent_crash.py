"""Actual isolated owner SIGKILL; physical scope retirement is not FREE."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.store import Store

WORKER=r'''
import json,sys,time
from pathlib import Path
from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_budget_ledger import reservation_key
spec={'purpose':'research','code':'import os,time\np=os.fork()\nif not p:os.setsid()\nwhile True:time.sleep(1)',
    'inputs':{},'seconds':20,'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12}}
with isolated_session(Path(sys.argv[1]),spec,approved=True,confirmation_reader=lambda p,c:'APPROVE '+c['scope_hash']) as s:
    runtime=s['runtime'];lease=s['lease'];runtime.start(lease)
    row=runtime.sources._issued(runtime._issued(lease)['source'])
    print(json.dumps({'crash_ready':True,'unit':row['manager'].unit,'keeper':row['ready']['keeper'],
        'task':row['ready']['task'],'root':str(runtime.store.root),'epoch':runtime.plans.workspace.store_epoch,
        'reservation':reservation_key(s['reserve']),
        'application_root':str(runtime.pool.application_root),
        'descriptor_sha256':runtime.pool.descriptor_sha256,
        'descriptor_identity':runtime.pool.descriptor_identity}),flush=True)
    sys.stdin.readline()
'''


def unit_state(unit):
    result=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState','--property=MainPID','--property=LoadState'],
        capture_output=True,text=True,timeout=3)
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def test_owner_crash_retires_physical_service_without_forging_budget_terminal(tmp_path):
    tmp_path.chmod(0o700)
    worker=subprocess.Popen([sys.executable,'-c',WORKER,str(tmp_path)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},bufsize=0)
    held=[];ready=None;tail=b''
    try:
        end=time.monotonic()+30
        while ready is None:
            assert time.monotonic()<end,'actual worker ready deadline'
            if not select.select([worker.stdout],[],[],.1)[0]:continue
            raw=os.read(worker.stdout.fileno(),32768)
            assert raw,'worker failed before crash injection'
            tail+=raw;assert len(tail)<=65536
            while b'\n' in tail:
                line,tail=tail.split(b'\n',1)
                try:value=json.loads(line)
                except ValueError:continue
                if value.get('crash_ready'):ready=value
        children=Path(f"/proc/{ready['task']['pid']}/task/{ready['task']['pid']}/children")
        end=time.monotonic()+2
        while not children.read_text().strip() and time.monotonic()<end:time.sleep(.01)
        descendants=[int(pid) for pid in children.read_text().split()]
        assert descendants,'actual setsid descendant required for crash proof'
        # Original live kernel handles captured before killing only this
        # disposable worker. No reconstructed product STOP/controller grant.
        for pid in (ready['keeper']['pid'],ready['task']['pid'],*descendants):held.append(os.pidfd_open(pid))
        worker.send_signal(signal.SIGKILL);assert worker.wait(timeout=4)==-signal.SIGKILL
        end=time.monotonic()+7
        while time.monotonic()<end:
            state=unit_state(ready['unit'])
            if state.get('LoadState')=='not-found' and state.get('MainPID')=='0':break
            time.sleep(.05)
        assert state.get('ActiveState') in ('inactive','failed') and state.get('MainPID')=='0',state
        assert state.get('LoadState')=='not-found',state
        assert len(select.select(held,[],[],0)[0])==len(held)
        store=Store.attach_existing(ready['root'],project_id='isolated_local_cpu',data_mode='fixture')
        version=store.version();reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=ready['epoch'])
        history=reader.task(ready['reservation'],timeline=True)
        assert history['task']['recorded_budget_status']=='UNKNOWN'
        assert history['task']['recorded_phase'] in ('RELEASE_INTENT','STARTED_AS_OBSERVED')
        assert history['managed_terminal_proof'] is None and history['recorded_settled_usage'] is None
        assert not history['task']['controls_available'] and not history['task']['condition_evidence']
        assert store.version()==version
        # Protected startup uses the actual before-crash installation pins,
        # not any reconstructed claim/source/manager capability. Only read.
        pool=HostPoolOwner.trusted_attach(ready['application_root'],ready['descriptor_sha256'],ready['descriptor_identity'])
        try:
            before=pool.snapshot();assert before['occupied']==1
            assert not pool._claims and not pool._claim_slots
            assert pool.snapshot()==before and store.version()==version
            (tmp_path/'crash-pool.json').write_text(json.dumps(before))
        finally:pool.shutdown()
        (tmp_path/'crash-history.json').write_text(json.dumps(history))
        (tmp_path/'crash-state.json').write_text(json.dumps(state))
    finally:
        if worker.poll() is None:
            worker.stdin.close();worker.wait(timeout=30)
        # Existing finite service RuntimeMaxSec is the fixture cleanup fallback,
        # never a cold STOP by unit name or a fake business FREE/settlement.
        if ready is not None:
            end=time.monotonic()+28
            while time.monotonic()<end:
                if unit_state(ready['unit']).get('ActiveState') in ('inactive','failed'):break
                time.sleep(.1)
        for fd in held:os.close(fd)
        worker.stdout.close();worker.stderr.close()
        if not worker.stdin.closed:worker.stdin.close()
