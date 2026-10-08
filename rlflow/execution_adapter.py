"""Private exec preparation, never execution authority.

No HTTP route, Store transition, worker or release. Seals are in-memory and are
not reconstructed from manifests. Persistent source-bound preparation/admission
must be implemented separately before this can participate in Hybrid execution.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading

from . import isolation
from .contracts import role_schema, ROLES
from .hybrid_protocol import obj, ID, HASH, enum, validate_schema, ProtocolError
from .hybrid_registry import Registry
from .role_config import load_role
from .store import canonical, sha, atomic, Conflict

PROFILE = obj({'adapter': {'const': 'codex-exec'}, 'model': ID,
    'effort': enum('low', 'medium', 'high', 'xhigh', 'max'),
    'codex_version': {'const': isolation.PINNED_VERSION}, 'native_subagents': {'const': False},
    'cpu_network': {'const': 'none'},
    'memory_bytes': {'type': 'integer', 'minimum': 64*1024**2, 'maximum': 16*1024**3},
    'command_seconds': {'type': 'integer', 'minimum': 1, 'maximum': 3600}})
PACKET = obj({'schema_version': {'const': '1.0'}, 'project_id': ID,
    'data_mode': enum('live', 'fixture'), 'store_epoch': ID, 'goal_id': ID,
    'contract_revision': {'type': 'integer', 'minimum': 1, 'maximum': 2**63-1},
    'proposal_hash': HASH, 'approval_key': ID, 'candidate_snapshot_hash': HASH,
    'role': enum(*ROLES), 'context': obj({'text': {'type': 'string', 'maxLength': 200000}})})
MAX_ARTIFACT_BYTES = 16*1024**2
FILES = ('packet.json', 'result.schema.json', 'command-plan.json',
         'control/result.json.models.json', 'control/result.json.mcp.json')


def _digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise Conflict('duplicate preparation JSON key')
            result[key] = value
        return result
    def constant(value): raise Conflict('nonfinite preparation JSON number')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > 64: raise Conflict('preparation JSON exceeds depth bound')
            if isinstance(item, float) and not math.isfinite(item): constant(item)
            if isinstance(item, dict): stack.extend((v, depth+1) for v in item.values())
            elif isinstance(item, list): stack.extend((v, depth+1) for v in item)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Conflict('invalid preparation JSON') from error


@dataclass(frozen=True, eq=False)
class PreparationPlan:
    id: str
    raw: bytes


class CodexExecAdapter:
    def __init__(self, registry, control_root):
        if type(registry) is not Registry: raise TypeError('protected immutable Registry required')
        self.registry = registry
        config = json.loads(registry._raw)
        validate_schema(PROFILE, config['runtime_profile'])
        profile = config['runtime_profile']
        if type(profile['memory_bytes']) is not int or type(profile['command_seconds']) is not int:
            raise ProtocolError('actual integer adapter limits required')
        self._profile = canonical(profile)
        self._scope = (config['project_id'], config['data_mode'])
        self.root = self._path(control_root)
        self._root_identity = self._directory(self.root, private=True)
        self._plans = {}; self._seals = {}; self._lock = threading.RLock()

    @staticmethod
    def _path(path):
        try:
            path = Path(path).absolute()
            resolved = path.resolve(strict=True)
        except (OSError, ValueError, RuntimeError) as error:
            raise Conflict('adapter path unavailable') from error
        if '\x00' in str(path) or resolved != path:
            raise Conflict('canonical nonsymlink adapter path required')
        return path

    @staticmethod
    def _directory(path, *, private=False):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or
                (private and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise Conflict('owned private adapter directory required' if private else 'adapter directory required')
        return [info.st_dev, info.st_ino]

    def _root(self):
        if self._path(self.root) != self.root or self._directory(self.root, private=True) != self._root_identity:
            raise Conflict('adapter root changed')

    @contextmanager
    def _guard(self):
        # Nonblocking directory flock coordinates separate adapter instances.
        with self._lock:
            self._root()
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                info = os.fstat(fd)
                if [info.st_dev, info.st_ino] != self._root_identity: raise Conflict('adapter root changed')
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError: raise Conflict('adapter preparation busy') from None
                yield
                self._root()
            finally: os.close(fd)

    def _paths(self, candidate, write_roots, role):
        if type(write_roots) not in (list, tuple) or len(write_roots) > 128:
            raise Conflict('bounded concrete preparation write roots required')
        candidate = self._path(candidate); self._directory(candidate)
        writes = [self._path(p) for p in write_roots]
        if (role == 'Engineer' and not writes) or (role != 'Engineer' and writes):
            raise Conflict('explicit role-specific preparation write roots required')
        if len(set(writes)) != len(writes): raise Conflict('invalid preparation write roots')
        for path in [candidate, *writes]:
            if path == self.root or path in self.root.parents or self.root in path.parents:
                raise Conflict('preparation control and candidate overlap')
            self._directory(path)
        if any(p != candidate and candidate not in p.parents for p in writes):
            raise Conflict('preparation writes outside candidate')
        return {'candidate': {'path': str(candidate), 'identity': self._directory(candidate)},
                'writes': [{'path': str(p), 'identity': self._directory(p)} for p in writes]}

    def plan_preparation(self, packet, *, candidate, write_roots=()):
        try: raw = canonical(packet)
        except (ValueError, TypeError, RecursionError) as error:
            raise ProtocolError('invalid preparation packet') from error
        if len(raw) > 256*1024: raise ProtocolError('preparation packet exceeds bound')
        packet = _parse(raw); validate_schema(PACKET, packet)
        if type(packet['contract_revision']) is not int: raise ProtocolError('actual preparation revision required')
        if (packet['project_id'], packet['data_mode']) != self._scope:
            raise Conflict('preparation scope differs from protected Registry')
        role = load_role(packet['role']); schema = role_schema(packet['role'])
        with self._guard():
            paths = self._paths(candidate, write_roots, packet['role'])
            value = {'schema_version': '1.0', 'adapter': 'codex-exec', 'packet': packet,
                'profile': json.loads(self._profile), 'paths': paths,
                'config_hash': self.registry.config_hash, 'role_definition': role, 'result_schema': schema,
                'gates': dict.fromkeys(('source_authority', 'model_access', 'actual_data', 'os_resources',
                    'controller_lease', 'writer_lease', 'budget_reservation', 'stop_recovery'), 'UNVERIFIED'),
                'execution_enabled': False}
            encoded = canonical(value); key = 'preparation_' + sha(value)
            if key in self._plans: return self._plans[key]
            if len(self._plans) >= 128: raise Conflict('preparation plan capacity reached')
            plan = PreparationPlan(key, encoded); self._plans[key] = plan
            return plan

    def _issued(self, plan):
        if type(plan) is not PreparationPlan or self._plans.get(plan.id) is not plan:
            raise PermissionError('actual adapter-issued preparation plan required')
        value = _parse(plan.raw)
        if plan.id != 'preparation_'+sha(value) or value['config_hash'] != self.registry.config_hash:
            raise Conflict('preparation plan binding changed')
        paths = value['paths']
        if self._paths(paths['candidate']['path'], [p['path'] for p in paths['writes']], value['packet']['role']) != paths:
            raise Conflict('preparation workspace identity changed')
        return value

    @staticmethod
    def _read(path, remaining):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                    or info.st_nlink != 1 or info.st_size > remaining):
                raise Conflict('preparation artifact unavailable')
            blocks = []; size = 0
            while block := os.read(fd, min(65536, remaining+1-size)):
                size += len(block)
                if size > remaining: raise Conflict('preparation artifacts exceed bound')
                blocks.append(block)
            return b''.join(blocks)
        finally: os.close(fd)

    def _verify(self, plan):
        value = self._issued(plan); directory = self.root/plan.id
        seal = self._seals.get(plan.id)
        if seal is None: raise Conflict('preparation has no actual seal; restart requires persistent service')
        for name, identity in seal['directories'].items():
            if self._directory(directory/name, private=True) != identity: raise Conflict('preparation directory changed')
        remaining = MAX_ARTIFACT_BYTES
        raw = self._read(directory/'manifest.json', remaining); remaining -= len(raw)
        if _digest(raw) != seal['manifest_hash']: raise Conflict('preparation manifest changed')
        manifest = _parse(raw)
        if manifest != seal['manifest']: raise Conflict('preparation manifest differs')
        contents = {}
        for name, digest in manifest['files'].items():
            data = self._read(directory/name, remaining); remaining -= len(data)
            if digest != _digest(data): raise Conflict('preparation artifact changed')
            contents[name] = data
        if (_parse(contents['packet.json']) != value['packet'] or
                _parse(contents['result.schema.json']) != value['result_schema']):
            raise Conflict('preparation input or result schema differs')
        return {'preparation_id': plan.id, 'plan_hash': manifest['plan_hash'],
                'manifest_hash': seal['manifest_hash'], 'execution_enabled': False}

    def verify_materialization(self, plan):
        with self._guard(): return self._verify(plan)

    def materialize_preparation(self, plan):
        with self._guard():
            value = self._issued(plan); destination = self.root/plan.id
            if destination.exists() or destination.is_symlink(): return self._verify(plan)
            temporary = Path(tempfile.mkdtemp(prefix='.preparing-', dir=self.root))
            temporary_identity = self._directory(temporary, private=True); published = False
            try:
                (temporary/'control').mkdir(mode=0o700); (temporary/'scratch').mkdir(mode=0o700)
                atomic(temporary/'packet.json', canonical(value['packet']))
                atomic(temporary/'result.schema.json', canonical(value['result_schema']))
                profile = value['profile']; paths = value['paths']
                # Reuse native-tool masking/MCP policy. Only --version may run;
                # the helper does not execute argv or contact the model provider.
                argv, environment = isolation.codex_command(value['packet']['role'], paths['candidate']['path'],
                    temporary/'scratch', temporary/'result.schema.json', temporary/'control'/'result.json',
                    write_roots=[p['path'] for p in paths['writes']] or None,
                    memory_bytes=profile['memory_bytes'], command_seconds=profile['command_seconds'],
                    model=profile['model'], effort=profile['effort'])
                del environment  # Never serialize authentication environment.
                def moved(v):
                    if isinstance(v, str):
                        prefix = str(temporary)
                        return str(destination)+v[len(prefix):] if v == prefix or v.startswith(prefix+'/') else v
                    if isinstance(v, dict): return {k: moved(x) for k, x in v.items()}
                    if isinstance(v, list): return [moved(x) for x in v]
                    return v
                rewritten = []; index = 0
                while index < len(argv):
                    if argv[index] == '-c':
                        key, encoded = argv[index+1].split('=', 1)
                        rewritten.extend(['-c', key+'='+json.dumps(moved(_parse(encoded)), separators=(',', ':'))])
                        index += 2
                    else: rewritten.append(moved(argv[index])); index += 1
                config_path = temporary/'control'/'result.json.mcp.json'; config_path.chmod(0o600)
                atomic(config_path, canonical(moved(_parse(self._read(config_path, MAX_ARTIFACT_BYTES)))))
                atomic(temporary/'command-plan.json', canonical({'argv': rewritten,
                    'execution_enabled': False, 'state': 'PREPARATION_ONLY'}))
                files = {}; total = 0
                for name in FILES:
                    path = temporary/name; path.chmod(0o600)
                    data = self._read(path, MAX_ARTIFACT_BYTES-total); total += len(data); files[name] = _digest(data)
                manifest = {'plan_hash': _digest(plan.raw), 'files': files, 'execution_enabled': False}
                raw = canonical(manifest)
                if total+len(raw) > MAX_ARTIFACT_BYTES: raise Conflict('preparation artifacts exceed bound')
                atomic(temporary/'manifest.json', raw); (temporary/'manifest.json').chmod(0o600)
                directories = {name: self._directory(temporary/name, private=True) for name in ('', 'control', 'scratch')}
                self._issued(plan); self._root()
                if destination.exists() or destination.is_symlink(): raise Conflict('preparation destination appeared')
                os.rename(temporary, destination); published = True
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                try: os.fsync(fd)
                finally: os.close(fd)
                self._seals[plan.id] = {'manifest_hash': _digest(raw), 'manifest': manifest, 'directories': directories}
                return self._verify(plan)
            finally:
                # Remove only this call's own unpublished staging directory.
                # Published or unknown directories are never overwritten.
                if not published and temporary.exists():
                    self._root()
                    if self._directory(temporary, private=True) != temporary_identity:
                        raise Conflict('preparation staging directory changed')
                    shutil.rmtree(temporary)

    def start(self, *args, **kwargs):
        raise PermissionError('Hybrid source, controller/writer lease, budget and STOP release gates unavailable')
