"""Original finite Host's process-local, conservative FS admission.

Available blocks/inodes are observations, NOT a quota or durable Budget fact.
No allocation, audit reserve, restart adoption, automatic dispatch or refund.
STOP never calls this new-work gate. All IO precedes final authority sampling.
"""
import os

from .hybrid_runtime_boundary import _held_chain
from .store import Conflict

FLOOR_BYTES = 128 * 1024**2
WORK_BYTES = 16 * 1024**2
FLOOR_INODES = 16
WORK_INODES = 8
MAX_FILESYSTEMS = 3


class _DiskAdmission:
    def __init__(self, host):
        self.host = host
        self._rows = ()
        host.pool._disk_admission = self

    def _actual(self):
        self.host._pure_identity()
        if getattr(self.host.pool, '_disk_admission', None) is not self:
            raise PermissionError('original finite disk domain required')

    @staticmethod
    def _anchor(path):
        with _held_chain(path) as (fds, chain):
            info = os.fstat(fds[-1]); space = os.fstatvfs(fds[-1])
            return (path, chain, (info.st_dev, space.f_fsid))

    def bind(self, unit, attempt):
        self._actual()
        if any(row['unit'] is unit for row in self._rows):
            return
        slot, _ = unit.runtime.workspace.working._slot(attempt['observation'])
        slot['hold'].check()
        paths = (self.host.pool.root, unit.runtime.store.root / 'runtime', slot['copy'].path)
        anchors = tuple(self._anchor(path) for path in paths)
        filesystems = {anchor[2] for row in self._rows for anchor in row['anchors']}
        filesystems.update(anchor[2] for anchor in anchors)
        if len(filesystems) > MAX_FILESYSTEMS:
            raise Conflict('disk admission unsupported filesystem count')
        self._rows = (*self._rows, {'unit': unit, 'claim_key': attempt['claim_value']['key'],
                                  'anchors': anchors})

    def _observe(self):
        self._actual()
        if not self.host.pool._lock._is_owned():
            raise PermissionError('original held Pool disk observation required')
        snapshot = self.host.pool.snapshot()
        active = {head['claim_key'] for head in snapshot['heads']
                  if head is not None and head['state'] != 'FREE'}
        known = {row['claim_key'] for row in self._rows}
        unknown = bool(active - known)
        buckets = {}
        for row in self._rows:
            unit = row['unit']; unit._pure_identity()
            attempt = unit.runtime._leases[id(unit.lease)]
            # FREE alone does not close engineering apply/accept or CPU facts.
            closed = (row['claim_key'] not in active and attempt['terminal'] is not None and
                      attempt.get('pool_closed') is not None and
                      (unit._last is not None or
                       (unit._cancelled.is_set() and
                        getattr(unit, '_disk_cleanup_complete', False))))
            for path, chain, filesystem in row['anchors']:
                with _held_chain(path) as (fds, current):
                    info = os.fstat(fds[-1]); space = os.fstatvfs(fds[-1])
                    if current != chain or (info.st_dev, space.f_fsid) != filesystem:
                        raise Conflict('original disk filesystem binding changed')
                    available = space.f_bavail * space.f_frsize
                    inodes = space.f_favail
                    if available < 0 or inodes < 0 or space.f_frsize <= 0:
                        raise Conflict('original disk availability unavailable')
                    bucket = buckets.setdefault(filesystem, {'available_bytes': available,
                        'available_inodes': inodes, 'claims': set()})
                    bucket['available_bytes'] = min(bucket['available_bytes'], available)
                    bucket['available_inodes'] = min(bucket['available_inodes'], inodes)
                    if not closed: bucket['claims'].add(row['claim_key'])
        rows = []
        for bucket in buckets.values():
            credits = len(bucket['claims'])
            required_bytes = FLOOR_BYTES + credits * WORK_BYTES
            required_inodes = FLOOR_INODES + credits * WORK_INODES
            rows.append({'available_bytes': bucket['available_bytes'],
                'available_inodes': bucket['available_inodes'], 'promised_claims': credits,
                'required_bytes': required_bytes, 'required_inodes': required_inodes,
                'admissible': (bucket['available_bytes'] >= required_bytes and
                               bucket['available_inodes'] >= required_inodes)})
        admissible = bool(rows) and not unknown and all(row['admissible'] for row in rows)
        return {'profile': 'PROCESS_LOCAL_FS_AVAILABLE_NOT_QUOTA',
            'new_run_admissible': admissible, 'unbound_occupied_claim': unknown,
            'filesystems': rows, 'stop_gated': False, 'audit_reserve_allocated': False,
            'restart_credit_recovery': False, 'goal_completed': False}

    def check(self, unit):
        self._actual()
        if not any(row['unit'] is unit for row in self._rows):
            raise PermissionError('original disk-bound execution unit required')
        with self.host.pool._lock:
            observation = self._observe()
            if not observation['new_run_admissible']:
                raise Conflict('disk admission unavailable; original STOP remains allowed')

    def health(self):
        self._actual()
        with self.host.pool._lock:
            return self._observe()


def check_effect(runtime, attempt):
    domain = getattr(runtime.pool, '_disk_admission', None)
    if domain is not None:
        domain.check(runtime._execution_units.get(id(attempt['lease'])))
