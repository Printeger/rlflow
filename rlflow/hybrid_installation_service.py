"""Actual fresh fixture two-phase installation, NEVER runtime capability.

The fixed material builder supplies a live held original inventory after hashes
outside the writer. Only this original owner can append its immutable core fact.
INTENT must be durable before descriptor-relative no-replace publication. READY
uses the exact original core seal and fresh CAS; unknown returns retain material.
"""
import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import threading

from .hybrid_fixture_materials import FixtureMaterialBuilder, _MaterialWitness, _deadline
from .hybrid_runtime_installation import (SECTIONS, EVENTS, intent_key, publication_key, event_inputs,
    validate_record, validate_complete)
from .hybrid_goals import digest
from .hybrid_runtime_boundary import _held_chain, directory_chain
from .hybrid_reads import ReadBudget
from .observation import ObservationReader
from .store import Conflict, canonical


class _RenameReceipt:
    """Protected native-success observation, not a publication capability."""
    def __init__(self,parent_fd,old_name,new_name):
        self.parent_fd,self.old_name,self.new_name=parent_fd,old_name,new_name
        info=os.fstat(parent_fd);self.parent_identity=(info.st_dev,info.st_ino)
        self.thread=threading.get_ident();self.succeeded=False


def _rename_no_replace(parent_fd, old_name, new_name,*,_receipt=None):
    """Linux renameat2(RENAME_NOREPLACE), no ordinary rename fallback."""
    if (any(type(name) is not str or not name or '/' in name or '\x00' in name or name in ('.', '..')
            for name in (old_name, new_name)) or type(parent_fd) is not int or parent_fd < 0):
        raise Conflict('fixed original relative publication names required')
    if _receipt is not None:
        info=os.fstat(parent_fd)
        if (type(_receipt) is not _RenameReceipt or _receipt.succeeded or
                (_receipt.parent_fd,_receipt.old_name,_receipt.new_name,_receipt.thread,_receipt.parent_identity)!=
                (parent_fd,old_name,new_name,threading.get_ident(),(info.st_dev,info.st_ino))):
            raise PermissionError('actual original native rename receipt required')
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, 'renameat2', None)
    if function is None: raise PermissionError('actual kernel no-replace publication unavailable')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent_fd, os.fsencode(old_name), parent_fd, os.fsencode(new_name), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    if _receipt is not None:_receipt.succeeded=True


class _Guard:
    def __init__(self, owner, db, witness, value, version, section):
        self.owner, self.db, self.witness = owner, db, witness
        self.raw = canonical(value); self.start_version = version; self.section = section
        self.thread = threading.get_ident(); self.read = ReadBudget(db, 16*1024**2)

    def check(self): self.owner.check_guard(self.db, self)


@dataclass(frozen=True, eq=False)
class _BootstrapWitness:
    """Original live inventory context, NOT a serialized execution permit."""
    owner: object
    material: object
    inventory: object
    raw: bytes
    thread: int


