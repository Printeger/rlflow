"""Original frozen generating FDs and launch fence; no usage/source cap yet."""
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .hybrid_fixture_materials import _write_new
from .hybrid_usage_source import FixtureUsageSourceOwner, FixtureUsageSource, SOURCE_FILES
from .store import Conflict, canonical


@dataclass(frozen=True,eq=False)
class NativeModelResult:
    source: FixtureUsageSource
    raw: bytes


class NativeModelSourceOwner(FixtureUsageSourceOwner):
    def __init__(self, pool):
        self._model_bindings = {}
        self._packet_readers = {}
        self._packet_origins = {}
        self._packet_completed = {}
        self._packet_failures = set()
        self._gate_bindings = {}
        self._gate_inputs = {}
        self._model_ready = {}
        # Capture the current host CLI cache location once, without opening it.
        # Runtime callers cannot select another path or ask for keyring fallback.
        self._account_home = os.path.abspath(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
        self._account_caches = {}
        self._exec_observations = {}
        self._exec_origins = {}
        self._model_started = {}
        self._model_results = {}
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
        cache=self._account_caches.get(id(attempt['source']))
        execution=self._exec_observations.get(id(attempt['source']))
        return (tuple(row['fd'] for row in self._gate_inputs.get(id(attempt['source']),[]) if row['fd'] is not None)
            +(cache.descriptors() if cache is not None else ())
            +(execution.descriptors() if execution is not None else ()))

    def _cleanup_attempt(self, attempt):
        errors=[]
        if id(attempt['source']) in self._model_results and attempt['status']!='CLOSED':
            # Preserve raw FD audit through the very last pre-close boundary.
            # Bad late data invalidates financial publication, but must never
            # prevent independent physical STOP/FD cleanup.
            try:self.packet_result_data(attempt['source'])
            except Exception:self._packet_failures.add(id(attempt['source']))
        cache=self._account_caches.get(id(attempt['source']))
        try:super()._cleanup_attempt(attempt)
        except (OSError,Conflict) as error:errors.append(error)
        execution=self._exec_observations.get(id(attempt['source']))
        if execution is not None:
            try:execution.close()
            except (OSError,Conflict) as error:errors.append(error)
        if cache is not None:
            # A live producer may refresh/recreate auth.json. Never close the
            # cleanup capability or declare the copy gone before it is reaped.
            if attempt['producer'] is not None and attempt['producer'].poll() is None:
                errors.append(Conflict('live original producer retains account-cache cleanup'))
            else:
                try:cache.close()
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

    def observe_native_exec(self,owner,lease):
        """Actual original producer ELF/stdio DATA, no account or G permission.

        Missing or changed observations never certify EOF/usage. A failed
        observation is retained for STOP, not replaced by caller flags.
        """
        from .hybrid_native_model_runtime import NativeModelOwner
        from .hybrid_native_exec_observation import _ExecFDObservation
        from .jobs import identity
        self._actual()
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original native executable observation owner required')
        runtime=owner._issued(lease);source=runtime['source'];attempt=self._issued(source)
        with self._lock:
            self._physical(attempt)
            if not runtime['release_entered'] or attempt['producer'] is None:
                raise Conflict('original released producer required for executable observation')
            ready=self._model_ready.get(id(source))
            if ready is None or ready[0] is not source:
                raise Conflict('original same-source sandbox ready required')
            # G is asynchronous. Do not consume the one bounded exec probe
            # while the fixed Python gate is still legitimately transitioning.
            # A stdout event is readiness DATA only; the kernel ELF check below
            # remains mandatory, so fabricated JSON cannot supply provenance.
            self.poll_packet_data(source)
            reader=self._packet_origins[id(source)][1]
            if reader.transcript.offset==0 or reader.transcript.state not in ('THREAD','TURN','MESSAGE','DONE'):
                raise Conflict('native stdout observation not ready for executable probe')
            def live():
                self._physical(attempt);self._check_pidfd(attempt,live=True)
                if (attempt['producer'].poll() is not None or
                        identity(attempt['producer'].pid)!=attempt['producer_identity'] or
                        runtime['producer_identity']!=attempt['producer_identity']):
                    raise Conflict('original same-PID live producer required')
            if id(source) in self._exec_observations:
                raise Conflict('original executable observation already entered')
            capture=_ExecFDObservation();self._exec_observations[id(source)]=capture
            value=capture.observe(attempt['producer'].pid,
                binary_identity=attempt['binary']['stamp'][:2],
                stdout_identity=attempt['identities']['events.jsonl'],
                stderr_identity=attempt['identities']['stderr.log'],check_live=live)
            # Separate Source-owned immutable origin from the helper's DATA
            # cache. A failed/replaced/mutated helper can never mint an ACK.
            self._exec_origins[id(source)]=(source,owner,lease,capture,canonical(value),
                canonical(runtime['producer_identity']),attempt['binary']['stamp'][:2],
                tuple(attempt['identities']['events.jsonl']),tuple(attempt['identities']['stderr.log']))
            return {**value,'source_id':source.id,'lease_id':lease.id,
                'elf_observed':True,'source_authenticated':False,'account_qualified':False,
                'usage_qualified':False,'condition_evidence_enabled':False}

    def _prepare_current_account_cache(self,owner,lease):
        from .hybrid_native_model_runtime import NativeModelOwner
        from .hybrid_native_account_cache import _AccountCache
        self._actual()
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original model account-cache owner required')
        runtime=owner._issued(lease);source=runtime['source'];attempt=self._issued(source)
        with self._lock:
            owner._check_account_cache_gate(runtime)
            self._physical(attempt)
            if id(source) not in self._gate_bindings:
                raise Conflict('original private session gate materials required')
            if id(source) in self._account_caches:
                raise Conflict('original account-cache attempt already entered')
            identity=self._gate_bindings[id(source)][4][-1][:2]
            cache=_AccountCache(self._account_home,attempt['path']/'auth-private',destination_identity=identity)
            self._account_caches[id(source)]=cache
            return cache.stage(lambda:owner._check_account_cache_gate(runtime))

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
    def _runtime_spawn(self, owner, lease):
        # Only the original fixed Python gate is spawned. Its control pipe
        # receives no G here, so it cannot exec Codex or read account secrets.
        return super()._runtime_spawn(owner,lease)
    def _check_launch_ready(self,owner,lease):
        runtime=owner._issued(lease);attempt=self._issued(runtime['source'])
        if owner.sources is not self or attempt['runtime'] is not runtime:
            raise PermissionError('original same-source native launch required')
        self._physical(attempt);self._check_pidfd(attempt,live=True)
        ready=self._model_ready.get(id(attempt['source']))
        if ready is None or ready[0] is not attempt['source']:
            raise Conflict('original kernel-ready native producer required before G')
        # Recheck the original producer's held ready bytes, not a caller flag.
        if os.pread(attempt['fds']['ready_read'],4097,0)!=ready[1]+b'\n':
            raise Conflict('original native sandbox ready changed before G')

    def _runtime_release(self,owner,lease):
        if owner._launch_active is None:
            raise PermissionError('native generating release unqualified')
        return super()._runtime_release(owner,lease)

    def _native_spawn_material(self, owner, attempt):
        self._physical(attempt)
        if self._gate_bindings.get(id(attempt['source'])) is None:
            raise Conflict('original model gate materials required before producer preparation')
        return (attempt['binary']['fd'],*(attempt['fds'][key] for key in
            ('ready_write','config','packet','schema','helper')))

    def _wait_ready(self, owner, attempt):
        from .hybrid_native_model_gate import HELPER_SHA256
        from .hybrid_goals import digest
        runtime=attempt['runtime'];binding=runtime['origin']['native_model']
        original=self._gate_bindings[id(attempt['source'])]
        expected={'type':'model.sandbox.ready','pid':attempt['producer_identity']['pid'],
            'nonce':runtime['origin']['nonce'],'config_sha256':digest(json.loads(original[1])),
            **{key:binding[key] for key in ('packet_sha256','output_schema_sha256','role','binary_sha256')},
            'helper_sha256':'sha256:'+HELPER_SHA256,'single_tgid':True,'landlock':True,
            'no_new_privs':True,'packet_sealed':True,'schema_sealed':True,
            'network_enforcement':'PARTIAL','account_qualified':False,
            'binary_identity':list(attempt['binary']['stamp'][:2]),
            'home_identity':list(original[4][-1][:2])+[os.geteuid(),0o700],
            'work_identity':list(original[5][-1][:2])+[os.geteuid(),0o700]}
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            self._physical(attempt);self._check_pidfd(attempt,live=True)
            raw=os.pread(attempt['fds']['ready_read'],4097,0)
            if raw:
                if raw!=canonical(expected)+b'\n':raise Conflict('original model sandbox receipt differs')
                self._model_ready[id(attempt['source'])]=(attempt['source'],canonical(expected))
                return
            if attempt['producer'].poll() is not None:break
            time.sleep(.01)
        raise Conflict('original model sandbox not ready; no G')

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

    def _packet_step(self, source, *, finish=False, candidate=False, result=False, review=False):
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
                if not candidate and not result and not review:return state
                if not state['data_complete']:
                    raise Conflict('original full packet audit required before candidate data')
                audited=json.loads(self._packet_completed[id(source)][1])
                if result:return audited  # fresh data copy; never a usage receipt
                if 'failure_event' in audited:
                    raise Conflict('failed model observation cannot produce candidate or review data')
                message=json.loads(self._packet_completed[id(source)][0])
                from .hybrid_protocol import validate_schema
                validate_schema(json.loads(original[4]),message)
                role=json.loads(original[3])['role']
                if review:
                    if role!='Evaluator':raise Conflict('original Evaluator packet required')
                    from .hybrid_native_model_stream import review_data
                    binding=json.loads(self._model_bindings[id(source)][5])
                    return review_data(message,binding['candidate_sha256'])
                if role!='Engineer':raise Conflict('original Engineer candidate required')
                if original[5] is None:
                    raise PermissionError('original workflow candidate paths required')
                # Neither the model nor this API chooses input bytes, edit
                # scope or tests. The packet/schema and approved Registry
                # scope are independently frozen by this original source.
                from .hybrid_engineering_candidate import transform
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

    def review_data(self, source):
        """Audited original Evaluator FD -> version-bound closed review DATA.

        Uses the independently frozen packet role/schema/grant, never caller
        role/candidate fields or mutable transcript declarations. No model
        provenance, independence receipt, condition CAS or new-session grant.
        """
        return self._packet_step(source,review=True)

    def _runtime_usage_publication(self, owner, lease):
        """Original writer hook, NOT an audited-data or caller receipt API.

        Only an exact natural-exit/full-audit result can issue after physical
        terminal proof. Missing/failed data still returns None; packet fields,
        packet_result_data or complete=true cannot substitute for a cap.
        """
        from .hybrid_native_model_runtime import NativeModelOwner
        self._actual()
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original native usage publisher owner required')
        runtime=owner._issued(lease);source=runtime['source']
        if id(source) in self._packet_failures:return None
        original=self._model_results.get(id(source))
        if original is None or runtime['terminal'] is None:return None
        cap=self._issued_native_result(owner,lease,original[2])
        attempt=self._issued(source);terminal=runtime['terminal']
        if (attempt['status']!='CLOSED' or any(fd is not None for fd in attempt['fds'].values()) or
                self._extra_fork_descriptors(attempt) or attempt['producer'] is None or
                attempt['producer'].poll()!=0 or not attempt['producer'].stdin.closed or
                terminal['scope']!='FIXED_NATIVE_SINGLE_TGID' or terminal['lease_id']!=lease.id or
                terminal['producer']!=runtime['producer_identity'] or
                not terminal['all_original_source_fds_closed'] or not terminal['original_participant_reaped']):
            raise Conflict('complete original native terminal required for usage issue')
        from .hybrid_goals import digest
        from .hybrid_native_model_usage import PUBLICATION
        from .hybrid_protocol import validate_schema
        data=json.loads(cap.raw);binding=runtime['origin']['native_model']
        ack=self._runtime_started(owner,lease)
        if ack is None or ack is not runtime['started_ack']:
            raise Conflict('original native result ACK lineage differs')
        value={'profile':'ORIGINAL_NATIVE_CLI_USAGE_V1','source_id':source.id,
            **{k:runtime['origin'][k] for k in ('lease_id','task_id','attempt_id','nonce')},
            'grant_id':binding['grant_id'],'grant_sha256':digest(binding),
            'producer':runtime['producer_identity'],
            **{k:binding[k] for k in ('workspace_id','packet_sha256','output_schema_sha256','candidate_sha256')},
            **{k:data[k] for k in ('stream_sha256','output_sha256','usage','ready_sha256')},
            'stream_bytes':data['bytes'],'started_ack_sha256':digest(json.loads(ack.raw)),
            'terminal_proof_sha256':digest(terminal),'producer_exit_code':0}
        validate_schema(PUBLICATION,value)
        return value

    def _released_original(self,owner,lease):
        from .hybrid_native_model_runtime import NativeModelOwner
        self._actual()
        if type(owner) is not NativeModelOwner or owner.sources is not self:
            raise PermissionError('original native result owner required')
        runtime=owner._issued(lease);source=runtime['source'];attempt=self._issued(source)
        witness=owner._native_releases.get(id(lease));launch=owner._native_launches.get(id(lease))
        if (witness is None or launch is None or witness[0] is not runtime or witness[1] is not launch[0] or
                witness[2]!=launch[1] or witness[1].raw!=witness[2] or witness[3] is not source or
                witness[4]!=canonical(runtime['producer_identity']) or
                not runtime['release_entered'] or attempt['runtime'] is not runtime or
                self._model_ready.get(id(source))!=(source,witness[5])):
            raise PermissionError('original native final release witness required')
        return runtime,source,attempt,witness

    def observe_native_started(self,owner,lease):
        """Original ELF/stdio + first held thread event; not account/usage proof."""
        from .hybrid_usage_source import _RuntimeStartedObservation
        from .hybrid_usage_stream import parse_line,MAX_LINE
        from .hybrid_goals import digest
        with self._lock:
            runtime,source,attempt,witness=self._released_original(owner,lease)
            old=self._model_started.get(id(source))
            if old is not None:return self._runtime_started(owner,lease)
            capture=self._exec_observations.get(id(source))
            if capture is None:self.observe_native_exec(owner,lease)
            capture=self._exec_observations[id(source)]
            origin=self._exec_origins.get(id(source))
            if (origin is None or origin[0] is not source or origin[1] is not owner or origin[2] is not lease or
                    origin[3] is not capture or canonical(capture.value)!=origin[4] or
                    origin[5]!=canonical(runtime['producer_identity']) or origin[6]!=attempt['binary']['stamp'][:2] or
                    origin[7]!=tuple(attempt['identities']['events.jsonl']) or
                    origin[8]!=tuple(attempt['identities']['stderr.log'])):
                raise Conflict('original registered successful native ELF observation required')
            self._physical(attempt)
            self._check_pidfd(attempt,live=True)
            from .jobs import identity
            if (attempt['producer'].poll() is not None or
                    identity(attempt['producer'].pid)!=runtime['producer_identity']):
                raise Conflict('original live native ACK producer required')
            raw=os.pread(attempt['fds']['read'],MAX_LINE+1,0)
            end=raw.find(b'\n')
            if end<0:raise Conflict('complete first native thread event required')
            line=raw[:end+1];event=parse_line(line)
            if event['type']!='thread.started':raise Conflict('original first native thread required')
            ack=_RuntimeStartedObservation(source,canonical({'source_id':source.id,
                'lease_id':lease.id,'producer':runtime['producer_identity'],'event':event,
                'line_sha256':'sha256:'+hashlib.sha256(line).hexdigest(),
                'elf_observation':capture.value,'ready_sha256':digest(json.loads(witness[5]))}))
            self._model_started[id(source)]=(owner,lease,ack,ack.raw)
            return ack

    def _runtime_started(self,owner,lease):
        runtime=owner._issued(lease);source=runtime['source']
        original=self._model_started.get(id(source))
        if original is None:return None  # Ignore inherited caller-mutable runtime_ack.
        self._released_original(owner,lease)
        if (original[0] is not owner or original[1] is not lease or
                original[2].source is not source or original[2].raw!=original[3]):
            raise Conflict('original native started capability changed')
        return original[2]

    def _issued_native_result(self,owner,lease,cap):
        runtime,source,attempt,_=self._released_original(owner,lease)
        row=self._model_results.get(id(source))
        if (id(source) in self._packet_failures or
                type(cap) is not NativeModelResult or row is None or row[0] is not owner or row[1] is not lease or
                row[2] is not cap or cap.source is not source or cap.raw!=row[3] or
                row[4] is not runtime['native_model_grant'] or row[4].raw!=row[5]):
            raise PermissionError('original same-lease native result capability required')
        if attempt['status']!='CLOSED':self.packet_result_data(source)
        return cap

    def collect_native_result(self,owner,lease):
        """Natural exit0 + full prefix audit under original no-new-TGID scope.

        The fixed trusted CLI enforces ChatGPT/workspace settings. Successful
        completion under that pipeline is the account binding, not JWT parsing
        or a provider-price/total-backend-request attestation. No condition CAS.
        """
        from .hybrid_goals import digest
        with self._lock:
            runtime,source,attempt,witness=self._released_original(owner,lease)
            old=self._model_results.get(id(source))
            if old is not None:return self._issued_native_result(owner,lease,old[2])
            if runtime.get('source_stop_latched'):
                raise Conflict('STOP prohibits a new native result')
            self._physical(attempt)
            ack=self._runtime_started(owner,lease)
            if (ack is None or runtime['started_ack'] is not ack or
                    owner._current(runtime)['fixture_runtime']['phase']!='STARTED_AS_OBSERVED'):
                raise Conflict('original observed native start required before result')
            process=attempt['producer']
            if process is None or process.poll() is None:return None
            if process.poll()!=0:raise Conflict('original native result requires natural exit0')
            self._check_pidfd(attempt,live=False)
            state=self.poll_packet_data(source);reader=self._packet_origins[id(source)][1]
            stamp=reader._stamp()
            if reader.transcript.offset<stamp[2] and reader.transcript.state not in ('DONE','FAILURE_OBSERVED'):
                return None
            state=self.finish_packet_data(source)
            if not state['data_complete']:return None
            data=self.packet_result_data(source)
            if 'failure_event' in data or not data['usage']['complete']:
                raise Conflict('original successful complete native usage required')
            from .hybrid_usage_stream import MAX_LINE,parse_line
            first=os.pread(attempt['fds']['read'],MAX_LINE+1,0)
            end=first.find(b'\n')
            if end<0:raise Conflict('original native ACK line missing at audit')
            line=first[:end+1];started=json.loads(ack.raw)
            if ('sha256:'+hashlib.sha256(line).hexdigest()!=started['line_sha256'] or
                    parse_line(line)!=started['event']):
                raise Conflict('original native ACK differs from final audited first line')
            # Validate the role-specific structured output before issuing.
            binding=json.loads(runtime['native_model_grant'].raw)
            if binding['role']=='Engineer':
                candidate=self.candidate_data(source)
                output={'candidate_sha256':candidate.output_sha256,'files':candidate.files()}
            else:output={'review':self.review_data(source)}
            cap=NativeModelResult(source,canonical({**data,**output,
                'ready_sha256':digest(json.loads(witness[5])),
                'source_authenticated':True,'account_qualified':True,
                'account_binding':'TRUSTED_CLI_FORCED_CHATGPT_WORKSPACE',
                'condition_evidence_enabled':False}))
            if runtime.get('source_stop_latched'):
                raise Conflict('STOP raced original native result; no issue')
            self._model_results[id(source)]=(owner,lease,cap,cap.raw,
                runtime['native_model_grant'],runtime['native_model_grant'].raw)
            return cap

    def poll(self, source):
        self._issued(source)
        raise PermissionError('native model producer qualification missing; use data-only packet decoding')

    def seal(self, source):
        self._issued(source)
        raise PermissionError('native model EOF/account/usage qualification missing; no source publication')
