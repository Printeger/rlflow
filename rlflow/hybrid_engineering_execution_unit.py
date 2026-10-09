"""Finite original-cap engineering SDK; no scheduler, cold adoption or new grant."""
from .hybrid_candidate_output_service import CandidateOutputService
from .hybrid_candidate_output import result_key
from .hybrid_finite_execution_operation import _FiniteExecutionOperation
from .store import Conflict, sha


class EngineeringExecutionUnit(_FiniteExecutionOperation):
    _execution_scope = 'FIXED_ADD_PATCH_ONLY'
    _handoff_prefix = 'engineering_unit_'

    def __init__(self, runtime, lease, output):
        if type(output) is not CandidateOutputService:
            raise TypeError('actual original candidate service required')
        self._apply_request = None
        self._accept_request = None
        self._bind(runtime, lease, output, 'engineering_grant')

    def _collect(self):
        return self.runtime.collect_engineering_patch(self.lease)

    def _close_local_output(self, attempt):
        self.runtime._close_engineering_input(self.runtime._engineering_grants[id(attempt['engineering_grant'])])
        row = self.output._rows.get(id(self.lease))
        if row is not None and row['material'].fd is not None: row['material'].close_fd()

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
