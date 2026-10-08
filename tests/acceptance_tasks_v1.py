"""Archived task cardinality probe; real Store and disabled-work fixture only.

No daemon, live Goal, models or subprocess execution. This is not full B1.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import time
from tests.acceptance_history_v1 import distribution
from rlflow.store import Store
from rlflow.observation import enable, ObservationReader
from rlflow.engine import reconcile, dispatch_one


def task(key):
    return {'id':key,'version':1,'stage_id':'fixture','cycle_id':'fixture',
            'text':'archived synthetic record; not an executed task','repo':'/fixture/not-run',
            'baseline':{'path':'/fixture/not-run','head':'fixture','tree_sha256':'0'*64,'files':{}},
            'status':'DONE','next_role':'PI','repair_rounds':0,'diagnostic_after_rounds':2,
            'results':[],'findings':[],'consulted':[],
            'completion':dict.fromkeys(('implementation','cpu','real_run','behavior','formal'),False)}


def measure(output, *, sizes=(100,1000,10000), samples=30):
    if sys.flags.optimize:raise RuntimeError('optimized Python is unsupported for acceptance probes')
    if (type(samples) is not int or samples<2 or not sizes
            or any(type(v) is not int or v<1 for v in sizes)
            or tuple(sorted(set(sizes)))!=tuple(sizes)):
        raise ValueError('invalid task probe profile')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);rows=[]
    for size in sizes:
        store=Store(output/str(size));enable(store,f'project_tasks_{size}',data_mode='fixture')
        reader=ObservationReader(store.root);keys=[f'task_{i:05d}' for i in range(size)]
        # Same one core bootstrap event per profile; public batching is genuine.
        store.transact_objects('TASK_PROBE_BOOTSTRAP','bootstrap',[('tasks',k) for k in keys],
            lambda s:s['tasks'].update({k:task(k) for k in keys}))
        timings={};cpu={}
        def timed(name,fn):
            elapsed=[];used=[]
            for _ in range(samples):
                start=time.perf_counter_ns();begin=time.process_time_ns();fn()
                used.append((time.process_time_ns()-begin)/1e6)
                elapsed.append((time.perf_counter_ns()-start)/1e6)
            timings[name]=distribution(elapsed);cpu[name]=distribution(used)
        def change(state):
            state['tasks'][keys[0]]['version']+=1
        sequence=[0]
        def write(scoped):
            sequence[0]+=1
            if scoped:store.transact_objects('TASK_PROBE_CHANGE',f'write-{sequence[0]}',[('tasks',keys[0])],change)
            else:store.transact('TASK_PROBE_CHANGE',f'write-{sequence[0]}',change)
        timed('scoped_write',lambda:write(True));timed('legacy_write',lambda:write(False))
        before=store.version();cursor=reader.head()['cursor']
        timed('view_key_discovery',lambda:len(store.view()['tasks']))
        def idle():
            state=reconcile(store);dispatched=dispatch_one(store)
            assert len(state['tasks'])==size and dispatched is None
        timed('isolated_no_work_iteration',idle)
        timed('snapshot_query',lambda:reader.snapshot(limit=30))
        timed('task_page',lambda:reader.page(kind='task',limit=50))
        assert store.version()==before and reader.head()['cursor']==cursor
        with store.connect() as db:
            counts={'core_events':db.execute('SELECT count(*) FROM events').fetchone()[0],
                    'public_events':db.execute('SELECT count(*) FROM observation_events').fetchone()[0],
                    'task_rows':db.execute("SELECT count(*) FROM projection WHERE section='tasks' AND object_key!=''").fetchone()[0],
                    'sessions':db.execute("SELECT count(*) FROM projection WHERE section='sessions' AND object_key!=''").fetchone()[0]}
        assert counts['core_events']==1+2*samples and counts['task_rows']==size and counts['sessions']==0
        assert reader.page(kind='task',limit=50)['total']==size
        assert store.audit()==store.replay()
        row={'tasks':size,'counts':counts,'wall':timings,'cpu':cpu,
             'cumulative_process_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'optimize':sys.flags.optimize,'integrity':'audit==replay; no-work phase leaves core/cursor unchanged'}
        rows.append(row);print(json.dumps({'measurement':row}),flush=True)
    result={'scope':'warm archived-task cardinality; no active work; NOT B1/5-minute idle',
            'measurements':rows,'full_B1_pass':False}
    print(json.dumps({'summary':{'task_sizes':list(sizes),'full_B1_pass':False,'integrity':'all profiles passed'}}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output')
    parser.add_argument('--sizes',nargs='+',type=int,default=[100,1000,10000])
    parser.add_argument('--samples',type=int,default=30);args=parser.parse_args()
    measure(args.output,sizes=tuple(args.sizes),samples=args.samples)
