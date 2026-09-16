"""Standalone measurement driver; no model/runner/GPU execution."""
import json
from pathlib import Path
import resource
import statistics
import sys
import time
from rlflow.store import Store


def write_bytes():
    return int(next(line.split(':')[1] for line in Path('/proc/self/io').read_text().splitlines() if line.startswith('write_bytes:')))


def measure(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    results=[]
    for growth in (False,True):
        store=Store(root/('objects' if growth else 'history'));timings=[];writes=[]
        for i in range(1,10001):
            key=str(i) if growth else 'fixed'
            before=write_bytes();start=time.perf_counter_ns()
            store.transact_objects('BENCH',str(i),[('historical',key)],lambda s:s['historical'].update({key:i}))
            elapsed=(time.perf_counter_ns()-start)/1e6;written=write_bytes()-before
            timings.append(elapsed);writes.append(written)
            if i in (100,1000,10000):
                samples=timings[-51:-1] if i%1000==0 else timings[-50:]
                byte_samples=writes[-51:-1] if i%1000==0 else writes[-50:]
                snapshot_start=time.perf_counter_ns();store.snapshot();snapshot_ms=(time.perf_counter_ns()-snapshot_start)/1e6
                export_start=time.perf_counter_ns();store.export();export_ms=(time.perf_counter_ns()-export_start)/1e6
                row={'growth':'objects' if growth else 'fixed','events':i,'p50_ms':statistics.median(samples),
                     'p95_ms':sorted(samples)[47],'write_bytes_p95':sorted(byte_samples)[47],
                     'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                     'snapshot_ms':snapshot_ms,'export_ms':export_ms,'samples_ms':samples,'samples_write_bytes':byte_samples,
                     'scheduled_snapshot_transaction_ms':elapsed if i%1000==0 else None}
                results.append(row);(root/'measurements.json').write_text(json.dumps(results,indent=2))
        assert store.audit()==store.replay()
    fixed=[r for r in results if r['growth']=='fixed']
    ratio={'latency_ratio_10000_to_100':fixed[-1]['p95_ms']/fixed[0]['p95_ms'],
           'write_ratio_10000_to_100':fixed[-1]['write_bytes_p95']/fixed[0]['write_bytes_p95']}
    (root/'thresholds.json').write_text(json.dumps(ratio,indent=2))
    print(json.dumps(ratio))
    return 0 if max(ratio.values())<=2 else 1

if __name__=='__main__':raise SystemExit(measure(sys.argv[1]))
