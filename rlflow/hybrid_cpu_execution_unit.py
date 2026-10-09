"""One original-cap fixed CPU experiment through actual raw machine disposition."""
import json
from .hybrid_cpu_assessment_service import CpuAssessmentService
from .hybrid_cpu_assessment import fact_key
from .hybrid_finite_execution_operation import _FiniteExecutionOperation
from .store import Conflict, sha, canonical


class CpuTrialExecutionUnit(_FiniteExecutionOperation):
    _execution_scope = 'FIXED_CPU_PI_TRIAL_V1'
    _handoff_prefix = 'cpu_trial_unit_'

    def __init__(self, runtime, lease, assessment):
        if type(assessment) is not CpuAssessmentService:
            raise TypeError('actual original CPU appraisal service required')
        self._phase_requests = {}
        self._phase_attempts = {}
        self._phase_facts = {}
        self._bind(runtime, lease, assessment, 'cpu_grant')

    def _collect(self):
        return self.runtime.collect_cpu_trial(self.lease)

    def _capture_assessment(self, value):
        """Called only by actual held appraisal guard before uncertain COMMIT."""
        self._check_final()
        phase = 'decision' if 'prior_assessment_key' in value['request'] else 'assessment'
        request = self._phase_requests.get(phase)
        if request is None or any(value['request'][name] != request[name]
                                  for name in ('idempotency_key', 'expected_state_version')):
            raise PermissionError('actual original CPU unit phase request required')
        raw = canonical(value)
        original = self._phase_attempts.get(phase)
        if original is not None and original != raw:
            raise Conflict('original CPU unit phase write attempt changed')
        self._phase_attempts[phase] = raw

    def _original_assessment_attempt(self, value):
        """Retry the exact retained fact, never resample unknown acceptance."""
        self._check_final()
        phase = 'decision' if 'prior_assessment_key' in value['request'] else 'assessment'
        raw = self._phase_attempts.get(phase)
        if raw is None: return value
        original = json.loads(raw)
        if canonical(original['request']) != canonical(value['request']):
            raise Conflict('original CPU unit phase request changed')
        return original

    def _finish(self, *, allow_apply):
        # Both stages are readonly evaluations of the retained original raw
        # result, not another experiment, candidate write or token renewal.
        token = self.runtime._issued(self.lease)['token']
        for phase in ('assessment', 'decision'):
            request = self._phase_requests.get(phase)
            if request is None:
                self._check_operation()
                request = {'idempotency_key': 'cpu_unit_' + phase + '_' + sha(self._request),
                           'expected_state_version': self.runtime.store.version()}
                if phase == 'decision':
                    request['assessment_key'] = fact_key(self._phase_facts['assessment']['request'])
                self._phase_requests[phase] = request
            try:
                method = self.output.assess if phase == 'assessment' else self.output.decide
                receipt = method(self.lease, token, **request)
            except Exception:
                # Rejected pre-write/stale activation is not an unknown
                # accepted request. A real write attempt remains immutable.
                if phase not in self._phase_attempts: self._phase_requests.pop(phase, None)
                raise
            self._phase_facts[phase] = receipt['fact']
        machine = self._phase_facts['decision']['machine_verification']
        status = ('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW' if machine['status'] == 'MACHINE_VERIFIED'
                  else 'EXPERIMENT_MACHINE_UNAVAILABLE')
        self._last = self._state(status, fact=self._phase_facts['decision'])
        return self._last

    def _resume(self):
        self._actual()
        if self._last is not None: return {**self._last, 'cancel_requested': self._cancelled.is_set()}
        if self._request is None: raise Conflict('no original execution unit request to resume')
        if self._cancelled.is_set():
            cleanup = self._cleanup()
            fact = self._phase_facts.get('assessment')
            status = ('EXPERIMENT_ASSESSED_CANCELLED' if fact is not None else
                      'CANCELLED_SCOPE_STOPPED' if cleanup['complete'] else 'UNKNOWN_CLEANUP_REQUIRED')
            return self._state(status, fact=fact, cleanup_error=cleanup['error'])
        if id(self.lease) not in self.runtime._cpu_results:
            cleanup = self._cleanup()
            return self._state('UNKNOWN_RESULT_UNAVAILABLE', cleanup_error=cleanup['error'])
        cleanup = self._cleanup()
        if not cleanup['complete']: return self._state('UNKNOWN_CLEANUP_REQUIRED', cleanup_error=cleanup['error'])
        return self._finish(allow_apply=False)
