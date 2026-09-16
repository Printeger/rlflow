"""Runs only in the disposable delegated user service created by acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from rlflow.resources import membership,prepare_group,enter,stats,verify_group
from rlflow.store import atomic,canonical

root=membership(os.getpid());control=root/'control';control.mkdir()
(control/'cgroup.procs').write_text(str(os.getpid()))
(root/'cgroup.subtree_control').write_text('+cpu +memory +pids')
policy={'mode':'compatible_cpu','memory_max':64*1024**2,'cpu_max':'20000 100000','pids_max':8,'disk_bytes':64*1024**2,'disk_inodes':1000,'cpu_seconds':10}
report={'controller':str(control),'real_model_calls':0,'tests':[],'quota':'NOT_PROVEN'}
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
heartbeat_code="from pathlib import Path;import sys,time;from rlflow.store import Store;s=Store(sys.argv[1]);i=0\nwhile not Path(sys.argv[2]).exists():\n s.transact_objects('HEARTBEAT',str(i),[('historical','heartbeat')],lambda v:v['historical'].update(heartbeat=i));i+=1;time.sleep(.05)"
heartbeat=subprocess.Popen([sys.executable,'-c',heartbeat_code,str(output/'controller-state'),str(output/'heartbeat-stop')])
report['heartbeat_argv']=[sys.executable,'-c',heartbeat_code,str(output/'controller-state'),str(output/'heartbeat-stop')]

for name,script in [
 ('memory',"import subprocess,time; subprocess.Popen(['/usr/bin/python3','-c','x=bytearray(100*1024*1024); import time; time.sleep(2)']); x=bytearray(100*1024*1024); time.sleep(2)"),
 ('pids',"import subprocess,time; children=[]\ntry:\n for i in range(30):children.append(subprocess.Popen(['/usr/bin/sleep','2']))\nexcept OSError as e:print(type(e).__name__,flush=True)\nfor p in children:p.wait()"),
 ('cpu',"import subprocess,time; code='import time; end=time.monotonic()+2\\nwhile time.monotonic()<end:pass'; children=[subprocess.Popen(['/usr/bin/python3','-c',code]) for _ in range(3)]; [p.wait() for p in children]")]:
 record=prepare_group(root,name,policy);group=Path(record['path'])
 started=time.monotonic()
 child=subprocess.Popen(['/usr/bin/python3','-c',script],preexec_fn=lambda:enter(record),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 out,err=child.communicate(timeout=12)
 observed=stats(group)
 report['tests'].append({'name':name,'record':record,'argv':['/usr/bin/python3','-c',script],
                        'exit_code':child.returncode,'stdout':out,'stderr':err,'wall_seconds':time.monotonic()-started,'stats':observed,
                        'controller_alive':membership(os.getpid())==control})
 atomic(output/'report.json',canonical(report))
 (group/'cgroup.kill').write_text('1')
 deadline=time.monotonic()+3
 while 'populated 1' in (group/'cgroup.events').read_text() and time.monotonic()<deadline:time.sleep(.02)
 group.rmdir()
assert report['tests'][0]['stats']['memory.events']['oom_kill']>0
assert report['tests'][1]['stats']['pids.events']['max']>0
assert report['tests'][2]['stats']['cpu.stat']['nr_throttled']>0
atomic(output/'heartbeat-stop',b'stop')
assert heartbeat.wait(timeout=5)==0
from rlflow.store import Store
ticks=Store(output/'controller-state').get('historical','heartbeat')
assert ticks>=2
report['controller_ledger_heartbeats']=ticks;atomic(output/'report.json',canonical(report))
atomic(output/'passed.json',canonical({'cgroup_positive':True,'quota_positive':False,'controller_ledger_heartbeats':ticks}))
