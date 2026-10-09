"""Finite original-cap SDK execution; no scheduler, cold adoption, or new grant."""
from contextlib import contextmanager
import threading
import time
import os

from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_candidate_output_service import CandidateOutputService
from .hybrid_candidate_output import result_key
from .hybrid_protocol import ID, validate_schema
from .store import Conflict, sha

_UNSET = object()


class EngineeringExecutionUnit:
    def __init__(self, runtime, lease, output):
        if type(runtime) is not FixtureRuntimeOwner or type(output) is not CandidateOutputService:
            raise TypeError('actual original Runtime and candidate service required')
        # PID/owner check precedes inherited locks, including after fork.
        attempt = runtime._issued(lease); output._actual()
        with runtime.pool._lock, runtime._lock:
            if (output.runtime is not runtime or runtime._control_service is not None or
                    id(lease) in runtime._engineering_units or attempt['engineering_grant'] is None or
                    runtime._current(attempt)['fixture_runtime']['phase'] != 'REGISTER_NO_HANDOFF'):
                raise Conflict('one original registered engineering unit; no HTTP rebinding/adoption')
            self.runtime, self.lease, self.output = runtime, lease, output
            self._cancelled = threading.Event()
            self._operation_thread = None
            self._operation_lock = threading.Lock()
            self._request = None
            self._apply_request = None
            self._accept_request = None
            self._last = None
            self.cleanup_error = None
            runtime._engineering_units[id(lease)] = self

    def _actual(self):
        attempt = self.runtime._issued(self.lease)
        if self.runtime._engineering_units.get(id(self.lease)) is not self:
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
                self.runtime._engineering_units.get(id(self.lease)) is not self or
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
        # Original HANDOFF event binds this exact initial body, no second ledger.
        return 'engineering_unit_' + sha(self._request)

    def _state(self, status, *, fact=None, cleanup_error=_UNSET):
        return {'status': status, 'lease_id': self.lease.id, 'fact': fact,
                'cancel_requested': self._cancelled.is_set(), 'goal_completed': False,
                'independent_review_status': 'NOT_PERFORMED', 'dispatch_enabled': False,
                'execution_scope': 'FIXED_ADD_PATCH_ONLY',
                'cleanup_error': self.cleanup_error if cleanup_error is _UNSET else cleanup_error}

    def _cleanup(self):
        """Only this lease's STOP/FDs; UNKNOWN never frees an unproved slot."""
        attempt = self._actual()
        local_error = None
        try:
            handoff = attempt['entries'].get('HANDOFF_UNKNOWN')
            if (attempt['producer_identity'] is None and handoff is not None and
                    self.runtime._confirm_entry(attempt, handoff) is not None):
                # Original ledger does not accept HANDOFF -> no-PID -> FREE,
                # even when private flags say Popen was not yet entered.
                self.runtime.request_stop(self.lease)
                self.runtime.sources.stop_fixture(attempt['source'])
                raise Conflict('original HANDOFF without producer identity retains UNKNOWN exposure')
            self.runtime.stop_to_terminal(self.lease)
        except Exception as exc: local_error = type(exc).__name__ + ': ' + str(exc)
        # stop_to_terminal may be unable to prove an unknown PID. Close only
        # our actual RO input and core RW FD, never another owner's resources.
        with self.runtime.pool._lock, self.output._lock:
            try:
                self.runtime._close_engineering_input(self.runtime._engineering_grants[id(attempt['engineering_grant'])])
                row = self.output._rows.get(id(self.lease))
                if row is not None and row['material'].fd is not None: row['material'].close_fd()
            except Exception as exc:
                local_error = type(exc).__name__ + ': ' + str(exc)
        # One completed diagnostic assignment; concurrent callers cannot
        # reset or replace this call's local success/failure decision.
        self.cleanup_error = local_error
        return {'complete': local_error is None, 'error': local_error}

    def cancel(self):
        self._pure_identity()
        # Latch BEFORE any Pool/Store/operation lock or blocking IO. Final
        # gates observe it; effects already entered cannot be undone.
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
                        self.runtime.collect_engineering_patch(self.lease); break
                    if source['status'] in ('UNKNOWN', 'QUARANTINED', 'CLOSED'):
                        raise Conflict('original engineering result UNKNOWN')
                    time.sleep(.01)
                else: raise Conflict('finite engineering unit result deadline exceeded')
                self.runtime.stop_to_terminal(self.lease)
                return self._finish(allow_apply=True)
            except BaseException:
                # Invalid/stale preacceptance does not poison a later valid
                # request. Any retained HANDOFF attempt (including unknown
                # COMMIT) remains bound, whether or not the receipt arrived.
                if 'HANDOFF_UNKNOWN' not in attempt['entries']:
                    self._request = None
                else: self._cleanup()
                raise

    def _finish(self, *, allow_apply):
        row = self.output._rows.get(id(self.lease))
        if row is not None and row['material'].write_entered:
            # Audit-only original readback, never a second pwrite.
            captured = self.output.reconcile(self.lease)
        elif allow_apply:
            self._check_operation()
            if self._apply_request is None:
                self._apply_request = {'idempotency_key': 'unit_apply_' + sha(self._request),
                                       'expected_state_version': self.runtime.store.version()}
            captured = self.output.apply(self.lease, self.runtime._issued(self.lease)['token'], **self._apply_request)
        else:
            return self._state('UNKNOWN_NO_AUTOMATIC_EFFECT_RETRY')
        if self._cancelled.is_set(): return self._state('OUTPUT_CAPTURED_CANCELLED', fact=captured['fact'])
        if self._accept_request is None:
            self._accept_request = {'output_key': result_key(captured['fact']['request']),
                'idempotency_key': 'unit_accept_' + sha(self._request),
                'expected_state_version': self.runtime.store.version()}
        accepted = self.output.accept_machine(self.lease, **self._accept_request)
        self._last = self._state('MACHINE_ACCEPTED_PENDING_REVIEW', fact=accepted['fact'])
        return self._last

    def _resume(self):
        attempt = self._actual()
        if self._last is not None: return {**self._last, 'cancel_requested': self._cancelled.is_set()}
        if self._request is None: raise Conflict('no original execution unit request to resume')
        if self._cancelled.is_set():
            cleanup = self._cleanup()
            row = self.output._rows.get(id(self.lease))
            if row is not None and row['material'].write_entered: return self._finish(allow_apply=False)
            return self._state('CANCELLED_SCOPE_STOPPED' if cleanup['complete'] else 'UNKNOWN_CLEANUP_REQUIRED',
                               cleanup_error=cleanup['error'])
        # No start/run re-entry, even if HANDOFF flags happen to be false.
        # Closed source cannot be reconstructed into a result capability.
        if id(self.lease) not in self.runtime._engineering_results:
            cleanup = self._cleanup()
            return self._state('UNKNOWN_RESULT_UNAVAILABLE', cleanup_error=cleanup['error'])
        cleanup = self._cleanup()
        if not cleanup['complete']: return self._state('UNKNOWN_CLEANUP_REQUIRED', cleanup_error=cleanup['error'])
        return self._finish(allow_apply=False)

    def resume(self):
        with self._operation(): return self._resume()
