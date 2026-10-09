"""Finite private routing of original fixed units in one actual shared pool.

No scheduler, grants, HTTP adoption, global owner shutdown or current-state UI.
Thread bounds do not claim a kernel deadline or host-wide process limit.
"""
from concurrent.futures import ThreadPoolExecutor
import os

from .hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from .hybrid_engineering_execution_unit import EngineeringExecutionUnit
from .hybrid_host_pool import HostPoolOwner
from .hybrid_budget_ledger import COUNT
from .hybrid_protocol import ID, validate_schema
from .store import Conflict


class HostExecutionService:
    def __init__(self, pool):
        if type(pool) is not HostPoolOwner:
            raise TypeError('actual original shared pool required')
        pool._actual()
        with pool._lock:
            pool._physical()
            if getattr(pool, '_finite_execution_host', None) is not None:
                raise Conflict('one original finite execution host per pool')
            self.pool = pool
            self._bindings = ()
            pool._finite_execution_host = self
            from .hybrid_disk_admission import _DiskAdmission
            self._disk = _DiskAdmission(self)

    def _pure_identity(self):
        if (os.getpid() != self.pool.process['pid'] or not self.pool._live or
                getattr(self.pool, '_finite_execution_host', None) is not self):
            raise PermissionError('actual original execution host required')

    def _unit(self, lease):
        self._pure_identity()
        unit = next((unit for unit in self._bindings if unit.lease is lease), None)
        if unit is None:
            raise PermissionError('original bound lease required; no ID adoption')
        unit._pure_identity()
        if unit.runtime.pool is not self.pool:
            raise PermissionError('original shared pool binding required')
        return unit

    def bind_unit(self, unit):
        self._pure_identity()
        if type(unit) not in (CpuTrialExecutionUnit, EngineeringExecutionUnit):
            raise TypeError('actual fixed original execution unit required')
        unit._pure_identity()
        if unit.runtime.pool is not self.pool:
            raise PermissionError('original shared pool binding required')
        # Full existing physical/canonical member, claim and lease checks.
        attempt = unit._actual()
        self.pool.check(attempt['claim'])
        with self.pool._lock:
            self._pure_identity(); unit._pure_identity()
            if unit in self._bindings:
                return unit.lease
            if len(self._bindings) >= 32:
                raise Conflict('finite host binding capacity reached')
            self._disk.bind(unit, attempt)
            self._bindings = (*self._bindings, unit)
        return unit.lease

    def _preflight(self, lease, token, body):
        unit = self._unit(lease)
        attempt = unit._actual()
        unit.runtime.controller._issued(token)
        if token is not attempt['token']:
            raise PermissionError('original unit controller token required')
        if type(body) is not dict:
            raise Conflict('closed original execution body required')
        body = dict(body)
        if set(body) != {'idempotency_key', 'expected_state_version'}:
            raise Conflict('closed original execution body required')
        validate_schema(ID, body['idempotency_key'])
        version = body['expected_state_version']
        if type(version) is not int or version < 0:
            raise Conflict('actual initial CAS integer required')
        validate_schema(COUNT, version)
        return unit, body

    def run(self, lease, token, **body):
        unit, body = self._preflight(lease, token, body)
        return unit.run(token, **body)

    def cancel(self, lease):
        # Pure lookup then Unit's latch, before all owner/Pool/procfs IO.
        return self._unit(lease).cancel()

    def _cancel_units(self, units):
        self._pure_identity()
        rows = []
        # Immutable finite snapshot: every live original latch comes first.
        for unit in units:
            try:
                if self._unit(unit.lease) is not unit:
                    raise PermissionError('original binding changed')
                unit._cancelled.set()
                rows.append((unit, None))
            except Exception as exc:
                rows.append((unit, exc))
        results = []
        for unit, error in rows:
            if error is None:
                try:
                    cleanup = unit._cleanup()
                    result = unit._state('CANCELLED_SCOPE_STOPPED' if cleanup['complete'] else
                                         'UNKNOWN_CLEANUP_REQUIRED', cleanup_error=cleanup['error'])
                except Exception as exc:
                    error = exc
            results.append({'lease_id': unit.lease.id, 'result': result if error is None else None,
                            'error': None if error is None else type(error).__name__ + ': ' + str(error)[:512]})
        return results

    def cancel_all(self):
        self._pure_identity()
        return self._cancel_units(self._bindings)

    def run_many(self, requests):
        self._pure_identity()
        if type(requests) not in (tuple, list):
            raise Conflict('one to three explicit original scope requests required')
        # Capture only a bounded prefix; four means reject, never unbounded
        # copy or iteration over a caller-mutated list after its length check.
        requests = tuple(requests[:4])
        if not 1 <= len(requests) <= 3:
            raise Conflict('one to three explicit original scope requests required')
        prepared = []
        for request in requests:
            if type(request) is not tuple or len(request) != 3:
                raise Conflict('explicit (original lease, original token, body) tuple required')
            lease, token, body = request
            unit, body = self._preflight(lease, token, body)
            if any(unit is prior[0] for prior in prepared):
                raise Conflict('distinct original units required; no duplicate submission')
            prepared.append((unit, token, body))
        def execute(unit, token, body):
            try:
                return {'lease_id': unit.lease.id, 'result': unit.run(token, **body), 'error': None}
            except Exception as exc:
                return {'lease_id': unit.lease.id, 'result': None,
                        'error': type(exc).__name__ + ': ' + str(exc)[:512]}
        # No Host/Pool lock spans submission, effects, cleanup or future wait.
        with ThreadPoolExecutor(max_workers=len(prepared), thread_name_prefix='rlflow_fixed_scope') as executor:
            futures = []
            try:
                for unit, token, body in prepared:
                    self._pure_identity()
                    futures.append(executor.submit(execute, unit, token, body))
                return [future.result() for future in futures]
            except BaseException:
                self._cancel_units(tuple(unit for unit, _, _ in prepared))
                # Context shutdown waits for original futures; never abandons
                # running capabilities or treats executor shutdown as STOP.
                raise
