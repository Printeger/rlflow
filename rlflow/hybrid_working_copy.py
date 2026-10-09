"""Process-local isolated working copies; no Store or execution authority.

Protected startup fixes the snapshot builder and a disjoint private namespace.
Copies preserve the original library snapshot. Their initial copy descriptor is
not reused as an immutable descriptor after a writer modifies the working tree.
Expired observations deny operations but retain the actual cooperating inode
lock. Explicit cleanup is safe ONLY here, where no writer has been handed off.
Persistent source/budget bindings and runtime handoff are deliberately absent.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .hybrid_snapshot import SnapshotBuilder, CandidateSnapshot
from .hybrid_workspace_kernel import DirectoryHold, _chain, _private, _local_mount
from .jobs import identity
from .store import Conflict, canonical, sha


@dataclass(frozen=True, eq=False)
class WorkingCopyObservation:
    id: str
    raw: bytes
    issued_monotonic_ns: int
    expires_monotonic_ns: int


@dataclass(frozen=True, eq=False)
class ClosedWorkingCopyWitness:
    """Actual owner-issued physical close success, not caller JSON attestation."""
    id: str
    raw: bytes
    observation: WorkingCopyObservation


class WorkingCopyOwner:
    """Actual issued-object observations, never JSON/path/FD adoption.

    No worker can be registered through this owner. A future persistent owner
    must bind the same held capability to controller/source/budget transactions
    before authorizing ANY writer; this class alone is not that authorization.
    """
    def __init__(self, builder, namespace, *, clock=lambda: datetime.now(timezone.utc),
                 monotonic_ns=time.monotonic_ns):
        if type(builder) is not SnapshotBuilder:raise TypeError('actual snapshot builder required')
        self.builder=builder;self.namespace=Path(namespace).absolute()
        for root in (builder.source,builder.root):
            if self.namespace==root or self.namespace in root.parents or root in self.namespace.parents:
                raise Conflict('working namespace must be disjoint from source and snapshot library')
        self._owner=identity(os.getpid())
        if self._owner is None:raise Conflict('actual working copy owner unavailable')
        self._lock=threading.RLock();self._clock_lock=threading.Lock()
        self._clock=clock;self._monotonic_ns=monotonic_ns;self._last_sample=None
        self._issued={};self._closed_witnesses={};self._mount_namespace=os.stat('/proc/thread-self/ns/mnt').st_ino
        with _chain(self.namespace) as (fds,chain):
            _private(fds[-1]);_local_mount(chain[-1][2]);self._namespace_chain=chain
        self._protected_chains={}
        for root in (builder.source,builder.root):
            with _chain(root) as (_,chain):
                _local_mount(chain[-1][2]);self._protected_chains[root]=chain
        self._namespace_check()

    def _owner_check(self):
        if identity(os.getpid())!=self._owner:raise PermissionError('actual original working copy process required')

    def _namespace_check(self):
        if os.stat('/proc/thread-self/ns/mnt').st_ino!=self._mount_namespace:
            raise Conflict('working namespace mount changed')
        with _chain(self.namespace) as (fds,chain):
            _private(fds[-1])
            if chain!=self._namespace_chain:raise Conflict('working namespace rebound')
            # Compare physical dev/inode, NOT mount id: a bind alias still
            # denotes the same underlying directory. Whole-FS aliases expose
            # their physical ancestors; subtree roots were refused above.
            for root,original in self._protected_chains.items():
                with _chain(root) as (_,protected):
                    if protected!=original:raise Conflict('working protected root rebound')
                    if (protected[-1][:2] in [item[:2] for item in chain] or
                            chain[-1][:2] in [item[:2] for item in protected]):
                        raise Conflict('working namespace physical roots overlap')

    def _sample(self):
        with self._clock_lock:
            now=self._clock();mono=self._monotonic_ns()
            if (type(now) is not datetime or now.tzinfo is None or now.utcoffset().total_seconds()!=0 or
                    type(mono) is not int or not 0<=mono<=2**63-1-60*10**9):
                raise Conflict('actual UTC and monotonic working copy clocks required')
            if self._last_sample is not None and (now<self._last_sample[0] or mono<self._last_sample[1]):
                raise Conflict('working copy clock regressed')
            self._last_sample=now,mono
            return now,mono

    @staticmethod
    def _ttl(ttl):
        if type(ttl) is not int or not 1<=ttl<=60:raise Conflict('working copy TTL must be an integer in 1..60')

    def _observation(self, slot, ttl, now, mono):
        value=dict(slot['binding']);value.update({'observation_id':'working_observation_'+uuid.uuid4().hex,
            'epoch':slot['epoch'],'checked_at':now.isoformat().replace('+00:00','Z'),
            'expires_at':(now+timedelta(seconds=ttl)).isoformat().replace('+00:00','Z'),
            'execution_enabled':False,'release_enabled':False})
        return WorkingCopyObservation(value['observation_id'],canonical(value),mono,mono+ttl*10**9)

    def acquire(self, snapshot, *, ttl_seconds=30):
        self._owner_check();self._ttl(ttl_seconds)
        with self._lock:
            if len(self._issued)+len(self._closed_witnesses)>=128:raise Conflict('working copy owner capacity reached')
            self._namespace_check()
            # verify requires exact object identity in the ORIGINAL builder.
            self.builder.verify(snapshot)
            if type(snapshot) is not CandidateSnapshot:raise PermissionError('actual base snapshot required')
            base=json.loads(snapshot.raw)
            copier=SnapshotBuilder(snapshot.path,[row['name'] for row in base['files']],self.namespace,
                byte_limit=self.builder.byte_limit,seconds=self.builder.seconds,clock=self.builder.clock)
            copy=copier.build();hold=None
            try:
                self._namespace_check();self.builder.verify(snapshot);copier.verify(copy)
                copied=json.loads(copy.raw)
                # source_executable describes each copier's SOURCE, not copy
                # bytes. Original executable provenance need not equal the
                # non-executable library file used as this copier's source.
                content=lambda rows:[{k:v for k,v in row.items() if k!='source_executable'} for row in rows]
                if content(copied['files'])!=content(base['files']) or copied['total_bytes']!=base['total_bytes']:
                    raise Conflict('working copy initial content differs from base')
                hold=DirectoryHold(copy.path);kernel=hold.check();self._namespace_check()
                slot={'hold':hold,'copy':copy,'base':snapshot,'epoch':1,'binding':{
                    'workspace_id':'working_copy_'+uuid.uuid4().hex,'base_snapshot_id':snapshot.id,
                    'base_snapshot_hash':base['tree_hash'],'initial_copy_hash':copied['tree_hash'],
                    'output_snapshot_hash':None,'kernel':kernel,'state':'HELD_PRE_RUNTIME'}}
                now,mono=self._sample();observation=self._observation(slot,ttl_seconds,now,mono)
                slot['observation']=observation;self._issued[slot['binding']['workspace_id']]=slot
                return observation
            except BaseException:
                if hold is not None:hold.close()
                # Preserve the private provisional artifact, never delete a
                # possibly rebound path as a side effect of failed issuance.
                raise

    def _slot(self, observation):
        if type(observation) is not WorkingCopyObservation:raise PermissionError('actual issued working observation required')
        # <=128 private slots. Reject forged/stale/foreign exact-type objects
        # BEFORE parsing caller-supplied bytes, including oversized/deep JSON.
        slot=next((slot for slot in self._issued.values() if slot['observation'] is observation),None)
        if slot is None:
            raise PermissionError('actual current working observation required')
        return slot,json.loads(observation.raw)

    def _live(self, observation):
        slot,value=self._slot(observation)
        self._namespace_check();kernel=slot['hold'].check()
        if kernel!=slot['binding']['kernel']:raise Conflict('working copy Kernel identity changed')
        now,mono=self._sample()
        # All filesystem checks precede the final freshness sample.
        checked=datetime.fromisoformat(value['checked_at'].replace('Z','+00:00'))
        expires=datetime.fromisoformat(value['expires_at'].replace('Z','+00:00'))
        if not (checked<=now<expires and observation.issued_monotonic_ns<=mono<observation.expires_monotonic_ns):
            raise Conflict('working copy observation expired')
        return slot,value,now,mono

    def check(self, observation):
        self._owner_check()
        with self._lock:return self._live(observation)[1]

    def renew(self, observation, *, ttl_seconds=30):
        self._owner_check();self._ttl(ttl_seconds)
        with self._lock:
            slot,_,now,mono=self._live(observation)
            slot['epoch']+=1
            new=self._observation(slot,ttl_seconds,now,mono);slot['observation']=new
            return new

    def close_pre_runtime(self, observation):
        """Explicit no-handoff cleanup, even after expiry; NOT runtime STOP."""
        self._owner_check()
        with self._lock:
            slot,value=self._slot(observation)
            slot['hold'].close()
            if not slot['hold']._closed or slot['hold']._fd is not None or slot['hold']._parent_fd is not None:
                raise Conflict('working physical close remains uncertain')
            # Mint before deleting the original slot. If minting fails after
            # physical close, the same actual slot remains explicitly retryable;
            # it is never mistaken for a still-live FD by check().
            wid='working_closed_'+uuid.uuid4().hex
            raw=canonical({'witness_id':wid,'workspace_id':value['workspace_id'],
                'observation_id':observation.id,'observation_hash':'sha256:'+sha(value),
                'kernel':value['kernel'],'state':'CLOSED_PRE_RUNTIME','execution_enabled':False,
                'release_enabled':False})
            witness=ClosedWorkingCopyWitness(wid,raw,observation)
            self._closed_witnesses[wid]=witness
            del self._issued[slot['binding']['workspace_id']]
            return witness

    def check_closed_witness(self,witness):
        self._owner_check()
        with self._lock:
            if (type(witness) is not ClosedWorkingCopyWitness or
                    not any(value is witness for value in self._closed_witnesses.values())):
                raise PermissionError('actual original working close witness required')
            return json.loads(witness.raw)

    def retire_closed_witness(self,witness):
        """Protected owner retires only AFTER durable completion, not refund."""
        with self._lock:
            self.check_closed_witness(witness)
            del self._closed_witnesses[witness.id]