class FixtureInstallationService:
    def __init__(self, builder):
        if type(builder) is not FixtureMaterialBuilder:
            raise TypeError('fixed actual fixture material builder required')
        builder._check()
        self.builder, self.store = builder, builder.store
        self._lock = threading.RLock(); self._active = None; self._published = None
        self._bootstrap_contexts = {}
        self.project_id, self.store_epoch = builder.project_id, builder.store_epoch
        self.data_mode=builder.data_mode
        self.store.bind_hybrid_installation(self)

    def _metadata(self, db):
        if self.builder.data_mode!=self.data_mode:
            raise Conflict('original installation builder domain changed')
        if self.store._hybrid_installation_service is not self:
            raise PermissionError('original bound fixture installation owner required')
        self.builder._check_physical()
        meta = ObservationReader._meta(db)
        version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
        tip = db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
        if ((meta['project_id'], meta['data_mode'], meta['store_epoch']) !=
                (self.project_id, self.data_mode, self.store_epoch) or
                type(version) is not int or meta['source_version'] != version or tip != version):
            raise Conflict('actual fixture installation registration or source tip differs')
        return version

    def _state(self, db, read, version):
        state = {'version': version}
        for section in SECTIONS:
            rows = db.execute('SELECT object_key FROM projection WHERE section=? ORDER BY object_key LIMIT 3',
                              (section,)).fetchall()
            if len(rows) > 2:
                raise Conflict('fixture installation projection count exceeds bound')
            if rows:
                if rows[0][0] != '' or read.object(section, '') != {}:
                    raise Conflict('fixture installation original collection marker missing')
                state[section] = {row[0]: read.object(section, row[0]) for row in rows[1:]}
        validate_complete(state, (self.project_id, self.data_mode),
                          lambda key: self.store._installation_event(db, key, _parse=read.parse, _decode=read.decode),
                          event_summary=self.store._installation_summary(db, version))
        return state

    def _point(self, db, read, version, section, key, expected):
        state = self._state(db, read, version)
        value = state.get(section, {}).get(key)
        if value != expected:
            raise Conflict('original fixture installation core fact differs')
        return value

    @contextmanager
    def _bootstrap_witness(self, material):
        """Original READY + actual issued release, hashes OUTSIDE the writer.

        Lifetime retains the original inventory; no Installation/Builder lock
        is held while waiting for a subsequent Controller writer. This does
        not enable execution. Its only consumer must prove its OWN fixed
        Store writer and current authority before using these source refs.
        """
        if self._active is not None and self._active.thread == threading.get_ident():
            raise Conflict('nested original installation bootstrap witness refused')
        with self.builder._witness(material) as inventory:
            with self._lock, self.builder._lock:
                if self._published is not material or inventory.path != material.release_path:
                    raise PermissionError('original owner-published bootstrap required')
                _, original = self.builder._slot(material); ready = self._ready_value(original)
                refs = {'intent_key': intent_key(original['request']), 'intent_hash': digest(original),
                    'publication_key': publication_key(ready['request']), 'publication_hash': digest(ready),
                    'expected_seal_hash': digest(original['expected_seal']),
                    'project_id': self.project_id, 'data_mode': self.data_mode, 'store_epoch': self.store_epoch,
                    'installation_id': material.id, 'release_id': ready['release_id']}
                if self.data_mode=='live':
                    refs['domain_profile']=original['request']['domain_profile']
                if len(self._bootstrap_contexts) >= 32:
                    raise Conflict('original bootstrap witness capacity reached')
                witness = _BootstrapWitness(self, material, inventory, canonical(refs), threading.get_ident())
                self._bootstrap_contexts[id(witness)] = witness
            try:
                # This owned read is historical/source verification only, NOT
                # admission. Later plan CAS repeats the point in its owned DB.
                with self.store.read_connection() as db:
                    db.execute('BEGIN')
                    self._bootstrap_point(db, witness, ReadBudget(db, 16*1024**2))
                yield witness
            finally:
                with self._lock: self._bootstrap_contexts.pop(id(witness), None)

    def _bootstrap_point(self, db, witness, read):
        """Bounded original source proof; caller separately owns its writer.

        No token, guard, budget mutation, runtime permission or new TTL is
        issued here. WorkingPlan's guard MUST enforce exact owned DB/current
        Controller, source and workspace authorization before any CAS.
        """
        # Private original identity BEFORE parsing any fields/caller bytes.
        if (type(witness) is not _BootstrapWitness or
                self._bootstrap_contexts.get(id(witness)) is not witness or
                witness.owner is not self or witness.thread != threading.get_ident() or
                type(read) is not ReadBudget or read.db is not db or not db.in_transaction):
            raise PermissionError('actual active original bootstrap witness required')
        version = self._metadata(db)
        if version < 2: raise Conflict('original durable installation READY required')
        if (self._published is not witness.material or witness.inventory.builder is not self.builder or
                witness.inventory.material is not witness.material or
                witness.inventory.path != witness.material.release_path or
                witness.material.stage_path.exists() or witness.material.stage_path.is_symlink()):
            raise Conflict('actual original owner-published release required')
        _, original = self.builder._slot(witness.material); ready = self._ready_value(original)
        state = self._state(db, read, version); refs = json.loads(witness.raw)
        expected = {'intent_key': intent_key(original['request']), 'intent_hash': digest(original),
                    'publication_key': publication_key(ready['request']), 'publication_hash': digest(ready),
                    'expected_seal_hash': digest(original['expected_seal']), 'project_id': self.project_id,
                    'data_mode': self.data_mode, 'store_epoch': self.store_epoch,
                    'installation_id': witness.material.id, 'release_id': ready['release_id']}
        if self.data_mode=='live':expected['domain_profile']=original['request']['domain_profile']
        if (state.get(SECTIONS[0], {}).get(refs['intent_key']) != original or
                state.get(SECTIONS[1], {}).get(refs['publication_key']) != ready or
                refs != expected):
            raise Conflict('original bootstrap source reference differs')
        witness.inventory.check(); _deadline(witness.inventory.deadline)
        return refs

    @staticmethod
    def _ready_value(original):
        request = {**original['request'], 'action': 'publish_fixture_runtime_installation',
            'expected_state_version': 1, 'idempotency_key': 'fixture_ready',
            'intent_key': intent_key(original['request']), 'intent_hash': digest(original)}
        if request['data_mode']=='live':
            from .hybrid_live_domain import PUBLISH
            request['action']=PUBLISH
        return {'request': request, 'request_hash': digest(request), 'accepted_state_version': 2,
            'catalog_sha256': original['expected_seal']['descriptor']['catalog_sha256'],
            'release_id': original['expected_seal']['release_id'],
            'state': 'LEGACY_DENIED_READY_NONEXECUTING', 'execution_enabled': False, 'release_enabled': False}

    def check_guard(self, db, guard):
        if (type(guard) is not _Guard or guard is not self._active or guard.owner is not self or
                guard.db is not db or guard.thread != threading.get_ident() or
                type(guard.witness) is not _MaterialWitness or guard.witness.builder is not self.builder):
            raise PermissionError('actual original fixture installation guard required')
        version = self._metadata(db); guard.witness.check()
        _, original = self.builder._slot(guard.witness.material)
        if guard.section not in SECTIONS:
            raise PermissionError('original installation phase required')
        expected = original if guard.section == SECTIONS[0] else self._ready_value(original)
        if guard.raw != canonical(expected):
            raise Conflict('actual fixture installation raw material differs')
        key = intent_key(original['request'])
        phase = SECTIONS.index(guard.section)
        if version != guard.start_version and not (guard.start_version == phase and version == phase + 1):
            raise Conflict('actual original installation transaction version changed')
        if version == 0:
            if guard.section != SECTIONS[0] or guard.start_version != 0 or self.store._installation_summary(db, version) != (None, 0):
                raise Conflict('actual fresh fixture installation requires empty history')
            self._state(db, guard.read, version)
        elif version in (1, 2) and guard.start_version in (0, 1, 2):
            self._point(db, guard.read, version, SECTIONS[0], key, original)
            if version == 2:
                ready = self._ready_value(original)
                self._point(db, guard.read, version, SECTIONS[1], publication_key(ready['request']), ready)
        else:
            raise Conflict('fixture installation original fresh CAS no longer current')
        if guard.section == SECTIONS[1] and (
                self._published is not guard.witness.material or
                guard.witness.path != guard.witness.material.release_path or
                guard.witness.material.stage_path.exists() or guard.witness.material.stage_path.is_symlink()):
            raise Conflict('original physically published fixture required before READY')
        guard.witness.check()
        # Original source decoding/hash/complete checks above can consume the
        # remaining cooperative window. They never make an old witness fresh.
        _deadline(guard.witness.deadline)

    def check_live_write(self, db, payload, inputs, guard):
        self.check_guard(db, guard)
        value = json.loads(guard.raw)
        key = intent_key(value['request']) if guard.section == SECTIONS[0] else publication_key(value['request'])
        expected = {'format': 2, 'put': [[guard.section, key, value], [guard.section, '', {}]],
                    'delete': [], 'details': None}
        if (sorted(payload['put'], key=lambda row: row[1]) != sorted(expected['put'], key=lambda row: row[1]) or
                {k: v for k, v in payload.items() if k != 'put'} != {k: v for k, v in expected.items() if k != 'put'} or
                inputs != event_inputs(value) or self._metadata(db) != SECTIONS.index(guard.section)):
            raise Conflict('actual original installation phase payload and fresh CAS required')
        if guard.section == SECTIONS[0] and (guard.witness.path != guard.witness.material.stage_path or
                guard.witness.material.release_path.exists() or guard.witness.material.release_path.is_symlink()):
            raise Conflict('actual original unpublished installation INTENT required')

    def persist_intent(self, material):
        """Actual hashes outside writer, original immutable INTENT before publish."""
        return self._persist(SECTIONS[0], material)

    def persist_ready(self, material):
        """Only original published material + original core INTENT, no disk adoption."""
        return self._persist(SECTIONS[1], material)

    def _persist(self, section, material):
        # We manage the same Store transaction here so the guard retains its
        # exact DB connection through _commit and actual COMMIT.
        if self._active is not None and self._active.thread == threading.get_ident():
            raise Conflict('nested actual fixture installation writer refused')
        with self.builder._witness(material) as witness:
            with self.store.lock(), self._lock, self.builder._lock, self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if self._active is not None: raise Conflict('installation owner already active')
                _, original = self.builder._slot(material)
                phase = SECTIONS.index(section); value = original if phase == 0 else self._ready_value(original)
                key = intent_key(value['request']) if phase == 0 else publication_key(value['request'])
                validate_record(section, key, value)
                guard = _Guard(self, db, witness, value, self._metadata(db), section); self._active = guard
                try:
                    guard.check()
                    result = {'version': phase + 1, 'intent_key' if phase == 0 else 'publication_key': key}
                    if self.store._existing(db, key, EVENTS[phase], value['request']['installation_id']):
                        self._point(db, guard.read, guard.start_version, section, key, value)
                        guard.check(); _deadline(witness.deadline); db.commit()
                        return {**result, 'duplicate': True}
                    payload = {'format': 2, 'put': [[section, key, value], [section, '', {}]],
                               'delete': [], 'details': None}
                    self.store._commit(db, EVENTS[phase], key, payload, phase, value['request']['installation_id'],
                                       'hybrid-installer', event_inputs(value), _authorization=guard)
                    guard.check(); _deadline(witness.deadline); db.commit()
                    return {**result, 'duplicate': False}
                finally:
                    self._active = None

    def publish(self, material):
        """INTENT -> original no-replace publish -> READY. Never enable execution."""
        self._publish(material)
        return self.persist_ready(material)

    def _publish(self, material):
        if self._active is not None and self._active.thread == threading.get_ident():
            raise Conflict('nested actual fixture installation writer refused')
        with self.builder._witness(material) as witness:
            with self.store.lock(), self._lock, self.builder._lock, self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                version = self._metadata(db)
                if version not in (1, 2): raise Conflict('original current durable installation INTENT required')
                entry, value = self.builder._slot(material); read = ReadBudget(db, 16*1024**2)
                self._point(db, read, version, SECTIONS[0], intent_key(value['request']), value)
                if version == 2:
                    ready = self._ready_value(value)
                    self._point(db, read, version, SECTIONS[1], publication_key(ready['request']), ready)
                witness.check(); _deadline(witness.deadline)
                with _held_chain(material.release_path.parent) as (fds, chain):
                    if chain != value['binding']['release_parent_chain']:
                        raise Conflict('original fixed publication parent differs')
                    if witness.path == material.stage_path:
                        if version != 1: raise Conflict('READY cannot republish another stage')
                        _deadline(witness.deadline)
                        _rename_no_replace(fds[-1], material.stage_path.name, material.release_path.name)
                    elif witness.path != material.release_path:
                        raise Conflict('actual original publication path required')
                    # Recheck/fsync even a prior unknown rename return. Never
                    # remint, delete, overwrite, fall back or infer durability
                    # just because a caller-selected directory happens to exist.
                    if (directory_chain(material.release_path)[-1] != entry['stage_identity'] or
                            material.stage_path.exists() or material.stage_path.is_symlink()):
                        raise Conflict('original actual published directory identity differs')
                    os.fsync(fds[-1])
                    if directory_chain(material.release_path.parent) != chain:
                        raise Conflict('original publication parent changed after fsync')
                    self._metadata(db); _deadline(witness.deadline)
                    self._published = material  # ONLY original fsynced owner path.
                    db.commit()
