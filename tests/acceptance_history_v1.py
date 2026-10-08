"""Real Store/observer history-axis probe, not the full B1 profile.

Run with python -m tests.acceptance_history_v1 OUTPUT_DIRECTORY. OUTPUT must
not exist. No scheduler, model or GPU; history is never fabricated/imported.
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import time

from rlflow.observation import enable, ObservationReader
from rlflow.snapshot_maintenance import maintain
from rlflow.store import Store


def percentile(values, fraction=.95):
    return sorted(values)[math.ceil(len(values)*fraction)-1]


def distribution(values):
    return {'n':len(values),'p50_ms':statistics.median(values),
            'p95_ms':percentile(values),'max_ms':max(values),'samples_ms':values}


def measure(output, *, checkpoints=(10000,100000), samples=200):
    if (type(samples) is not int or samples<2 or not checkpoints
            or any(type(v) is not int or v<=samples for v in checkpoints)
            or tuple(sorted(set(checkpoints)))!=tuple(checkpoints)):
        raise ValueError('invalid probe checkpoints/sample count')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    store=Store(output/'state');enable(store,'project_history_probe',data_mode='fixture')
    reader=ObservationReader(store.root);rows=[];boundaries=[];window=[];holds=[]
    original=store.lock
    @contextlib.contextmanager
    def instrument(name='writer',nonblocking=False):
        with original(name,nonblocking):
            start=time.perf_counter_ns()
            try:yield
            finally:
                if name=='writer':holds.append((time.perf_counter_ns()-start)/1e6)
    store.lock=instrument
    manifest={'scope':'fixed projection / real core and public history; NOT full B1',
              'python':platform.python_version(),'cpu_count':os.cpu_count(),
              'machine':platform.machine(),'checkpoints':list(checkpoints),'samples':samples,
              'maintenance':'explicit after measurement window; no daemon',
              'resources':'host unconstrained; no model/GPU/browser/paid resources'}
    print(json.dumps({'manifest':manifest}),flush=True)
    for version in range(1,checkpoints[-1]+1):
        holds.clear();start=time.perf_counter_ns()
        result=store.transact_objects('USAGE_OBSERVED',f'probe-{version}',[('usage','fixed')],
            lambda s:s.setdefault('usage',{}).update(fixed={'input_tokens':version}))
        elapsed=(time.perf_counter_ns()-start)/1e6
        assert result=={'version':version,'duplicate':False} and len(holds)==1
        record={'version':version,'total_ms':elapsed,'writer_hold_ms':holds[0]}
        if version%1000==0:boundaries.append(record)
        window.append(record)
        if len(window)>samples:window.pop(0)
        if version in checkpoints:
            # Boundary samples are reported separately, never silently discarded.
            ordinary=[r for r in window if r['version']%1000]
            snapshot_times=[];page_times=[];event_times=[]
            for _ in range(30):
                start=time.perf_counter_ns();snapshot=reader.snapshot(limit=30)
                snapshot_times.append((time.perf_counter_ns()-start)/1e6)
                start=time.perf_counter_ns();page=reader.page(kind='usage',limit=50)
                page_times.append((time.perf_counter_ns()-start)/1e6)
                cursor=snapshot['cursor'];epoch,seq=cursor.rsplit(':',1)
                start=time.perf_counter_ns();events=reader.events(f'{epoch}:{max(0,int(seq)-100)}',limit=100)
                event_times.append((time.perf_counter_ns()-start)/1e6)
                assert page['total']==1 and len(page['items'])==1 and len(events)<=100
            with store.connect() as db:
                counts={'core_events':db.execute('SELECT count(*) FROM events').fetchone()[0],
                        'public_events':db.execute('SELECT count(*) FROM observation_events').fetchone()[0],
                        'projection_rows':db.execute('SELECT count(*) FROM projection').fetchone()[0],
                        'usage_rows':db.execute("SELECT count(*) FROM projection WHERE section='usage' AND object_key!=''").fetchone()[0]}
                plans=[tuple(r) for r in db.execute("EXPLAIN QUERY PLAN SELECT section,value FROM projection WHERE object_key=''")]
            assert counts['core_events']==version and counts['public_events']>=version and counts['usage_rows']==1
            with store.connect() as db:pending=db.execute('SELECT due_version FROM snapshot_due').fetchone()[0]
            before=reader.head()['cursor'];start=time.perf_counter_ns();completed=maintain(store)
            maintenance_ms=(time.perf_counter_ns()-start)/1e6
            assert completed==bool(pending) and reader.head()['cursor']==before and store.version()==version
            row={'version':version,'counts':counts,'ordinary_write':distribution([r['total_ms'] for r in ordinary]),
                 'ordinary_hold':distribution([r['writer_hold_ms'] for r in ordinary]),
                 'boundary_writes':[r for r in window if not r['version']%1000],
                 'snapshot_query':distribution(snapshot_times),'page_query':distribution(page_times),
                 'event_page_query':distribution(event_times),'maintenance_ms':maintenance_ms,'maintenance_completed':completed,
                 'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'marker_plan':plans}
            rows.append(row);print(json.dumps({'measurement':row}),flush=True)
        elif version%1000==0:print(json.dumps({'progress':version}),flush=True)
    # Retain all events, check recovery with a complete snapshot and full audit.
    assert store.recover()==store.audit()==store.replay()
    ratio=rows[-1]['ordinary_write']['p95_ms']/rows[0]['ordinary_write']['p95_ms']
    assert len({r['counts']['projection_rows'] for r in rows})==1
    summary={'ordinary_write_p95_ratio':ratio,'ratio_target_met':ratio<=2,
             'integrity':'recover==audit==replay','all_boundary_writes':boundaries,
             'full_B1_pass':False}
    print(json.dumps({'summary':summary}),flush=True)
    return {'manifest':manifest,'measurements':rows,'summary':summary}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output');parser.add_argument('--checkpoints',nargs='+',type=int,default=[10000,100000])
    parser.add_argument('--samples',type=int,default=200);args=parser.parse_args()
    result=measure(args.output,checkpoints=tuple(args.checkpoints),samples=args.samples)
    raise SystemExit(0 if result['summary']['ratio_target_met'] else 1)
