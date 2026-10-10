"""Original frozen generating packet FDs; no model launch qualification yet."""
import hashlib
import json
import os
import stat
from pathlib import Path

from .hybrid_fixture_materials import _write_new
from .hybrid_usage_source import FixtureUsageSourceOwner, FixtureUsageSource, SOURCE_FILES
from .store import Conflict, canonical


class NativeModelSourceOwner(FixtureUsageSourceOwner):
    def __init__(self, pool):
        self._model_bindings = {}
        self._packet_readers = {}
        self._packet_origins = {}
        self._packet_completed = {}
        self._packet_failures = set()
        self._gate_bindings = {}
        self._gate_inputs = {}
        super().__init__(pool)

    def _actual(self):
        from . import hybrid_usage_source
        if type(self) is not NativeModelSourceOwner or hybrid_usage_source._owners.get(id(self)) is not self:
            raise PermissionError('exact original generating source owner required')
        super()._actual()

    def _source_files(self):
        return {**SOURCE_FILES, 'packet':'packet.json', 'schema':'output.schema.json',
            'config':'launch.json','helper':'kernel-helper.py',
            'ready_read':'sandbox.jsonl','ready_write':'sandbox.jsonl'}

    def _readonly_source_keys(self):
        return super()._readonly_source_keys() | {'packet','schema','config','helper','ready_read'}

    def _check_binary(self, attempt):
        row = attempt['binary']; info = os.fstat(row['fd'])
        stamp = (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        if stamp != row['stamp']:raise Conflict('original generating ELF changed')

    def _open_gate_input(self, source, path, flags):
        # Retain immediately after open, BEFORE any fallible identity/hash IO.
        fd = os.open(path,flags|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        row = {'fd':fd,'identity':None,'path':str(path)}
        self._gate_inputs.setdefault(id(source),[]).append(row)
        info = os.fstat(fd); row['identity'] = (info.st_dev,info.st_ino)
        return fd

    def _pin_gate_binary(self, source):
        from .hybrid_native_diagnostic_gate import NATIVE
        previous = self._open_gate_input(source,'/',os.O_PATH|os.O_DIRECTORY)
        current_path=''
        for part in Path(NATIVE).parts[1:-1]:
            fd = os.open(part,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=previous)
            current_path += '/'+part
            row = {'fd':fd,'identity':None,'path':current_path}
            self._gate_inputs[id(source)].append(row)
            info = os.fstat(fd); row['identity'] = (info.st_dev,info.st_ino)
            if info.st_uid!=0 or info.st_mode&0o022:raise Conflict('original immutable ELF ancestors required')
            previous = fd
        fd = os.open('codex',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK,dir_fd=previous)
        row = {'fd':fd,'identity':None,'path':NATIVE}; self._gate_inputs[id(source)].append(row)
        info = os.fstat(fd); row['identity'] = (info.st_dev,info.st_ino)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or
                not 0<info.st_size<=512*1024**2 or os.pread(fd,4,0)!=b'\x7fELF'):
            raise Conflict('fixed root-owned bounded generating ELF required')
        value=hashlib.sha256(); offset=0
        while offset<info.st_size:
            block=os.pread(fd,min(1024**2,info.st_size-offset),offset)
            if not block:raise Conflict('original generating ELF truncated')
            value.update(block); offset+=len(block)
        stamp=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        after=os.fstat(fd)
        if stamp!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise Conflict('original generating ELF changed during pin')
        return {'fd':fd,'stamp':stamp,'sha256':'sha256:'+value.hexdigest()}

    def _extra_fork_descriptors(self, attempt):
        return tuple(row['fd'] for row in self._gate_inputs.get(id(attempt['source']),[]) if row['fd'] is not None)

    def _cleanup_attempt(self, attempt):
        errors=[]
        try:super()._cleanup_attempt(attempt)
        except (OSError,Conflict) as error:errors.append(error)
        for row in self._gate_inputs.get(id(attempt['source']),[]):
            if row['fd'] is None:continue
            try:
                info=os.fstat(row['fd'])
                if row['identity'] is None or (info.st_dev,info.st_ino)!=row['identity']:
                    raise Conflict('original generating input FD identity unknown/reused')
                os.close(row['fd']); row['fd']=None
            except (OSError,Conflict) as error:errors.append(error)
        if errors:
            attempt['status']='UNKNOWN'
            raise Conflict('original generating input cleanup incomplete') from errors[0]

    def _prepare_model_gate(self, owner, lease):
        """Private original materials only. No process, auth read or G."""
        from .hybrid_native_model_runtime import NativeModelOwner
        from .hybrid_native_model_gate import FIELDS, HELPER_SHA256
        from .hybrid_runtime_boundary import directory_chain
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original same-owner generating gate required')
        runtime = owner._issued(lease); source = runtime['source']; attempt = self._issued(source)
        with self._lock:
            self._physical(attempt)
            prior = self._gate_bindings.get(id(source))
            if prior is not None:return {'prepared':True,'execution_qualified':False}
            if attempt.get('model_gate_entered'):
                raise Conflict('original gate material outcome UNKNOWN; no replacement')
            attempt['model_gate_entered'] = True
            try:
                binding = json.loads(runtime['native_model_grant'].raw)
                binary = self._pin_gate_binary(source); attempt['binary'] = binary
                if binary['sha256'] != binding['binary_sha256']:
                    raise Conflict('original approved generating ELF differs')
                config = {key:binding[key] for key in FIELDS}; config_raw = canonical(config)
                helper_fd = self._open_gate_input(source,Path(__file__).with_name('hybrid_native_diagnostic_gate.py'),os.O_RDONLY)
                info=os.fstat(helper_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size>16384:
                    raise Conflict('original bounded regular kernel helper required')
                helper_raw = os.pread(helper_fd,16385,0)
                if len(helper_raw)>16384 or hashlib.sha256(helper_raw).hexdigest()!=HELPER_SHA256:
                    raise Conflict('original hash-pinned kernel helper differs')
                for name in ('auth-private','work'):(attempt['path']/name).mkdir(mode=0o700)
                for key,name,raw,flags in (('config','launch.json',config_raw,os.O_RDONLY),
                        ('helper','kernel-helper.py',helper_raw,os.O_RDONLY),
                        ('ready_read','sandbox.jsonl',b'',os.O_RDONLY)):
                    _write_new(attempt['path']/name,raw)
                    fd = os.open(attempt['path']/name,flags|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
                    attempt['fds'][key] = fd; info = os.fstat(fd)
                    attempt['identities'][name] = [info.st_dev,info.st_ino]
                fd = os.open(attempt['path']/'sandbox.jsonl',os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
                attempt['fds']['ready_write'] = fd
                self._gate_bindings[id(source)] = (source,config_raw,helper_raw,binary['stamp'],
                    directory_chain(attempt['path']/'auth-private'),directory_chain(attempt['path']/'work'))
                self._physical(attempt)
                return {'prepared':True,'execution_qualified':False}
            except BaseException:
                attempt['status'] = 'UNKNOWN'; raise

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
                reader = self._packet_readers[id(original)]
                # Allocation can follow a durable REGISTER retry. Rebind a
                # single captured Registry to the original grant config hash;
                # neither the current registry nor a mutable grant row alone
                # is an approval source.
                from .hybrid_goals import digest
                config=json.loads(owner.plans.registry._raw)
                if digest(config)!=binding['native_model']['config_hash']:
                    raise Conflict('original generating Registry config changed before allocation')
                paths = (tuple(config['tools']['native_model']
                    ['definition']['spec']['candidate_paths'])
                    if 'workflow' in binding['native_model'] else None)
                self._packet_origins[id(original)] = (original, reader, reader.transcript,
                    row['packet_raw'], row['schema_raw'], paths)
                return original
            except BaseException:
                attempt['status'] = 'UNKNOWN'; raise

    def _physical(self, attempt):
        result = super()._physical(attempt)
        for row in self._gate_inputs.get(id(attempt['source']),[]):
            if row['fd'] is None:raise Conflict('original generating input closed before terminal')
            info=os.fstat(row['fd']); current=os.stat(row['path'],follow_symlinks=False)
            if row['identity'] is None or (info.st_dev,info.st_ino)!=row['identity'] or (current.st_dev,current.st_ino)!=row['identity']:
                raise Conflict('original generating input FD/path rebound')
            if stat.S_ISDIR(info.st_mode) and (info.st_uid!=0 or info.st_mode&0o022):
                raise Conflict('original immutable generating input ancestor changed')
        if attempt.get('binary') is not None:self._check_binary(attempt)
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
        gate = self._gate_bindings.get(id(attempt['source']))
        if gate is not None:
            from .hybrid_runtime_boundary import directory_chain
            source,config_raw,helper_raw,binary_stamp,home_chain,work_chain = gate
            if (source is not attempt['source'] or attempt['binary']['stamp'] != binary_stamp or
                    os.pread(attempt['fds']['config'],8193,0) != config_raw or
                    os.pread(attempt['fds']['helper'],16385,0) != helper_raw or
                    directory_chain(attempt['path']/'auth-private') != home_chain or
                    directory_chain(attempt['path']/'work') != work_chain):
                raise Conflict('original generating gate materials changed')
        return result

    def _packet_step(self, source, *, finish=False, candidate=False, result=False):
        """One original FD step, never an EOF/account/settlement assertion."""
        attempt = self._issued(source)
        with self._lock:
            if id(source) in self._packet_failures:
                raise Conflict('original packet source failed; no replacement')
            try:
                self._physical(attempt)
                reader = self._packet_readers.get(id(source))
                original = self._packet_origins.get(id(source))
                if (original is None or original[0] is not source or reader is not original[1] or
                        reader.transcript is not original[2] or reader.fd != attempt['fds']['read']):
                    raise Conflict('original same-source packet reader required')
                state = reader.finish_data() if finish else reader.poll()
                if state['data_complete']:
                    completed=(reader.audited_message,canonical(reader.result))
                    prior=self._packet_completed.setdefault(id(source),completed)
                    if completed!=prior or reader.transcript.message!=prior[0]:
                        raise Conflict('original audited packet output changed')
                if not candidate and not result:return state
                if not state['data_complete']:
                    raise Conflict('original full packet audit required before candidate data')
                audited=json.loads(self._packet_completed[id(source)][1])
                if result:return audited  # fresh data copy; never a usage receipt
                if 'failure_event' in audited:
                    raise Conflict('failed model observation cannot produce candidate data')
                if original[5] is None:
                    raise PermissionError('original workflow candidate paths required')
                # Neither the model nor this API chooses input bytes, edit
                # scope or tests. The packet/schema and approved Registry
                # scope are independently frozen by this original source.
                from .hybrid_protocol import validate_schema
                from .hybrid_engineering_candidate import transform
                if reader.transcript.role!='Engineer':raise Conflict('original Engineer candidate required')
                message=json.loads(self._packet_completed[id(source)][0])
                validate_schema(json.loads(original[4]),message)
                return transform(json.loads(original[3])['files'],message,allowed_paths=original[5])
            except Exception:
                self._packet_failures.add(id(source))
                retained = self._packet_readers.get(id(source))
                if retained is not None:retained.failed = True
                attempt['status'] = 'QUARANTINED'
                raise

    def poll_packet_data(self, source):
        """Original held FD decoding only; no model/usage/review publication."""
        return self._packet_step(source)

    def finish_packet_data(self, source):
        """Finite full-prefix audit only. Completion is NOT authentic EOF."""
        return self._packet_step(source,finish=True)

    def candidate_data(self, source):
        """Original audited Engineer bytes → bounded Candidate DATA only.

        Does not publish provenance or usage, execute checks, modify a project,
        authorize another model, or provide Reviewer/ConditionEvidence.
        Original producer/account/EOF and settlement gates remain mandatory.
        """
        return self._packet_step(source,candidate=True)

    def packet_result_data(self, source):
        """Frozen audited hashes/observed usage/failure DATA; no authority.

        Failure data does not prove final CLI state or EOF, and never permits
        a candidate, known-cost settlement, refund or another model session.
        """
        return self._packet_step(source,result=True)

    def _runtime_usage_publication(self, owner, lease):
        """Original writer hook, NOT an audited-data or caller receipt API.

        The native account/producer/G/EOF qualification issuer is not yet
        implemented. Consequently there is no issued usage publication. Do
        not use source fields, packet_result_data or complete=true as a cap.
        """
        from .hybrid_native_model_runtime import NativeModelOwner
        self._actual()
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original native usage publisher owner required')
        owner._issued(lease)
        return None

    def poll(self, source):
        self._issued(source)
        raise PermissionError('native model producer qualification missing; use data-only packet decoding')

    def seal(self, source):
        self._issued(source)
        raise PermissionError('native model EOF/account/usage qualification missing; no source publication')
