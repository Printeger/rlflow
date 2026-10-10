"""Original frozen generating packet FDs; no model launch qualification yet."""
import hashlib
import json
import os
import stat

from .hybrid_fixture_materials import _write_new
from .hybrid_usage_source import FixtureUsageSourceOwner, FixtureUsageSource, SOURCE_FILES
from .store import Conflict, canonical


class NativeModelSourceOwner(FixtureUsageSourceOwner):
    def __init__(self, pool):
        self._model_bindings = {}
        self._packet_readers = {}
        self._packet_failures = set()
        super().__init__(pool)

    def _actual(self):
        from . import hybrid_usage_source
        if type(self) is not NativeModelSourceOwner or hybrid_usage_source._owners.get(id(self)) is not self:
            raise PermissionError('exact original generating source owner required')
        super()._actual()

    def _source_files(self):
        return {**SOURCE_FILES, 'packet':'packet.json', 'schema':'output.schema.json'}

    def _readonly_source_keys(self):
        return super()._readonly_source_keys() | {'packet','schema'}

    def start_fixture(self, *args, **kwargs):raise PermissionError('generating source cannot run fixture')
    def _runtime_spawn(self, *args, **kwargs):raise PermissionError('native generating launch unqualified')
    def _runtime_release(self, *args, **kwargs):raise PermissionError('native generating release unqualified')

    def _runtime_allocate(self, owner, lease):
        from .hybrid_native_model_runtime import NativeModelOwner
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original same-owner generating source required')
        source = super()._runtime_allocate(owner, lease); attempt = self._issued(source)
        with self._lock:
            if attempt.get('model_allocated'):return source
            if attempt.get('model_allocation_entered'):
                raise Conflict('original generating source allocation UNKNOWN; no replacement')
            attempt['model_allocation_entered'] = True
            runtime = owner._issued(lease)
            row = owner._issued_native_model_grant(runtime['native_model_grant'], runtime['bundle'],
                                                  runtime['token'], runtime['observation'])
            try:
                attempt['model_raw'] = {'packet':row['packet_raw'], 'schema':row['schema_raw']}
                for key,raw in attempt['model_raw'].items():
                    name = self._source_file(key); _write_new(attempt['path']/name, raw)
                    fd = os.open(attempt['path']/name, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
                    attempt['fds'][key] = fd; info = os.fstat(fd)
                    attempt['identities'][name] = [info.st_dev,info.st_ino]
                    if not stat.S_ISREG(info.st_mode) or info.st_size != len(raw):
                        raise Conflict('original regular generating material required')
                binding = json.loads(source.raw)
                binding['native_model'] = json.loads(runtime['native_model_grant'].raw)
                binding['execution_qualified'] = False
                original = FixtureUsageSource(source.id, canonical(binding))
                self._sources.pop(id(source)); attempt['source'] = original; self._sources[id(original)] = attempt
                self._model_bindings[id(original)] = (original, original.raw, owner, lease,
                    runtime['native_model_grant'], runtime['native_model_grant'].raw,
                    row['packet_raw'], row['schema_raw'])
                attempt['model_allocated'] = True; self._physical(attempt)
                from .hybrid_native_packet_reader import _HeldPacketReader
                self._packet_readers[id(original)] = _HeldPacketReader(attempt['fds']['read'],
                    role=binding['native_model']['role'],
                    candidate_sha256=binding['native_model']['candidate_sha256'])
                return original
            except BaseException:
                attempt['status'] = 'UNKNOWN'; raise

    def _physical(self, attempt):
        result = super()._physical(attempt)
        original = self._model_bindings.get(id(attempt['source']))
        if original is not None:
            source, source_raw, owner, lease, grant, grant_raw, packet_raw, schema_raw = original
            runtime = owner._issued(lease)
            row = owner._issued_native_model_grant(grant, runtime['bundle'], runtime['token'], runtime['observation'])
            if (attempt['source'] is not source or source.raw != source_raw or owner.sources is not self or
                    attempt['runtime'] is not runtime or attempt['claim'] is not runtime['claim'] or
                    attempt['membership'] is not owner.membership or runtime['native_model_grant'] is not grant or
                    grant.raw != grant_raw or row['attempt'] is not runtime or
                    canonical(runtime['origin']['native_model']) != grant_raw):
                raise Conflict('original generating source/runtime/grant binding differs')
            binding = json.loads(grant_raw)
            if json.loads(source_raw)['native_model'] != binding:
                raise Conflict('original generating source approval differs')
            for key,field,bound,frozen in (('packet','packet_sha256',60000,packet_raw),
                                           ('schema','output_schema_sha256',8192,schema_raw)):
                raw = os.pread(attempt['fds'][key], bound+1, 0)
                if raw != frozen or 'sha256:'+hashlib.sha256(raw).hexdigest() != binding[field]:
                    raise Conflict('original frozen generating packet/schema changed')
        elif 'native_model' in json.loads(attempt['source'].raw):
            raise Conflict('original generating source publication missing')
        return result

    def poll_packet_data(self, source):
        """Original held FD decoding only; no model/usage/review publication."""
        attempt = self._issued(source)
        with self._lock:
            if id(source) in self._packet_failures:
                raise Conflict('original packet source failed; no replacement')
            try:
                self._physical(attempt)
                reader = self._packet_readers.get(id(source))
                if reader is None or reader.fd != attempt['fds']['read']:
                    raise Conflict('original same-source packet reader required')
                return reader.poll()
            except Exception:
                self._packet_failures.add(id(source))
                retained = self._packet_readers.get(id(source))
                if retained is not None:retained.failed = True
                attempt['status'] = 'QUARANTINED'
                raise

    def poll(self, source):
        self._issued(source)
        raise PermissionError('native model producer qualification missing; use data-only packet decoding')

    def seal(self, source):
        self._issued(source)
        raise PermissionError('native model EOF/account/usage qualification missing; no source publication')
