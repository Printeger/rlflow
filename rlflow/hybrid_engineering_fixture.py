"""Fixed model-free read-only patch proposer; NEVER writes the candidate.

Its sole candidate input is an inherited readonly original FD. The trusted
core must separately authorize/apply/verify output after STOP and Pool FREE.
"""
import ctypes
import hashlib
import json
import os
import resource
import select
import signal
import sys
import time

PROFILE='FIXED_CPU_ADD_PATCH_V1'
BEFORE=b'def add(a, b):\n    return a - b\n'
AFTER=b'def add(a, b):\n    return a + b\n'
CASES=((2,3),(-4,2),(0,0))


def run(parent,nonce,candidate_fd):
    if (parent<=0 or os.getppid()!=parent or len(nonce)!=32 or
            any(c not in '0123456789abcdef' for c in nonce) or candidate_fd<=2):
        raise SystemExit(126)
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=parent:raise SystemExit(126)
    resource.setrlimit(resource.RLIMIT_CPU,(2,2))
    resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))
    gate_began=time.monotonic_ns()
    readable=bool(select.select([0],[],[],3)[0])
    released=readable and os.read(0,1)==b'G'
    if not released:
        os.write(2,(json.dumps({'diagnostic':'engineering.G.rejected','readable':readable,
            'gate_began_ns':gate_began,'gate_end_ns':time.monotonic_ns()},sort_keys=True)+'\n').encode())
        raise SystemExit(126)
    def emit(value):
        remaining=json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\n'
        while remaining:
            written=os.write(1,remaining)
            if written<=0:raise SystemExit(126)
            remaining=remaining[written:]
    emit({'type':'runtime.started','nonce':nonce,'pid':os.getpid(),'program':PROFILE})
    cpu,wall=time.process_time_ns(),time.monotonic_ns()
    source=os.pread(candidate_fd,len(BEFORE)+1,0)
    if source!=BEFORE:raise SystemExit(125)
    # Only these exact fixed literals enter Python, never caller code.
    baseline={};repaired={};exec(BEFORE,baseline);exec(AFTER,repaired)
    rows=[]
    for left,right in CASES:
        rows.append({'left':left,'right':right,'expected':left+right,
                     'before':baseline['add'](left,right),'after':repaired['add'](left,right)})
    emit({'type':'engineering.patch','target':'module/source.py',
          'before_sha256':'sha256:'+hashlib.sha256(source).hexdigest(),
          'after_sha256':'sha256:'+hashlib.sha256(AFTER).hexdigest(),
          'replacement':AFTER.decode(),'tests':rows,
          'cpu_ns':time.process_time_ns()-cpu,'wall_ns':time.monotonic_ns()-wall})
    emit({'type':'fixture.end'});os.fsync(1)


if __name__=='__main__':
    if len(sys.argv)!=5 or sys.argv[3]!='engineering_patch':raise SystemExit(126)
    run(int(sys.argv[1]),sys.argv[2],int(sys.argv[4]))
