"""Private original-cap finite lifecycle shared by approved fixed SDK profiles."""
from contextlib import contextmanager
import os
import threading
import time

from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_protocol import ID, validate_schema
from .store import Conflict, sha

_UNSET = object()


class _FiniteExecutionOperation:
    def _bind(self, runtime, lease, output, grant_field):
        if type(runtime) is not FixtureRuntimeOwner:
            raise TypeError('actual original Runtime required')
        # Complete PID/owner check precedes inherited locks, including fork.
        attempt = runtime._issued(lease); output._actual()
        with runtime.pool._lock, runtime._lock:
            if (output.runtime is not runtime or runtime._control_service is not None or
                    id(lease) in runtime._execution_units or attempt[grant_field] is None or
                    runtime._current(attempt)['fixture_runtime']['phase'] != 'REGISTER_NO_HANDOFF'):
                raise Conflict('one original registered fixed unit; no HTTP rebinding/adoption')
            self.runtime, self.lease, self.output = runtime, lease, output
            self._cancelled = threading.Event()
            self._operation_thread = None
            self._operation_lock = threading.Lock()
            self._request = None
            self._last = None
            self.cleanup_error = None
            runtime._execution_units[id(lease)] = self

    def _actual(self):
        attempt = self.runtime._issued(self.lease)
        if self.runtime._execution_units.get(id(self.lease)) is not self:
            raise PermissionError('actual original execution unit required')
        return attempt

    def _check_operation(self):
        self._actual()
        self._check_final()

    def _check_final(self):
        # No file/SQL/clock sampling after the protected last-effect fence.
        self._pure_identity()
        if self._cancelled.is_set(): raise Conflict('original execution unit permanently cancelled')
        if self._operation_thread != threading.get_ident():
            raise PermissionError('actual active original unit operation required')

    def _pure_identity(self):
        if (os.getpid() != self.runtime.process['pid'] or
                not self.runtime._live or self.runtime.budget._fixture_runtime is not self.runtime or
                self.runtime._execution_units.get(id(self.lease)) is not self or
                self.runtime._leases.get(id(self.lease), {}).get('lease') is not self.lease):
            raise PermissionError('actual original execution unit required')

    @contextmanager
    def _operation(self):
        self._actual()
        if not self._operation_lock.acquire(blocking=False):
            raise Conflict('original execution unit already running; cancellation does not wait on this lock')
        self._operation_thread = threading.get_ident()
        try: yield
        finally:
            self._operation_thread = None
            self._operation_lock.release()

    def _handoff(self, version):
        self._check_operation()
        if self._request is None or version != self._request['expected_state_version']:
            raise Conflict('execution unit stale initial HANDOFF writer CAS')
        return self._handoff_prefix + sha(self._request)

    def _state(self, status, *, fact=None, cleanup_error=_UNSET):
        return {'status': status, 'lease_id': self.lease.id, 'fact': fact,
                'cancel_requested': self._cancelled.is_set(), 'goal_completed': False,
                'independent_review_status': 'NOT_PERFORMED', 'dispatch_enabled': False,
                'execution_scope': self._execution_scope,
                'cleanup_error': self.cleanup_error if cleanup_error is _UNSET else cleanup_error}

    def _close_local_output(self, attempt):
        # CPU profiles have no engineering input or core write descriptor.
        pass

    def _cleanup(self):
        """Only this lease's STOP/FDs; UNKNOWN never frees an unproved slot."""
        attempt = self._actual()
        local_error = None
        try:
            handoff = attempt['entries'].get('HANDOFF_UNKNOWN')
            if (attempt['producer_identity'] is None and handoff is not None and
                    self.runtime._confirm_entry(attempt, handoff) is not None):
                self.runtime.request_stop(self.lease)
                self.runtime.sources.stop_fixture(attempt['source'])
                raise Conflict('original HANDOFF without producer identity retains UNKNOWN exposure')
            self.runtime.stop_to_terminal(self.lease)
        except Exception as exc: local_error = type(exc).__name__ + ': ' + str(exc)
        with self.runtime.pool._lock, self.output._lock:
            try: self._close_local_output(attempt)
            except Exception as exc: local_error = type(exc).__name__ + ': ' + str(exc)
        self.cleanup_error = local_error
        return {'complete': local_error is None, 'error': local_error}

    def cancel(self):
        self._pure_identity()
        # Latch before any Pool/Store/operation lock or blocking identity IO.
        self._cancelled.set()
        cleanup = self._cleanup()
        return self._state('CANCELLED_SCOPE_STOPPED' if cleanup['complete'] else 'UNKNOWN_CLEANUP_REQUIRED',
                           cleanup_error=cleanup['error'])

    def run(self, token, *, idempotency_key, expected_state_version):
        attempt = self._actual(); self.runtime.controller._issued(token)
        validate_schema(ID, idempotency_key)
        if token is not attempt['token']: raise PermissionError('original unit token required')
        if type(expected_state_version) is not int or expected_state_version < 0:
            raise Conflict('actual initial CAS integer required')
        request = {'idempotency_key': idempotency_key, 'expected_state_version': expected_state_version}
        with self._operation():
            if self._request is not None:
                if self._request != request: raise Conflict('original execution unit request changed')
                return self._resume()
            self._check_operation(); self._request = request
            try:
                self.runtime.start(self.lease)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    self._check_operation(); self.runtime.poll(self.lease, seal=True)
                    source = self.runtime.sources._issued(attempt['source'])
                    if source['status'] == 'SEALED':
                        self._collect(); break
                    if source['status'] in ('UNKNOWN', 'QUARANTINED', 'CLOSED'):
                        raise Conflict('original fixed result UNKNOWN')
                    time.sleep(.01)
                else: raise Conflict('finite execution unit result deadline exceeded')
                self.runtime.stop_to_terminal(self.lease)
                return self._finish(allow_apply=True)
            except BaseException:
                if 'HANDOFF_UNKNOWN' not in attempt['entries']:
                    self._request = None
                else: self._cleanup()
                raise

    def resume(self):
        with self._operation(): return self._resume()
