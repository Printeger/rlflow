"""Best-effort loop progress, never model activity or execution authority."""
import math
import os
import time
from pathlib import Path
from .jobs import identity
from .store import atomic_stream, canonical, sha
from .tool_journal import context_valid


def write_heartbeat(path,data):
    atomic_stream(path,[data])  # Remove owned temporary file after failed writes.


class Heartbeat:
    def __init__(self, request, *, clock=time.monotonic, write=write_heartbeat):
        self.clock,self.write,self.last,self.counter = clock,write,None,0
        self.context = None
        self.directory = None
        try:
            self.directory = Path(request['directory'])
            if request.get('recovery_protocol',1)>=2:
                context = dict(schema_version='1.0',session=request.get('id'),generation=request.get('generation'),
                               request_sha256=sha(request),candidate_sha256=sha(request.get('before')))
                if context_valid(context):self.context=context
        except (OSError,ValueError,TypeError,KeyError,RecursionError,OverflowError):pass

    def tick(self):
        # Called by the actual supervisor loop, never a timer/helper thread.
        # Telemetry failure cannot enter worker's kill/receipt exception path.
        try:
            now = self.clock()
            if (self.context is None or not math.isfinite(now) or now<0
                    or self.last is not None and now-self.last<2 or self.counter>=2**63-1):return False
            self.last = now  # Also limit retry writes after a filesystem failure.
            owner = identity(os.getpid())
            if owner is None:return False
            self.counter += 1
            value = dict(schema_version='1.0',kind='WORKER_HEARTBEAT',context=self.context,
                         identity=owner,counter=self.counter,monotonic_seconds=now)
            self.write(self.directory/'worker-heartbeat.json',canonical(value))
            return True
        except (OSError,ValueError,TypeError,RecursionError,OverflowError):return False
