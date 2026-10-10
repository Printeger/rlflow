"""Original finite Host's process-local, conservative FS admission.

Available blocks/inodes are observations, NOT a quota or durable Budget fact.
Small original-FD audit reserve, no restart adoption or automatic dispatch.
STOP never calls this new-work gate. All IO precedes final authority sampling.
"""
import os
import threading

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
        self._locations = {}
        self._reserves = {}
        self._emergency_frozen = False
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
        locations = dict(self._locations)
        for anchor in anchors:
            if anchor[2] not in locations:
                location = self._anchor(anchor[0].parent) if anchor[0] == slot['copy'].path else anchor
                if location[2] != anchor[2]:raise Conflict('private same-FS reserve location unavailable')
                locations[anchor[2]] = location
        filesystems = {anchor[2] for row in self._rows for anchor in row['anchors']}
        filesystems.update(anchor[2] for anchor in anchors)
        if len(filesystems) > MAX_FILESYSTEMS:
            raise Conflict('disk admission unsupported filesystem count')
        self._rows = (*self._rows, {'unit': unit, 'claim_key': attempt['claim_value']['key'],
                                  'anchors': anchors})
        self._locations = locations

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
        reserves = [reserve.observe() for reserve in self._reserves.values()]
        ready = (set(self._reserves) == set(self._locations) and
                 all(row['allocation_complete'] and not row['released'] for row in reserves))
        admissible = (bool(rows) and not unknown and not self._emergency_frozen and ready and
                      all(row['admissible'] for row in rows))
        return {'profile': 'PROCESS_LOCAL_FS_AVAILABLE_NOT_QUOTA',
            'new_run_admissible': admissible, 'unbound_occupied_claim': unknown,
            'filesystems': rows, 'stop_gated': False,
            'audit_reserve_allocated': bool(reserves) and ready,
            'audit_reserves': reserves, 'emergency_frozen': self._emergency_frozen,
            'reserve_profile': 'SMALL_BEST_EFFORT_NOT_COMMIT_GUARANTEE',
            'restart_credit_recovery': False, 'goal_completed': False}

    def check(self, unit, *, allocate=False):
        self._actual()
        if not any(row['unit'] is unit for row in self._rows):
            raise PermissionError('original disk-bound execution unit required')
        with self.host.pool._lock:
            observation = self._observe()
            retry_allocation = (allocate and not self._emergency_frozen and
                not observation['unbound_occupied_claim'] and
                all(row['admissible'] for row in observation['filesystems']))
            if not observation['new_run_admissible'] and not retry_allocation:
                raise Conflict('disk admission unavailable; original STOP remains allowed')
            if allocate:
                from .hybrid_audit_reserve import _AuditReserve
                for filesystem, anchor in self._locations.items():
                    reserve = self._reserves.get(filesystem)
                    if reserve is None:
                        reserve = _AuditReserve(self, anchor)
                        self._reserves[filesystem] = reserve  # retain before allocation IO
                    reserve.allocate()
                if not self._observe()['new_run_admissible']:
                    raise Conflict('disk admission unavailable after actual reserve allocation')

    def prepare_stop(self, unit, scope):
        self._actual(); unit._pure_identity()
        if not any(row['unit'] is unit for row in self._rows):return
        original = scope.get('_disk_rescue')
        if original is not None:
            if original['domain'] is not self or original['unit'] is not unit:
                raise PermissionError('original same-operation rescue required')
            if original['error'] is not None:raise original['error']
            return
        record = {'domain': self, 'unit': unit, 'error': None}
        scope['_disk_rescue'] = record
        try:
            # Physical sources only, BEFORE waiting for Pool or any Store
            # writer. Neither broken ledger reads nor slot capacity authorize
            # release. Identity unknown freezes but never truncates by path.
            low = set()
            for row in self._rows:
                for path, chain, filesystem in row['anchors']:
                    with _held_chain(path) as (fds, current):
                        info = os.fstat(fds[-1]); space = os.fstatvfs(fds[-1])
                        if current != chain or (info.st_dev, space.f_fsid) != filesystem:
                            raise Conflict('original rescue filesystem binding changed')
                        available = space.f_bavail * space.f_frsize
                        inodes = space.f_favail
                        if available < 0 or inodes < 0 or space.f_frsize <= 0:
                            raise Conflict('original rescue availability unavailable')
                        if available < FLOOR_BYTES or inodes < FLOOR_INODES:
                            low.add(filesystem)
            rescuable = {fs for fs, reserve in self._reserves.items()
                         if reserve.fd is not None or reserve.creation_entered}
            low.update(fs for fs in rescuable if not self._reserves[fs].allocated)
            rescue = low & rescuable
            # A known pre-HANDOFF denial with no creation has consumed no
            # emergency capacity. Keep the original healthy retry possible.
            # Missing reserve in an unfinished HANDOFF is instead UNKNOWN.
            unsafe_handoff = any(
                (attempt := row['unit'].runtime._leases[id(row['unit'].lease)])['terminal'] is None and
                (attempt['spawn_entered'] or 'HANDOFF_UNKNOWN' in attempt['entries'])
                for row in self._rows)
            if rescue or (low and unsafe_handoff):
                self._emergency_frozen = True  # pure, before Pool wait/release IO
                with self.host.pool._lock:
                    self._actual()
                    errors = []
                    for fs in rescue:
                        reserve = self._reserves.get(fs)
                        if reserve is not None:
                            try:reserve.release()
                            except BaseException as error:errors.append(error)
                    if errors:raise errors[0]
        except BaseException as error:
            self._emergency_frozen = True
            record['error'] = error
            raise

    def shutdown_owned(self):
        self._actual()
        errors = []
        for reserve in self._reserves.values():
            try:reserve.shutdown()
            except BaseException as error:errors.append(error)
        if errors:raise errors[0]

    def _fork_child_close(self):
        for reserve in self._reserves.values():reserve.child_close()

    def health(self):
        self._actual()
        with self.host.pool._lock:
            return self._observe()


def check_effect(runtime, attempt, *, allocate=False):
    domain = getattr(runtime.pool, '_disk_admission', None)
    if domain is not None:
        domain.check(runtime._execution_units.get(id(attempt['lease'])), allocate=allocate)


def prepare_stop(runtime, attempt):
    domain = getattr(runtime.pool, '_disk_admission', None)
    unit = runtime._execution_units.get(id(attempt['lease']))
    if domain is None or unit is None:return
    service = runtime._control_service
    operation = service._operation() if service is not None else None
    if operation is not None:
        scope = getattr(operation, '_disk_stop_scope', None)
        if scope is None:
            scope = {}; operation._disk_stop_scope = scope
    elif unit._operation_thread == threading.get_ident():
        scope = unit._disk_stop_scope
    else:scope = {}
    domain.prepare_stop(unit, scope)


def check_final(runtime):
    domain = getattr(runtime.pool, '_disk_admission', None)
    if domain is not None and domain._emergency_frozen:
        raise Conflict('audit reserve emergency permanently freezes new effects')
