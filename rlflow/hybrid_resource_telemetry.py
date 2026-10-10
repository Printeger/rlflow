"""Original fixed-unit OS observations, not execution or billing authority.

Sampling is an explicit private SDK action. HTTP/SSE only read the latest
memory slot; no process polling, collection, pool SQL or reconstructed owners.
"""
import copy
import os
import sqlite3
import threading
import time
import uuid

from .hybrid_host_execution import HostExecutionService
from .hybrid_protocol import validate
from .observation import public_id, utc
from . import telemetry_sources as sources
from .store import canonical
from .store import Conflict


class FixedUnitTelemetry:
    def __init__(self, host, lease):
        if type(host) is not HostExecutionService:
            raise TypeError('original finite host required')
        unit = host._unit(lease); unit._actual()
        if getattr(unit, '_fixed_resource_telemetry', None) is not None:
            raise Conflict('one original telemetry observer per fixed unit')
        self.host, self.unit = host, unit
        self.root = unit.runtime.store.root
        self.project_id = unit.runtime.workspace.project_id
        self.store_epoch = unit.runtime.workspace.store_epoch
        self.data_mode = 'fixture'
        self._epoch = 'sampler_' + uuid.uuid4().hex
        self._seq = 0; self._slot = None; self._cpu = None
        self._sample_lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._retirement = 0; self._age_highwater = 0
        self._fault = False
        self._slot_capture = None; self._final_retired = False
        unit._fixed_resource_telemetry = self

    def _original(self):
        self.host._pure_identity(); self.unit._pure_identity()
        if (self.host._unit(self.unit.lease) is not self.unit or
                getattr(self.unit, '_fixed_resource_telemetry', None) is not self or
                (self.root,self.project_id,self.store_epoch,self.data_mode) !=
                (self.unit.runtime.store.root,self.unit.runtime.workspace.project_id,
                 self.unit.runtime.workspace.store_epoch,'fixture')):
            raise PermissionError('original fixed-unit telemetry binding required')

    def sample(self):
        """Finite, non-waiting coordinator acquisition; never drives execution."""
        self._original()
        if not self._sample_lock.acquire(blocking=False): return False
        pool = self.host.pool
        held = False; locks = []
        try:
            held = pool._lock.acquire(blocking=False)
            if not held: return False
            self._original(); pool._physical()
            for lock in (self.unit.runtime._lock,self.unit.runtime.sources._lock):
                if not lock.acquire(blocking=False): return False
                locks.append(lock)
            issued, observed = time.monotonic(), utc()
            attempt = self.unit._actual()
            runtime = self.unit.runtime
            # Version precedes observation: concurrent later domain facts may
            # conservatively invalidate, never upgrade, these process metrics.
            with runtime.store.read_connection() as db:
                db.execute('PRAGMA busy_timeout=0'); db.execute('BEGIN')
                version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
            host, cpu = sources.host(self.root, self._cpu)
            process = dict(scope='FIXED_WORKER_PROCESS', status='UNKNOWN', cpu_seconds=None, rss_bytes=None)
            final_usage = None
            capture = None
            source = attempt.get('source')
            if source is not None and runtime.sources._live:
                row = runtime.sources._issued(source)
                producer = row['producer']
                capture = row.get('kernel_usage')
                if (row['runtime'] is attempt and capture is not None and capture.process is producer
                        and row['producer_identity'] == attempt['producer_identity']
                        and row['producer_identity'] is not None and capture.pid == row['producer_identity']['pid']):
                    final_usage = capture.snapshot()
                if (row['runtime'] is attempt and producer is not None and producer.returncode is None
                        and row['producer_identity'] == attempt['producer_identity']
                        and row['producer_identity'] is not None and producer.pid == row['producer_identity']['pid']):
                    runtime.sources._physical(row)
                    process = {**sources.process(row['producer_identity']), 'scope':'FIXED_WORKER_PROCESS'}
            self._original()
            value = dict(schema_version='1.0', sampler_epoch=self._epoch, sample_seq=8*(self._seq+1),
                sample_id=self._epoch+':'+str(8*(self._seq+1)), observed_at=observed,
                project_id=self.project_id, store_epoch=self.store_epoch, data_mode=self.data_mode,
                source_state_version=version, source='CORE_OS_SAMPLE', observability='PARTIAL', sample_age_seconds=time.monotonic()-issued,
                host=host, gpu=dict(scope='GPU',status='UNKNOWN',utilization_percent=None,memory_used_bytes=None),
                workers=[dict(execution_id=public_id(self.unit.lease.id), process=process,
                    heartbeat=dict(status='UNKNOWN',counter=None,age_seconds=None),final_usage=final_usage)], workers_truncated=False)
            validate('Telemetry', value)
            if len(canonical(value))>65536: return False
            # One immutable publication includes its actual clock and original
            # source row. Read-side invalidation cannot refresh this clock.
            self._seq += 1; self._cpu = cpu
            with self._read_lock:
                self._slot = (value, issued, source)
                self._slot_capture = capture
                self._final_retired = False
                self._retirement = 0; self._age_highwater = value['sample_age_seconds']
                self._fault = False
            return True
        except (OSError, ValueError, PermissionError, Conflict, sqlite3.Error):
            with self._read_lock: self._fault = True
            return False
        finally:
            for lock in reversed(locks): lock.release()
            if held: pool._lock.release()
            self._sample_lock.release()

    def latest(self):
        if (os.getpid()!=self.host.pool.process['pid'] or
                getattr(self.unit, '_fixed_resource_telemetry', None) is not self):
            raise PermissionError('original telemetry reader required')
        # This short lock covers memory only, never any control lock or OS/SQL
        # read. Retirement and age are monotonic per immutable original slot.
        with self._read_lock:
            slot = self._slot
            if slot is None: return None
            value, issued, source = slot
            age = time.monotonic()-issued
            available = False; process_available = False
            final_available = False
            try:
                self._original()
                runtime = self.unit.runtime
                attempt = runtime._leases[id(self.unit.lease)]
                row = runtime.sources._sources.get(id(source))
                final_available = (not self._fault and runtime.sources._live and source is not None
                    and attempt.get('source') is source and row is not None and row['source'] is source
                    and row['runtime'] is attempt and row['producer_identity'] is not None
                    and row['producer_identity'] == attempt['producer_identity']
                    and self._slot_capture is not None and row.get('kernel_usage') is self._slot_capture
                    and self._slot_capture.process is row['producer']
                    and self._slot_capture.creator == os.getpid()
                    and self._slot_capture.pid == row['producer_identity']['pid']
                    and row['producer'].pid == self._slot_capture.pid and self._slot_capture._bound())
                available = (not self._fault and sources.number(age) and self._age_highwater<=age<=15
                    and runtime.sources._live and attempt.get('source') is source and not self.unit._cancelled.is_set())
                if available and source is not None:
                    row = runtime.sources._sources.get(id(source))
                    process_available = (row is not None and row['source'] is source and row['runtime'] is attempt
                        and row['producer'] is not None and row['producer'].returncode is None
                        and row['fds']['read'] is not None and row['producer_identity']==attempt['producer_identity'])
            except PermissionError: pass
            if value['workers'][0]['final_usage'] is not None and not final_available:
                self._final_retired = True
            final_available = final_available and not self._final_retired
            retired_process = value['workers'][0]['process']['status']=='KNOWN' and not process_available
            self._retirement = max(self._retirement, 2 if not available else 1 if retired_process else 0)
            self._age_highwater = max(self._age_highwater,age if sources.number(age) else 16)
            live_retirement = self._retirement
            retirement, age = live_retirement + (4 if self._final_retired else 0), self._age_highwater
        result = copy.deepcopy(value)
        if not final_available:result['workers'][0]['final_usage'] = None
        result['sample_age_seconds'] = age
        if retirement:
            # Deterministic retirement identity, NOT a new OS sample. Preserve
            # observed_at/version/age; SSE may convey this once, not renew it.
            result['sample_seq'] += retirement
            result['sample_id'] = self._epoch+':'+str(result['sample_seq'])
            for metric in ([*result['host'].values()] if live_retirement==2 else [])+[result['workers'][0]['process']]:
                metric['status'] = 'UNKNOWN'
                for key in metric:
                    if key not in ('scope','status'): metric[key] = None
        validate('Telemetry', result)
        return result
