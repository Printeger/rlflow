import json
from pathlib import Path
import subprocess
import sys
import tempfile

report=[]
with tempfile.TemporaryDirectory(prefix='rlflow-file-memory-') as temporary:
    for size in (1024**2,2*1024**3):
        path=Path(temporary)/str(size)
        with path.open('xb') as stream:stream.truncate(size)
        code='import json,resource,sys,time;from rlflow.files import stream_digest;t=time.monotonic();digest=stream_digest(sys.argv[1]);print(json.dumps({"sha256":digest,"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"seconds":time.monotonic()-t}))'
        result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,check=True)
        report.append({'bytes':size,**json.loads(result.stdout)})
extra=report[1]['peak_rss_kib']-report[0]['peak_rss_kib']
Path(sys.argv[1]).write_text(json.dumps({'measurements':report,'extra_peak_rss_kib':extra,'limit_kib':16384,'passed':extra<=16384},indent=2))
assert extra<=16384
