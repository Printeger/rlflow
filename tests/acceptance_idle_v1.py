"""Finite actual-daemon idle probe on a strict fixture backup; NOT full B1."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from rlflow.store import Store, initial
from rlflow.observation import ObservationReader, rotate_epoch
from rlflow.jobs import identity, owns
from rlflow.policy import stopped
from tests.acceptance_tasks_v1 import task


def fingerprint(path):
    def digest(p):
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    wal=Path(str(path)+'-wal');size=wal.stat().st_size if wal.exists() else 0
    # A new empty SQLite auxiliary WAL is not a history change.
    return {'db':digest(path),'wal':digest(wal) if size else None,'wal_bytes':size}


def prepare(source,output,*,tasks=10000,min_events=100000):
    if sys.flags.optimize:raise RuntimeError('optimized Python is unsupported for acceptance probes')
    if type(tasks) is not int or not 1<=tasks<=10000 or type(min_events) is not int or min_events<1:raise ValueError('invalid fixture profile')
    source=Path(source).resolve(strict=True);before=fingerprint(source)
    output=Path(output);output.mkdir(parents=True,exist_ok=False,mode=0o700)
    state=output/'state';(state/'runtime').mkdir(parents=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        mode=db.execute('SELECT data_mode FROM observation_meta WHERE singleton=1').fetchone()
        version=db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
        count=db.execute('SELECT count(*) FROM events').fetchone()[0]
        if mode!=('fixture',) or count!=version or count<min_events:raise ValueError('source must be a coherent fixture history')
        markers={**initial(),'usage':{}};seen=[];seen_markers=set()
        for section,key,raw in db.execute('SELECT section,object_key,value FROM projection'):
            value=json.loads(raw)
            if not key:
                seen_markers.add(section)
                expected=markers.get(section)
                if section not in markers or section=='version' or type(value) is not type(expected) or value!=expected:
                    raise ValueError('source marker is not the safe initial fixture')
            else:
                if (section,key)!=('usage','fixed') or value!={'input_tokens':version}:raise ValueError('source contains forbidden objects')
                seen.append((section,key))
        if seen!=[('usage','fixed')]:raise ValueError('source lacks unique fixture usage')
        if seen_markers!=set(markers)-{'version'}:raise ValueError('source markers are incomplete')
        with sqlite3.connect(state/'runtime/research.db') as target:db.backup(target)
    if fingerprint(source)!=before:raise RuntimeError('source changed during backup')
    store=Store(state);rotate_epoch(store)
    keys=[f'task_{i:05d}' for i in range(tasks)]
    store.transact_objects('TASK_PROBE_BOOTSTRAP','idle-bootstrap',[('tasks',k) for k in keys],
        lambda s:s['tasks'].update({k:task(k) for k in keys}))
    records=store.objects('tasks')
    if len(records)!=tasks or any(value['status']!='DONE' or value['completion']!=task(key)['completion'] for key,value in records):
        raise RuntimeError('clone does not contain only inactive fixture tasks')
    return store,{'source':str(source),'source_fingerprint':before,'source_events':count,
                  'tasks':tasks,'core_version':store.version(),'cursor':ObservationReader(state).head()['cursor']}


WRAPPER=r'''
import ctypes,json,os,signal,sys
from pathlib import Path
def witness(pid):
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    if fields[0]=='Z':raise RuntimeError('dead parent')
    return {'pid':pid,'pgid':int(fields[2]),'starttime':fields[19],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
parent=json.loads(sys.argv[2])
if os.getppid()!=parent['pid'] or witness(parent['pid'])!=parent:raise RuntimeError('parent identity mismatch')
signal.signal(signal.SIGTERM,signal.SIG_DFL)
libc=ctypes.CDLL(None,use_errno=True);libc.prctl.argtypes=[ctypes.c_int]+[ctypes.c_ulong]*4
if libc.prctl(1,signal.SIGTERM,0,0,0)!=0:raise OSError(ctypes.get_errno(),'PDEATHSIG failed')
if os.getppid()!=parent['pid'] or witness(parent['pid'])!=parent:raise RuntimeError('parent died during setup')
if sys.flags.optimize:raise RuntimeError('optimized child is unsupported')
os.write(int(sys.argv[3]),(json.dumps(witness(os.getpid()))+'\n').encode());os.close(int(sys.argv[3]))
from rlflow.engine import daemon
daemon(sys.argv[1])
'''


def launch(state,log):
    if threading.current_thread() is not threading.main_thread():raise RuntimeError('launch requires stable main thread')
    read,write=os.pipe();child=None
    try:
        with Path(log).open('xb') as stream:
            child=subprocess.Popen([sys.executable,'-u','-c',WRAPPER,str(state),json.dumps(identity(os.getpid())),str(write)],
                stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,pass_fds=(write,),start_new_session=True)
        os.close(write);write=None
        if not select.select([read],[],[],10)[0]:raise RuntimeError('daemon readiness timeout')
        record=json.loads(os.read(read,4096))
        if record['pid']!=child.pid or not owns(record):raise RuntimeError('daemon readiness identity mismatch')
        return child,record
    except BaseException:
        if child is not None:finish(child)
        raise
    finally:
        os.close(read)
        if write is not None:os.close(write)


def finish(child):
    if child.poll() is None:
        child.terminate()
        try:child.wait(5)
        except subprocess.TimeoutExpired:child.kill();child.wait(5)
    return child.returncode


def metrics(child,record):
    if child.poll() is not None or not owns(record):raise RuntimeError('daemon exited or identity changed')
    fields=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()
    if fields[19]!=record['starttime'] or fields[0]=='Z':raise RuntimeError('daemon metric identity changed')
    rss=int(Path(f'/proc/{child.pid}/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    return {'time':time.monotonic(),'cpu_seconds':(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK'),'rss_bytes':rss}


def measure(source,output,*,tasks=10000,min_events=100000,seconds=300,warmup=5):
    if type(seconds) not in (int,float) or not 0<seconds<=3600 or type(warmup) not in (int,float) or not 0<=warmup<=60:raise ValueError('invalid idle duration')
    store,manifest=prepare(source,output,tasks=tasks,min_events=min_events)
    if stopped(store.root):raise RuntimeError('STOP gate is engaged; cannot claim normal idle')
    log=Path(output)/'daemon.log';child,record=launch(store.root,log);rows=[]
    try:
        print(json.dumps({'manifest':manifest,'daemon_identity':record,'seconds':seconds,'warmup':warmup,'optimize':sys.flags.optimize}),flush=True)
        def checked():
            if stopped(store.root) or log.stat().st_size:raise RuntimeError('STOP or daemon diagnostic observed')
            return metrics(child,record)
        # Wrapper handshake proves the death guard, not entry into daemon().
        # New fixture has no old runtime files; require actual controller witness.
        ready=store.root/'runtime/daemon-code.json';deadline=time.monotonic()+10
        while not ready.exists():
            checked()
            if time.monotonic()>=deadline:raise RuntimeError('actual daemon initialization timeout')
            time.sleep(.05)
        if json.loads(ready.read_text())['identity']!=record:raise RuntimeError('actual daemon witness mismatch')
        start=time.monotonic()
        while time.monotonic()-start<warmup:
            checked();time.sleep(min(.1,warmup))
        first=checked();last_progress=first['time'];deadline=first['time']+seconds
        while True:
            row=checked();rows.append(row)
            if row['time']>=deadline:break
            if row['time']-last_progress>=30:
                print(json.dumps({'progress_seconds':row['time']-first['time']}),flush=True);last_progress=row['time']
            time.sleep(min(1,max(.001,deadline-time.monotonic())))
        last=rows[-1]
    finally:exit_code=finish(child)
    if log.stat().st_size:raise RuntimeError('daemon emitted an exception or source-change diagnostic')
    if stopped(store.root) or owns(record):raise RuntimeError('STOP changed or daemon remains alive')
    reader=ObservationReader(store.root)
    if store.version()!=manifest['core_version'] or reader.head()['cursor']!=manifest['cursor']:raise RuntimeError('idle advanced business state')
    with store.connect() as db:
        session_count=db.execute("SELECT count(*) FROM projection WHERE section='sessions' AND object_key!=''").fetchone()[0]
        task_count=db.execute("SELECT count(*) FROM projection WHERE section='tasks' AND object_key!=''").fetchone()[0]
    if session_count or task_count!=tasks or fingerprint(Path(source).resolve())!=manifest['source_fingerprint']:raise RuntimeError('fixture/source invariants changed')
    elapsed=last['time']-first['time'];percent=100*(last['cpu_seconds']-first['cpu_seconds'])/elapsed
    result={'elapsed_seconds':elapsed,'single_core_cpu_percent':percent,'cpu_target_met':percent<1,
            'five_minute_interval':elapsed>=300,'sampled_peak_rss_bytes':max(r['rss_bytes'] for r in rows),
            'sessions':session_count,'tasks':task_count,'exit_code':exit_code,'sample_rows':rows,
            'source_unchanged':True,'business_unchanged':True,'full_B1_pass':False,
            'stop_observation':'not observed at start/end and each sample; sub-sample transients not excluded',
            'scope':'actual daemon only; no API/active work/hardware limits; archived fixture'}
    print(json.dumps({'summary':result}),flush=True);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('output')
    parser.add_argument('--tasks',type=int,default=10000);parser.add_argument('--min-events',type=int,default=100000)
    parser.add_argument('--seconds',type=float,default=300);parser.add_argument('--warmup',type=float,default=5)
    args=parser.parse_args();measure(args.source,args.output,tasks=args.tasks,min_events=args.min_events,seconds=args.seconds,warmup=args.warmup)
