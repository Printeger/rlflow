"""Original, bounded SOURCE_ONLY fixture usage observations.

This owner runs only fixed finite CPU protocol fixtures. No caller Path/FD,
Task/Lease ID, provider URL, model prompt, Runtime grant or Budget settlement.
"""
from dataclasses import dataclass
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .hybrid_host_pool import HostPoolOwner
from . import hybrid_host_pool as pool_module
from .hybrid_fixture_materials import _write_new, _sync_directory
from .hybrid_runtime_boundary import _held_chain, directory_chain
from .hybrid_usage_fixture import SCENARIOS
from .hybrid_usage_stream import Accumulator, MAX_LINE, parse_line
from .hybrid_workspace_kernel import _private
from .jobs import identity
from .store import Conflict, canonical

POLL_BYTES = 65536
POLL_LINES = 128
POLL_NODES = 32768
MAX_FILE = 16 * 1024**2
SOURCE_FILES = {'read':'events.jsonl','write':'events.jsonl','stderr':'stderr.log','program':'program.py'}
_owners = {}
_registry = threading.RLock()
_fork_quarantine = []


@dataclass(frozen=True, eq=False)
class FixtureUsageSource:
    id: str
    raw: bytes


@dataclass(frozen=True, eq=False)
class SourceObservation:
    source: FixtureUsageSource
    raw: bytes


@dataclass(frozen=True, eq=False)
class _RuntimeStartedObservation:
    source: FixtureUsageSource
    raw: bytes


def _prepare_fork():
    _registry.acquire()
    for owner in _owners.values():
        owner._lock.acquire()
        for attempt in owner._attempts.values():
            if attempt.get('receiver_lock') is not None:attempt['receiver_lock'].acquire()


def _parent_fork():
    for owner in reversed(tuple(_owners.values())):
        for attempt in reversed(tuple(owner._attempts.values())):
            if attempt.get('receiver_lock') is not None:attempt['receiver_lock'].release()
        owner._lock.release()
    _registry.release()


def _child_fork():
    global _registry
    for owner in _owners.values():
        owner._live = False
        for attempt in owner._attempts.values():
            descriptors = set(fd for fd in attempt['fds'].values() if fd is not None)
            descriptors.update(owner._extra_fork_descriptors(attempt))
            process = attempt['producer']
            server=attempt.get('server')
            if server is not None:
                _fork_quarantine.append(server)
                if server.socket.fileno()>=0:descriptors.add(server.socket.fileno())
            accepted=attempt.get('accepted')
            if accepted is not None:
                connection,original=accepted;_fork_quarantine.append(connection)
                if original is not None and connection.fileno()>=0:
                    try:
                        info=os.fstat(connection.fileno())
                        if (info.st_dev,info.st_ino)==original:descriptors.add(connection.fileno())
                    except OSError:pass  # Independently retire other known FDs.
            if process is not None:
                _fork_quarantine.append(process)
                if process.stdin is not None and not process.stdin.closed: descriptors.add(process.stdin.fileno())
            for fd in descriptors:
                try: os.close(fd)
                except OSError: pass
            if attempt.get('receiver_lock') is not None:attempt['receiver_lock']=threading.RLock()
        owner._lock = threading.RLock()
    _owners.clear(); _registry = threading.RLock()


# ONE shared Pool->Source fork coordinator. Separate later before callbacks
# run first and would invert the normal Pool->Source startup lock order.
with pool_module._registry_lock:
    if 'fixture_usage' in pool_module._fork_extensions:
        raise Conflict('original fixture usage fork coordinator cannot be rebound')
    pool_module._fork_extensions['fixture_usage'] = (_prepare_fork, _parent_fork, _child_fork)


class FixtureUsageSourceOwner:
    """Protected local startup, fixed original managed application only."""
    def __init__(self, pool):
        if type(pool) is not HostPoolOwner: raise PermissionError('actual fixed host pool owner required')
        with pool._lock, _registry:
            pool._physical()
            if len(_owners) >= 32: raise Conflict('finite fixture usage owner bound exceeded')
            self.pool = pool; self.process = dict(pool.process)
            self._namespace = os.stat('/proc/thread-self/ns/mnt').st_ino
            self._lock = threading.RLock(); self._live = True
            self._attempts = {}; self._sources = {}; self._receipts = {}
            self.root = Path(tempfile.mkdtemp(prefix='usage-source-fixture-', dir=pool.application_root))
            self._chain = directory_chain(self.root)
            _sync_directory(pool.application_root)
            _owners[id(self)] = self

    def _actual(self):
        if not self._live or os.getpid() != self.process['pid'] or identity(os.getpid()) != self.process:
            raise PermissionError('actual original fixture usage owner process required')
        if os.stat('/proc/thread-self/ns/mnt').st_ino != self._namespace:
            raise Conflict('original fixture usage mount namespace changed')

    def _issued(self, source):
        self._actual()
        if type(source) is not FixtureUsageSource or self._sources.get(id(source), {}).get('source') is not source:
            raise PermissionError('actual original fixture usage source required')
        return self._sources[id(source)]

    def _physical(self, attempt):
        self._actual()
        if directory_chain(self.root) != self._chain:
            raise Conflict('original fixture usage namespace rebound')
        with _held_chain(attempt['path']) as (fds, chain):
            _private(fds[-1]); _private(fds[-2])
            if chain != attempt['chain']: raise Conflict('original fixture source ancestors rebound')
            for name in attempt['identities']:
                original = attempt['identities'][name]
                current = os.stat(name, dir_fd=fds[-1], follow_symlinks=False)
                if [current.st_dev, current.st_ino] != original:
                    raise Conflict('original fixture usage file replaced')
            for name, fd in attempt['fds'].items():
                if fd is None or name == 'pidfd': continue
                if name == 'binary':
                    self._check_binary(attempt); continue
                info = os.fstat(fd)
                file_name = self._source_file(name)
                original = attempt['identities'][file_name]
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                        stat.S_IMODE(info.st_mode) != 0o600 or [info.st_dev, info.st_ino] != original or
                        os.get_inheritable(fd) or (self._source_readonly(name) and flags & os.O_ACCMODE != os.O_RDONLY) or
                        (not self._source_readonly(name) and (flags & os.O_ACCMODE != os.O_WRONLY or not flags & os.O_APPEND))):
                    raise Conflict('original private fixture source descriptor differs')
        read_fd = attempt['fds']['read']
        if read_fd is None: raise Conflict('original fixture usage reader closed')
        info = os.fstat(read_fd)
        if info.st_size > MAX_FILE: raise Conflict('finite original usage file bound exceeded')
        return (info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _source_files(self):
        return SOURCE_FILES

    def _readonly_source_keys(self):
        return frozenset(('read','program','config','ready_read'))

    def _source_file(self,name):
        return self._source_files()[name]

    def _extra_fork_descriptors(self,attempt):
        return ()

    def _source_readonly(self,name):
        return name in self._readonly_source_keys()

    def _allocate(self, membership, claim, scenario, member):
        """Internal allocation only. Strong original attempt precedes file IO."""
        if len(self._attempts) >= 32: raise Conflict('finite fixture source capacity reached')
        attempt = {'source': None, 'claim': claim, 'membership': membership, 'scenario': scenario,
                   'producer': None, 'producer_identity': None, 'fds': {}, 'status': 'ALLOCATING',
                   'launch_entered': False, 'stdin_identity': None, 'pidfd_identity': None,
                   'offset': 0, 'seen': None, 'tail': b'', 'anchor': b'', 'hash': hashlib.sha256(),
                   'end': False, 'audit': None, 'receipt': None, 'partial_released': False,
                   'runtime': None, 'runtime_ack': None}
        self._attempts[id(claim)] = attempt
        path = Path(tempfile.mkdtemp(prefix='source-', dir=self.root)); attempt['path'] = path
        attempt['chain'] = directory_chain(path)
        for name in ('events.jsonl', 'stderr.log'): _write_new(path / name, b'')
        attempt['identities'] = {}
        with _held_chain(path) as (fds, _):
            for key, name, flags in (('read', 'events.jsonl', os.O_RDONLY | os.O_NONBLOCK),
                                      ('write', 'events.jsonl', os.O_WRONLY | os.O_APPEND),
                                      ('stderr', 'stderr.log', os.O_WRONLY | os.O_APPEND)):
                fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
                attempt['fds'][key] = fd; info = os.fstat(fd)
                attempt['identities'][name] = [info.st_dev, info.st_ino]
        source_id = 'fixture_source_' + uuid.uuid4().hex
        binding = {'source_id': source_id, 'project_id': member['payload']['project_id'],
            'store_epoch': member['payload']['store_epoch'], 'member_hash': hashlib.sha256(membership.raw).hexdigest(),
            'pool_claim_hash': hashlib.sha256(claim.raw).hexdigest(), 'scenario': scenario,
            'owner': self.process, 'file_identity': attempt['identities']['events.jsonl'],
            'data_mode': 'fixture', 'source_only': True, 'settlement_enabled': False}
        source = FixtureUsageSource(source_id, canonical(binding)); attempt['source'] = source
        self._sources[id(source)] = attempt
        attempt['accumulator'] = Accumulator('per_turn' if scenario == 'per_turn' else 'cumulative')
        return attempt

    def start_fixture(self, membership, claim, scenario='cumulative'):
        """One original finite fixture producer per original claim, never a model."""
        self._actual(); member = self.pool._issued_member(membership); claimed = self.pool._issued_claim(claim)
        if claimed['payload']['member_id'] != member['payload']['member_id']:
            raise PermissionError('original fixture source membership/claim differs')
        if type(scenario) is not str or scenario not in SCENARIOS: raise Conflict('fixed finite fixture scenario required')
        # Pool -> source owner. No source operation takes Pool lock in reverse.
        with self.pool._lock, self._lock:
            previous = self._attempts.get(id(claim))
            if previous is not None:
                if previous['scenario'] != scenario or previous['membership'] is not membership:
                    raise Conflict('original fixture source attempt request differs')
                if previous['source'] is None: raise Conflict('original source allocation uncertain; no repeat launch')
                return previous['source']
            if self.pool.check(claim)['state'] != 'CLAIM': raise Conflict('fixture source requires original unclosed claim')
            try:
                attempt = self._allocate(membership, claim, scenario, member)
                source = attempt['source']
                self._physical(attempt)
                self.pool._claim_slots[id(claim)].check(); self.pool._claim_clocks(claimed)
                attempt['status'] = 'START_UNKNOWN'
                attempt['launch_entered'] = True
                process = subprocess.Popen([sys.executable, '-B', '-I', str(Path(__file__).with_name('hybrid_usage_fixture.py')),
                    str(self.process['pid']), scenario], stdin=subprocess.PIPE,
                    stdout=attempt['fds']['write'], stderr=attempt['fds']['stderr'],
                    env={'PATH': '/usr/bin:/bin'}, close_fds=True, start_new_session=True)
                attempt['producer'] = process
                pipe_info = os.fstat(process.stdin.fileno())
                attempt['stdin_identity'] = [pipe_info.st_dev, pipe_info.st_ino]
                attempt['producer_identity'] = identity(process.pid)
                if attempt['producer_identity'] is None or attempt['producer_identity']['pgid'] != process.pid:
                    raise Conflict('original actual fixture producer identity unavailable')
                attempt['fds']['pidfd'] = os.pidfd_open(process.pid, 0)
                pin = os.fstat(attempt['fds']['pidfd']); attempt['pidfd_identity'] = [pin.st_dev, pin.st_ino]
                process.stdin.write(b'R'); process.stdin.flush()
                attempt['status'] = 'READING'
                return source
            except BaseException:
                retained = self._attempts.get(id(claim))
                if retained is not None: retained['status'] = 'UNKNOWN'
                raise

    def _runtime_allocate(self, owner, lease):
        """Only the exact bound Runtime's original attempt can allocate."""
        from .hybrid_fixture_runtime import FixtureRuntimeOwner
        from .hybrid_native_diagnostic import NativeDiagnosticOwner
        from .hybrid_native_diagnostic_source import NativeDiagnosticSourceOwner
        from .hybrid_native_model_runtime import NativeModelOwner
        from .hybrid_native_model_source import NativeModelSourceOwner
        if (type(owner),type(self)) not in ((FixtureRuntimeOwner,FixtureUsageSourceOwner),(NativeDiagnosticOwner,NativeDiagnosticSourceOwner),(NativeModelOwner,NativeModelSourceOwner)) or owner.sources is not self:
            raise PermissionError('fixed original fixture Runtime source binding required')
        runtime = owner._issued(lease); claim = runtime['claim']
        with self._lock:
            old = self._attempts.get(id(claim))
            if old is not None:
                if old.get('runtime') is not runtime or old['source'] is None:
                    raise Conflict('original runtime source allocation uncertain; no reallocation')
                return old['source']
            member = self.pool._issued_member(owner.membership)
            try:
                attempt = self._allocate(owner.membership, claim, 'runtime.' + runtime['scenario'], member)
                attempt['runtime'] = runtime
                program_raw=(owner._engineering_grants[id(runtime['engineering_grant'])]['program_raw']
                    if runtime.get('engineering_grant') is not None else owner.program_raw)
                _write_new(attempt['path'] / 'program.py', program_raw)
                fd = os.open(attempt['path'] / 'program.py', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                attempt['fds']['program'] = fd; info = os.fstat(fd)
                attempt['identities']['program.py'] = [info.st_dev, info.st_ino]
                attempt['status'] = 'ALLOCATED_NO_HANDOFF'; self._physical(attempt)
                return attempt['source']
            except BaseException:
                retained = self._attempts.get(id(claim))
                if retained is not None: retained['status'] = 'UNKNOWN'
                raise

    def _runtime_spawn(self, owner, lease):
        runtime = owner._issued(lease); attempt = self._issued(runtime['source'])
        with self._lock:
            if owner.sources is not self or attempt['runtime'] is not runtime:
                raise PermissionError('actual original runtime producer source required')
            if attempt['launch_entered']: return attempt['producer_identity']
            self._physical(attempt)
            if hashlib.sha256(os.pread(attempt['fds']['program'], 16385, 0)).hexdigest() != runtime['origin']['program_sha256'].removeprefix('sha256:'):
                raise Conflict('fixed original CPU program changed before handoff')
            extra=() if runtime.get('engineering_grant') is None else (owner._engineering_input(runtime),)
            native = runtime.get('diagnostic_grant') is not None or runtime.get('native_model_grant') is not None
            if native:
                extra=self._native_spawn_material(owner,attempt)
            owner._check_spawn_gate(runtime)
            attempt['launch_entered'] = True; attempt['status'] = 'START_UNKNOWN'
            runtime['spawn_entered'] = True; runtime['spawn_monotonic'] = time.monotonic()
            try:
                process = subprocess.Popen([sys.executable, '-B', '-I', '-S', '/proc/self/fd/' + str(attempt['fds']['program']),
                    str(self.process['pid']), runtime['origin']['nonce'], runtime['scenario'],*[str(fd) for fd in extra]], stdin=subprocess.PIPE,
                    stdout=attempt['fds']['write'], stderr=attempt['fds']['stderr'],
                    env={'PATH': '/usr/bin:/bin'}, close_fds=True, pass_fds=(attempt['fds']['program'],*extra), start_new_session=True)
                attempt['producer'] = process
                try:
                    from .hybrid_kernel_usage import _KernelUsageCapture
                    attempt['kernel_usage'] = _KernelUsageCapture(process)
                except Exception:
                    # Missing passive OS observations never block original cleanup.
                    attempt['kernel_usage'] = None
                pipe = os.fstat(process.stdin.fileno()); attempt['stdin_identity'] = [pipe.st_dev, pipe.st_ino]
                attempt['producer_identity'] = identity(process.pid)
                if attempt['producer_identity'] is None or attempt['producer_identity']['pgid'] != process.pid:
                    raise Conflict('actual original gated fixture process identity unavailable')
                attempt['fds']['pidfd'] = os.pidfd_open(process.pid, 0)
                pin = os.fstat(attempt['fds']['pidfd']); attempt['pidfd_identity'] = [pin.st_dev, pin.st_ino]
                attempt['status'] = 'READING'
                if native:self._wait_ready(owner,attempt)
                return attempt['producer_identity']
            except BaseException:
                attempt['status'] = 'UNKNOWN'; raise

    def _runtime_release(self, owner, lease):
        runtime = owner._issued(lease); attempt = self._issued(runtime['source'])
        with self._lock:
            if owner.sources is not self or attempt['runtime'] is not runtime:
                raise PermissionError('actual original runtime release source required')
            if runtime['release_entered']: return
            self._physical(attempt); self._check_pidfd(attempt, live=True)
            pipe = os.fstat(attempt['producer'].stdin.fileno())
            if [pipe.st_dev, pipe.st_ino] != attempt['stdin_identity']:
                raise Conflict('original gated fixture pipe changed')
            owner._check_release_gate(runtime)
            runtime['release_entered'] = True  # Lost send outcome must NEVER resend.
            attempt['producer'].stdin.write(b'G'); attempt['producer'].stdin.flush()

    def _runtime_started(self, owner, lease):
        runtime = owner._issued(lease); attempt = self._issued(runtime['source'])
        if owner.sources is not self or attempt['runtime'] is not runtime:
            raise PermissionError('actual original runtime observation required')
        return attempt['runtime_ack']

    def _observation(self, attempt):
        accumulator = attempt.get('accumulator')
        totals = (accumulator.totals(inclusive_parent='fixture_parent' if attempt['scenario'] == 'parent_inclusive' else None)
                  if accumulator is not None else dict.fromkeys(('input_tokens', 'output_tokens', 'cached_tokens')))
        totals['complete'] = attempt['status'] == 'SEALED' and totals.get('complete', False)
        value = {'source_id': attempt['source'].id, 'data_mode': 'fixture', 'source_only': True,
                 'source_status': attempt['status'], 'offset': attempt['offset'],
                 'observed_prefix_sha256': attempt['hash'].hexdigest(), 'usage': totals,
                 'actual_cost_status': 'UNKNOWN', 'actual_cost': None, 'estimated_cost': None,
                 'execution_enabled': False, 'settlement_enabled': False}
        raw = canonical(value); original = attempt['receipt']
        if original is None or original.raw != raw:
            original = SourceObservation(attempt['source'], raw); attempt['receipt'] = original
            self._receipts[id(original)] = original
            # At most one latest source-only receipt per source; no unbounded history.
            if len(self._receipts) > 32:
                live = {id(item['receipt']) for item in self._attempts.values() if item['receipt'] is not None}
                self._receipts = {key: item for key, item in self._receipts.items() if key in live}
        return original

    def poll(self, source):
        attempt = self._issued(source)
        with self._lock:
            if attempt['status'] == 'CLOSED' and attempt['receipt'] is not None: return attempt['receipt']
            if attempt['status'] in ('UNKNOWN', 'QUARANTINED', 'CLOSED'): return self._observation(attempt)
            aggregate = attempt['accumulator']
            checkpoint = (copy.deepcopy(aggregate.sources), copy.deepcopy(aggregate.aggregate),
                          dict(aggregate.active), set(aggregate.threads), aggregate.failed, len(aggregate.rows))
            try:
                stamp = self._physical(attempt); old = attempt['seen']; fd = attempt['fds']['read']
                if old is not None and (stamp[0] < old[0] or stamp[0] == old[0] and stamp != old):
                    raise Conflict('original usage source truncated or changed without append')
                if attempt['anchor'] and os.pread(fd, len(attempt['anchor']), attempt['offset'] - len(attempt['anchor'])) != attempt['anchor']:
                    raise Conflict('original usage prefix tip changed')
                if attempt['tail'] and os.pread(fd, len(attempt['tail']), attempt['offset']) != attempt['tail']:
                    raise Conflict('original partial usage tail changed')
                if attempt['status'] == 'SEALED':
                    if stamp != old: raise Conflict('sealed original usage source changed')
                    return self._observation(attempt)
                remaining = POLL_BYTES - len(attempt['anchor']) - len(attempt['tail'])
                raw = os.pread(fd, remaining, attempt['offset']); cursor = 0; lines = 0; node_budget = [POLL_NODES]
                ended = attempt['end']; runtime_ack = attempt['runtime_ack']
                while lines < POLL_LINES:
                    newline = raw.find(b'\n', cursor)
                    if newline < 0: break
                    line = raw[cursor:newline + 1]
                    if ended: raise Conflict('original fixture usage appended after end')
                    event = parse_line(line, node_budget=node_budget)
                    if event['type'] == 'runtime.started' and attempt['runtime'] is not None:
                        runtime = attempt['runtime']
                        expected = {'type': 'runtime.started', 'nonce': runtime['origin']['nonce'],
                                    'pid': attempt['producer_identity']['pid'],
                                    'program': 'FIXED_CPU_ADD_PATCH_V1' if runtime['scenario']=='engineering_patch' else 'FIXED_CPU_PI_TRIAL_V1' if runtime['scenario'] == 'cpu_trial' else 'FIXED_CPU_PROTOCOL_V1'}
                        if event != expected or runtime_ack is not None or not runtime['release_entered']:
                            raise Conflict('original gated fixture started ACK differs')
                        runtime_ack = _RuntimeStartedObservation(source, canonical({'source_id': source.id,
                            'event': event, 'offset': attempt['offset'] + cursor, 'line_sha256': hashlib.sha256(line).hexdigest(),
                            'lease_sha256': hashlib.sha256(runtime['lease'].raw).hexdigest()}))
                    elif event['type'] == 'fixture.end': ended = True
                    else: aggregate.accept(source.id, attempt['offset'] + cursor, line, _parsed=event,
                        _allowed_threads=frozenset(('fixture_parent', 'fixture_child'))
                        if attempt['scenario'] == 'parent_inclusive' else None)
                    cursor = newline + 1; lines += 1
                remainder = raw[cursor:]
                if b'\n' not in remainder and len(remainder) > MAX_LINE:
                    raise Conflict('original usage partial line exceeds finite bound')
                final_stamp = self._physical(attempt)
                if final_stamp[0] < stamp[0] or final_stamp[0] == stamp[0] and final_stamp != stamp:
                    raise Conflict('original usage changed during observation')
                attempt['hash'].update(raw[:cursor]); attempt['offset'] += cursor
                attempt['anchor'] = (attempt['anchor'] + raw[:cursor])[-MAX_LINE:]
                attempt['tail'] = remainder if b'\n' not in remainder else b''
                attempt['accumulator'] = aggregate; attempt['end'] = ended; attempt['seen'] = final_stamp
                attempt['runtime_ack'] = runtime_ack
                if attempt['producer'] is None or attempt['producer_identity'] is None:
                    attempt['status'] = 'UNKNOWN'
                elif attempt['producer'].poll() is not None:
                    if attempt['producer'].returncode != 0: attempt['status'] = 'UNKNOWN'
                    elif ended and attempt['offset'] == final_stamp[0] and not attempt['tail']:
                        attempt['status'] = 'AUDITING'
                return self._observation(attempt)
            except (OSError, Conflict, PermissionError):
                aggregate.sources, aggregate.aggregate, aggregate.active, aggregate.threads, aggregate.failed, old_size = checkpoint
                while len(aggregate.rows) > old_size: aggregate.rows.popitem()
                attempt['status'] = 'QUARANTINED'
                raise

    def seal(self, source):
        """ONE bounded audit step, not an unbounded read-to-EOF or wait."""
        attempt = self._issued(source)
        with self._lock:
            if attempt['status'] != 'AUDITING': return self.poll(source)
            observation = self._observation(attempt)
            if attempt['status'] != 'AUDITING': return observation
            try:
                stamp = self._physical(attempt)
                audit = attempt['audit']
                if audit is None:
                    audit = {'stamp': stamp, 'offset': 0, 'hash': hashlib.sha256()}; attempt['audit'] = audit
                if stamp != audit['stamp']: raise Conflict('original final usage audit source changed')
                block = os.pread(attempt['fds']['read'], min(POLL_BYTES, stamp[0] - audit['offset']), audit['offset'])
                audit['hash'].update(block); audit['offset'] += len(block)
                if self._physical(attempt) != stamp: raise Conflict('original usage source changed during final audit')
                if audit['offset'] == stamp[0]:
                    if audit['hash'].hexdigest() != attempt['hash'].hexdigest():
                        raise Conflict('original earlier usage prefix rewritten')
                    attempt['status'] = 'SEALED'
                return self._observation(attempt)
            except (OSError, Conflict, PermissionError):
                attempt['status'] = 'QUARANTINED'
                raise

    def finish_partial_fixture(self, source):
        attempt = self._issued(source)
        with self._lock:
            if attempt['scenario'] == 'partial' and attempt['partial_released']: return
            if attempt['scenario'] != 'partial' or not attempt['tail'] or attempt['producer'] is None:
                raise Conflict('actual observed partial fixture source required')
            if identity(attempt['producer'].pid) != attempt['producer_identity']:
                raise Conflict('original partial fixture producer no longer live')
            info = os.fstat(attempt['producer'].stdin.fileno())
            if [info.st_dev, info.st_ino] != attempt['stdin_identity']:
                raise Conflict('original partial fixture pipe changed')
            attempt['producer'].stdin.write(b'C'); attempt['producer'].stdin.flush()
            attempt['partial_released'] = True

    def _check_pidfd(self, attempt, *, live):
        fd = attempt['fds'].get('pidfd')
        if fd is None: raise Conflict('original fixture pidfd missing')
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != attempt['pidfd_identity'] or os.get_inheritable(fd):
            raise Conflict('original fixture pidfd changed')
        if live:
            item = os.open('/proc/self/fdinfo/' + str(fd), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            try: raw = os.read(item, 4097)
            finally: os.close(item)
            if len(raw) > 4096 or ('Pid:\t' + str(attempt['producer_identity']['pid']) + '\n').encode() not in raw:
                raise Conflict('original fixture pidfd target differs')

    def _signal_original(self, attempt, sig):
        """Signal only the pinned live child; an original reap resolves exit races."""
        process = attempt['producer']
        if process.poll() is not None: return
        if identity(process.pid) != attempt['producer_identity']:
            if process.poll() is not None: return
            raise Conflict('original fixture cleanup identity uncertain')
        try:
            self._check_pidfd(attempt, live=True)
            signal.pidfd_send_signal(attempt['fds']['pidfd'], sig)
        except (Conflict, ProcessLookupError):
            if process.poll() is None: raise

    def _cleanup_attempt(self, attempt):
        """Also reaches known pre-Popen partial allocations without source caps."""
        process = attempt['producer']
        if process is not None and process.poll() is None:
            try: self._signal_original(attempt, signal.SIGKILL)
            except (Conflict, OSError):
                attempt['status'] = 'UNKNOWN'; raise
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                attempt['status'] = 'UNKNOWN'; raise Conflict('finite original fixture cleanup incomplete') from None
        unknown_start = process is None and attempt['launch_entered']
        errors = []
        for name, fd in tuple(attempt['fds'].items()):
            if fd is None: continue
            try:
                if name == 'pidfd': self._check_pidfd(attempt, live=False)
                else:
                    if name == 'binary':self._check_binary(attempt)
                    else:
                        info = os.fstat(fd); key = self._source_file(name)
                        if [info.st_dev, info.st_ino] != attempt['identities'].get(key):
                            raise Conflict('original fixture cleanup descriptor reused')
                os.close(fd); attempt['fds'][name] = None
            except (OSError, Conflict) as error: errors.append(error)
        if process is not None and process.stdin is not None and not process.stdin.closed:
            try:
                info = os.fstat(process.stdin.fileno())
                if [info.st_dev, info.st_ino] != attempt['stdin_identity']:
                    raise Conflict('original fixture cleanup pipe reused')
                try: process.stdin.close()
                except BrokenPipeError:
                    # Buffered close can report the already-dead reader while
                    # successfully closing the original verified descriptor.
                    if not process.stdin.closed: raise
            except (OSError, Conflict) as error: errors.append(error)
        if errors:
            attempt['status'] = 'UNKNOWN'; raise Conflict('original fixture partial cleanup retained') from errors[0]
        if unknown_start:
            # Parent descriptors can be safely closed by their original inode
            # identities even when no child identity was returned. That is NOT
            # proof of participant termination or a refundable no-handoff.
            attempt['status'] = 'UNKNOWN'
            raise Conflict('original fixture startup outcome unknown; no process adoption')
        attempt['status'] = 'CLOSED'

    def stop_fixture(self, source):
        """Cleanup only, not Runtime STOPPED or any pool/budget refund."""
        attempt = self._issued(source)
        with self._lock:
            self._cleanup_attempt(attempt)
            return {'closed': True, 'runtime_stopped': False, 'settlement_enabled': False}

    def shutdown(self):
        self._actual()
        with _registry, self._lock:
            for attempt in self._attempts.values():
                self._cleanup_attempt(attempt)
            self._live = False; _owners.pop(id(self), None)

    def shutdown_safety(self):
        """Retire original parent FD owner, never prove unknown children stopped."""
        self._actual()
        unknown = False
        with _registry, self._lock:
            errors=[]
            for attempt in self._attempts.values():
                try: self._cleanup_attempt(attempt)
                except Conflict as exc:
                    if (attempt['producer'] is not None or attempt['producer_identity'] is not None or
                            not attempt['launch_entered'] or attempt['status'] != 'UNKNOWN' or
                            any(fd is not None for fd in attempt['fds'].values())):
                        errors.append(exc)
                    else:unknown = True
                except BaseException as exc:errors.append(exc)
            if errors:raise errors[0]
            self._live = False; _owners.pop(id(self), None)
        return {'state': 'PARENT_FDS_CLOSED_EXPOSURE_UNKNOWN' if unknown else 'ORIGINAL_PARENT_FDS_CLOSED',
                'runtime_stopped': False, 'settlement_enabled': False}
