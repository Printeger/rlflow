"""Original configured CPU source; transport/keeper/task are separate identities.

Original Core-gated dispatch; task reports, keeper kernel terminal and original
manager job completion are separate proofs. Unknown sources never refund/adopt.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import time
import uuid

from .hybrid_usage_source import FixtureUsageSourceOwner, FixtureUsageSource, SOURCE_FILES, _RuntimeStartedObservation
from .hybrid_fixture_materials import _write_new
from .hybrid_runtime_boundary import directory_chain
from .hybrid_local_cpu_profile import validate_bound_spec
from .store import Conflict,canonical
from .jobs import identity
from .hybrid_goals import digest

TRUSTED_MODULES=('hybrid_local_runner_service.py','hybrid_local_runner_keeper.py',
                 'hybrid_local_runner_cgroup.py','hybrid_local_runner_sandbox.py')


class LocalCpuSourceOwner(FixtureUsageSourceOwner):
    def __init__(self,pool):
        super().__init__(pool)
        self._kernel_terminals={}

    def _actual(self):
        from .hybrid_usage_source import _owners
        if type(self) is not LocalCpuSourceOwner or _owners.get(id(self)) is not self:
            raise PermissionError('exact original configured CPU source owner required')
        super()._actual()

    def start_fixture(self,*args,**kwargs):raise PermissionError('fixed source cannot start configurable task')

    def _source_files(self):
        return {**SOURCE_FILES,'config':'launch.json','task_read':'task-stdout','task_error_read':'task-stderr'}

    def _readonly_source_keys(self):
        return super()._readonly_source_keys()|{'task_read','task_error_read'}

    def _source_file(self,name):
        if name.startswith('input:'):return 'work/'+name.removeprefix('input:')
        if name.startswith('trusted:'):return 'trusted/rlflow/'+name.removeprefix('trusted:')
        return super()._source_file(name)

    def _source_readonly(self,name):
        return name.startswith(('input:','trusted:')) or super()._source_readonly(name)

    def _extra_fork_descriptors(self,row):
        fds=[];manager=row.get('manager')
        if manager is not None and manager.fd is not None:fds.append(manager.fd)
        process=row.get('producer')
        if process is not None and process.stdout is not None and not process.stdout.closed:fds.append(process.stdout.fileno())
        return fds

    def _runtime_allocate(self,owner,lease):
        from .hybrid_local_cpu_runtime import LocalCpuRunnerOwner
        if type(owner) is not LocalCpuRunnerOwner or owner.sources is not self:
            raise PermissionError('original configured CPU source/runtime pair required')
        runtime=owner._issued(lease);claim=runtime['claim']
        with self._lock:
            old=self._attempts.get(id(claim))
            if old is not None:
                if old['runtime'] is not runtime or not old.get('local_allocated'):
                    raise Conflict('original configured CPU allocation UNKNOWN; no replacement')
                return old['source']
            member=self.pool._issued_member(owner.membership)
            try:
                binding=json.loads(runtime['local_cpu_grant'].raw)
                grant=owner._issued_local_cpu_grant(runtime['local_cpu_grant'],runtime['bundle'],runtime['token'],runtime['observation'])
                spec=validate_bound_spec(json.loads(grant['spec_raw']),binding)
                validate_bound_spec(json.loads(owner.plans.registry._raw)['tools']['local_cpu']['definition']['spec'],binding)
                pins=json.loads(grant['modules_raw'])
                if (digest(pins)!=binding['modules_sha256'] or digest(json.loads(owner.plans.registry._raw)
                        ['tools']['local_cpu']['definition']['modules'])!=binding['modules_sha256']):
                    raise Conflict('original approved CPU module pins changed before allocation')
                row=self._allocate(owner.membership,claim,'runtime.local_cpu',member)
                row['runtime']=runtime;row['runtime_owner']=owner
                row.update(manager=None,protocol_tail=b'',protocol_rows=[],transport_identity=None,
                           protocol_identity=None,ready=None,task_closed=None,managed_terminal=None)
                trusted=row['path']/'trusted';trusted.mkdir(mode=0o700)
                package=trusted/'rlflow';package.mkdir(mode=0o700)
                trusted_manifest={}
                for name in TRUSTED_MODULES:
                    raw=(Path(__file__).parent/name).read_bytes()
                    if 'sha256:'+hashlib.sha256(raw).hexdigest()!=pins[name]:
                        raise Conflict('original approved trusted service bytes changed')
                    _write_new(package/name,raw)
                    fd=os.open(package/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    row['fds']['trusted:'+name]=fd;info=os.fstat(fd)
                    row['identities']['trusted/rlflow/'+name]=[info.st_dev,info.st_ino]
                    trusted_manifest[name]=hashlib.sha256(raw).hexdigest()
                work=row['path']/'work';work.mkdir(mode=0o700)
                for name,value in spec['inputs'].items():
                    _write_new(work/name,value.encode())
                    fd=os.open(work/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    # Keep the original BEFORE fstat/validation. Failed close or
                    # fstat never loses an input handle or creates a replacement.
                    row['fds']['input:'+name]=fd
                    info=os.fstat(fd);row['identities']['work/'+name]=[info.st_dev,info.st_ino]
                for name in ('task-stdout','task-stderr'):_write_new(row['path']/name,b'')
                for key,name in (('task_read','task-stdout'),('task_error_read','task-stderr')):
                    fd=os.open(row['path']/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                    row['fds'][key]=fd;info=os.fstat(fd)
                    row['identities'][name]=[info.st_dev,info.st_ino]
                config={'code':spec['code'],'work':str(work),'stdout':str(row['path']/'task-stdout'),
                        'stderr':str(row['path']/'task-stderr'),'limits':spec['limits'],'seconds':spec['seconds'],
                        'output_identities':{name:[os.fstat(row['fds'][key]).st_dev,
                            os.fstat(row['fds'][key]).st_ino,os.geteuid()]
                            for name,key in (('stdout','task_read'),('stderr','task_error_read'))}}
                raw=canonical(config)
                if len(raw)>65536:raise Conflict('original configured CPU launch config exceeds service bound')
                row['config_raw']=raw
                _write_new(row['path']/'launch.json',raw)
                fd=os.open(row['path']/'launch.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
                row['fds']['config']=fd;info=os.fstat(fd)
                row['identities']['launch.json']=[info.st_dev,info.st_ino]
                old_source=row['source'];binding=json.loads(old_source.raw)
                binding['local_cpu_binding']={'config_sha256':hashlib.sha256(raw).hexdigest(),
                    'unit':'rlflow-local-'+uuid.uuid4().hex+'.service',
                    'trusted_chain':directory_chain(package),'trusted_modules':trusted_manifest,
                    'work_chain':directory_chain(work),'inputs':{
                        name:{'sha256':hashlib.sha256(value.encode()).hexdigest(),
                              'identity':row['identities']['work/'+name]}
                        for name,value in spec['inputs'].items()}}
                source=FixtureUsageSource(old_source.id,canonical(binding))
                self._sources.pop(id(old_source));row['source']=source;self._sources[id(source)]=row
                row['local_allocated']=True;row['status']='ALLOCATED_NO_HANDOFF'
                self._physical(row)
                return row['source']
            except BaseException:
                retained=self._attempts.get(id(claim))
                if retained is not None:retained['status']='UNKNOWN'
                raise

    def _physical(self,row):
        value=super()._physical(row)
        binding=json.loads(row['source'].raw).get('local_cpu_binding')
        if binding is None or row.get('local_allocated') is not True:
            raise Conflict('original configured CPU allocation/source binding incomplete')
        if binding is not None:
            raw=os.pread(row['fds']['config'],65537,0)
            if raw!=row['config_raw'] or hashlib.sha256(raw).hexdigest()!=binding['config_sha256']:
                raise Conflict('original configurable CPU source config changed')
            runtime=row['runtime'];grant_binding=json.loads(runtime['local_cpu_grant'].raw)
            grant=self._runtime_spec(row)
            config=json.loads(raw)
            # Execution config deliberately has no evaluator authority. Preserve
            # the original grant's optional acceptance while replacing ONLY
            # actual worker-controlled fields for the full-spec comparison.
            actual=dict(grant)
            actual.update(code=config['code'],limits=config['limits'],seconds=config['seconds'])
            validate_bound_spec(actual,grant_binding)
            if set(binding['inputs'])!=set(grant['inputs']):
                raise Conflict('actual configured CPU input manifest differs from approval')
            work=row['path']/'work'
            if directory_chain(work)!=binding['work_chain']:
                raise Conflict('original configured CPU work namespace changed')
            if directory_chain(row['path']/'trusted'/'rlflow')!=binding['trusted_chain']:
                raise Conflict('original trusted service namespace changed')
            if set(binding['trusted_modules'])!=set(TRUSTED_MODULES):
                raise Conflict('original approved trusted module set differs')
            pins=self._runtime_pins(row)
            for name,expected_hash in binding['trusted_modules'].items():
                if ('sha256:'+expected_hash!=pins[name] or
                        hashlib.sha256(os.pread(row['fds']['trusted:'+name],65537,0)).hexdigest()!=expected_hash):
                    raise Conflict('original trusted service source bytes changed')
            if not row['runtime']['release_entered']:
                for name,original in binding['inputs'].items():
                    fd=row['fds']['input:'+name]
                    info=os.fstat(fd);raw=os.pread(fd,65537,0)
                    approved_hash=hashlib.sha256(grant['inputs'][name].encode()).hexdigest()
                    if ([info.st_dev,info.st_ino]!=original['identity'] or original['sha256']!=approved_hash or
                            hashlib.sha256(raw).hexdigest()!=approved_hash):
                        raise Conflict('original configured CPU input differs before G')
        return value

    def _runtime_spec(self,row):
        from .hybrid_local_cpu_runtime import LocalCpuRunnerOwner
        runtime=row['runtime'];owner=row.get('runtime_owner')
        if (type(owner) is not LocalCpuRunnerOwner or owner.sources is not self or
                owner._issued(runtime['lease']) is not runtime or owner._original_source(runtime) is not row):
            raise PermissionError('original configured CPU source attempt differs')
        grant=owner._issued_local_cpu_grant(runtime['local_cpu_grant'],runtime['bundle'],runtime['token'],runtime['observation'])
        return validate_bound_spec(json.loads(grant['spec_raw']),json.loads(runtime['local_cpu_grant'].raw))

    def _runtime_pins(self,row):
        self._runtime_spec(row)
        owner=row['runtime_owner'];runtime=row['runtime']
        grant=owner._issued_local_cpu_grant(runtime['local_cpu_grant'],runtime['bundle'],runtime['token'],runtime['observation'])
        pins=json.loads(grant['modules_raw'])
        if digest(pins)!=json.loads(runtime['local_cpu_grant'].raw)['modules_sha256']:
            raise Conflict('original approved trusted module pins differ')
        return pins

    def _runtime_spawn(self,owner,lease):
        from .hybrid_local_cpu_manager import OriginalServiceManager
        runtime=owner._issued(lease);row=owner._original_source(runtime)
        with self._lock:
            self._physical(row)
            if row['launch_entered']:
                if row['producer_identity'] is None:raise Conflict('original service launch UNKNOWN; no restart')
                return row['producer_identity']
            manager=OriginalServiceManager(self,row);row['manager']=manager;manager.connect()
            binding=json.loads(row['source'].raw)['local_cpu_binding'];spec=self._runtime_spec(row)
            script=(f'import sys;sys.path.insert(0,{str(row["path"]/"trusted")!r});'
                    'from rlflow.hybrid_local_runner_service import serve;'
                    f'serve({str(row["path"]/"launch.json")!r},{binding["config_sha256"]!r})')
            command=['/usr/bin/systemd-run','--user','--pipe','--wait','--unit='+binding['unit'],
                '--property=Delegate=cpu memory pids','--property=MemoryMax='+str(spec['limits']['memory_max']),
                '--property=MemorySwapMax=0','--property=CPUQuota=100%',
                '--property=TasksMax='+str(spec['limits']['pids_max']+1),
                '--property=NoNewPrivileges=yes','--property=RestrictNamespaces=yes',
                '--property=KillMode=control-group','--property=SendSIGKILL=yes','--property=TimeoutStopSec=2',
                '--property=RuntimeMaxSec='+str(spec['seconds']+5),'--property=RemainAfterExit=yes',
                str(Path('/usr/bin/python3').resolve()),'-I','-S','-c',script]
            row['command']=command
            owner._check_spawn_gate(runtime)
            row['launch_entered']=True;runtime['spawn_entered']=True
            runtime['spawn_monotonic']=time.monotonic();row['status']='START_UNKNOWN'
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=row['fds']['stderr'],bufsize=0,close_fds=True,start_new_session=True,
                env=dict(PATH='/usr/bin:/bin',LANG='C.UTF-8',XDG_RUNTIME_DIR=f'/run/user/{os.geteuid()}',
                    DBUS_SESSION_BUS_ADDRESS=f'unix:path=/run/user/{os.geteuid()}/bus'))
            row['producer']=process  # Transport ONLY, strongly kept before identity IO.
            row['transport_identity']=identity(process.pid)
            info=os.fstat(process.stdin.fileno());row['stdin_identity']=[info.st_dev,info.st_ino]
            info=os.fstat(process.stdout.fileno());row['protocol_identity']=[info.st_dev,info.st_ino]
            end=time.monotonic()+3
            while row['ready'] is None:
                self._read_protocol(row)
                if time.monotonic()>=end:raise Conflict('original service ready UNKNOWN')
                if row['ready'] is None:select.select([process.stdout],[],[],.02)
            keeper=row['ready']['keeper'];current=identity(keeper['pid'])
            if current is None or any(current[key]!=keeper[key] for key in ('pid','starttime','boot_id')):
                raise Conflict('original keeper kernel ready differs')
            row['producer_identity']=current;manager.bind_ready(keeper)
            fd=os.pidfd_open(current['pid']);row['fds']['pidfd']=fd;info=os.fstat(fd)
            row['pidfd_identity']=[info.st_dev,info.st_ino]
            self._check_pidfd(row,live=True)
            row['status']='READING'
            return current

    def _read_protocol(self,row):
        process=row['producer']
        if process is None:return
        if process.stdout.closed:return
        info=os.fstat(process.stdout.fileno())
        if [info.st_dev,info.st_ino]!=row['protocol_identity']:
            raise Conflict('original trusted service protocol FD changed')
        if not select.select([process.stdout],[],[],0)[0]:return
        raw=os.read(process.stdout.fileno(),32769)
        tail=row['protocol_tail']+raw
        if len(tail)>32768:raise Conflict('original finite service protocol exceeds bound')
        while b'\n' in tail:
            line,tail=tail.split(b'\n',1);value=json.loads(line)
            binding=json.loads(row['source'].raw)['local_cpu_binding']
            if value.get('config_sha256')!=binding['config_sha256']:raise Conflict('original trusted report config differs')
            if value.get('type')=='local_cpu.ready' and row['ready'] is None and not row['protocol_rows']:
                if value['task']['source_sha256']!=json.loads(row['runtime']['local_cpu_grant'].raw)['code_sha256'].removeprefix('sha256:'):
                    raise Conflict('original task approved source differs')
                row['ready']=value
            elif value.get('type')=='local_cpu.task_closed' and row['ready'] is not None and row['task_closed'] is None:
                if (value['keeper']!=row['ready']['keeper'] or value['task']!=row['ready']['task'] or
                        not value['original_output_fds_closed'] or not value['original_control_fd_closed'] or
                        not value['closed']['keeper_protocol_handles_closed'] or not value['closed']['task_handles_closed'] or
                        not value['stopped']['task_empty'] or value['stopped']['handoff_unknown'] or
                        value['stopped']['protocol_cleanup_unknown']):
                    raise Conflict('original full task report UNKNOWN')
                row['task_closed']=value
            else:raise Conflict('original service protocol order/type differs')
            row['protocol_rows'].append(value)
        row['protocol_tail']=tail
        if not raw and tail:raise Conflict('original service protocol truncated')

    def _runtime_release(self,owner,lease):
        runtime=owner._issued(lease);row=owner._original_source(runtime)
        with self._lock:
            if runtime['release_entered']:return
            self._physical(row);self._check_pidfd(row,live=True)
            value=row['manager'].snapshot()
            if value['MainPID']!=row['producer_identity']['pid']:raise Conflict('original keeper no longer live before G')
            pipe=os.fstat(row['producer'].stdin.fileno())
            if [pipe.st_dev,pipe.st_ino]!=row['stdin_identity']:raise Conflict('original G transport changed')
            owner._check_release_gate(runtime)
            runtime['release_entered']=True  # Never resend after lost return.
            if os.write(row['producer'].stdin.fileno(),b'G')!=1:raise Conflict('original G write UNKNOWN')

    def poll(self,source):
        row=self._issued(source)
        with self._lock:
            if row['status']=='CLOSED':return row['receipt'] or self._observation(row)
            self._physical(row);self._read_protocol(row)
            closed=row['task_closed'];runtime=row['runtime']
            if closed is not None:
                if closed['stopped']['release_attempted'] and not runtime['release_entered']:
                    raise Conflict('original task released without Core G intent')
                if runtime['release_entered'] and closed['stopped']['release_attempted'] and row['runtime_ack'] is None:
                    # Terminal trusted keeper observation proves G consumed; NOT
                    # a ready receipt or task stdout claimed as a started ACK.
                    row['runtime_ack']=_RuntimeStartedObservation(source,canonical({
                        'source_id':source.id,'lease_sha256':hashlib.sha256(runtime['lease'].raw).hexdigest(),
                        'event':closed,'started_observation':'TRUSTED_TASK_TERMINAL_AFTER_G'}))
                row['status']='TASK_TERMINAL_OBSERVED'
            return self._observation(row)

    def seal(self,source):return self.poll(source)

    def _cleanup_attempt(self,row):
        self._actual()
        owner=row.get('runtime_owner')
        if owner is not None and owner._original_source(row['runtime']) is not row:
            raise PermissionError('original service cleanup scope differs')
        errors=[];manager=row.get('manager');process=row['producer'];proof=None
        def attempt(label,operation):
            try:return operation()
            except BaseException as exc:errors.append((label,exc));return None
        if not row['launch_entered']:
            if manager is not None:attempt('manager_close',manager.close)
            attempt('source_close',lambda:super(LocalCpuSourceOwner,self)._cleanup_attempt(row))
        else:
            # Independent participants. A broken control/report source MUST
            # NOT prevent STOP on the already bound original Invocation.
            if process is None:errors.append(('transport',Conflict('original service handoff UNKNOWN; no adoption')))
            else:
                def close_control():
                    if process.stdin is not None and not process.stdin.closed:
                        info=os.fstat(process.stdin.fileno())
                        if [info.st_dev,info.st_ino]!=row['stdin_identity']:
                            raise Conflict('original service STOP control identity differs')
                        process.stdin.close()
                attempt('control_eof',close_control)
                def observe_task():
                    end=time.monotonic()+1
                    while row['task_closed'] is None and time.monotonic()<end:
                        self._read_protocol(row)
                        if row['task_closed'] is None:select.select([process.stdout],[],[],.02)
                attempt('trusted_task_report',observe_task)
            if manager is not None and manager.bound is not None:
                proof=attempt('original_manager_stop',manager.stop)
            else:errors.append(('manager_binding',Conflict('original manager scope UNKNOWN; no adoption')))
            def kernel_terminal():
                if self._kernel_terminals.get(id(row)) is row:return
                self._check_pidfd(row,live=False)
                if not select.select([row['fds']['pidfd']],[],[],3)[0]:
                    raise Conflict('original keeper kernel terminal UNKNOWN')
                self._kernel_terminals[id(row)]=row
            attempt('original_keeper_terminal',kernel_terminal)
            if process is not None:
                attempt('transport_reap',lambda:process.wait(timeout=3))
                if row['task_closed'] is None and process.stdout is not None and not process.stdout.closed:
                    attempt('final_trusted_report',lambda:self._read_protocol(row))
                def close_protocol():
                    if process.stdout is not None and not process.stdout.closed:
                        info=os.fstat(process.stdout.fileno())
                        if [info.st_dev,info.st_ino]!=row['protocol_identity']:
                            raise Conflict('original protocol close identity differs')
                        process.stdout.close()
                attempt('protocol_close',close_protocol)
            if manager is not None:attempt('manager_close',manager.close)
            # Never use inherited participant signalling: producer is a
            # transport, pidfd belongs to keeper. Close each held source only.
            for name,fd in tuple(row['fds'].items()):
                if fd is None:continue
                def close_source(name=name,fd=fd):
                    if name=='pidfd':self._check_pidfd(row,live=False)
                    else:
                        info=os.fstat(fd)
                        if [info.st_dev,info.st_ino]!=row['identities'].get(self._source_file(name)):
                            raise Conflict('original configured CPU cleanup FD reused')
                    os.close(fd);row['fds'][name]=None
                attempt('source_'+name,close_source)
            if (row['task_closed'] is None or row['protocol_tail'] or proof is None or
                    self._kernel_terminals.get(id(row)) is not row or process is None or process.poll() is None or
                    not process.stdin.closed or not process.stdout.closed or manager is None or not manager.closed):
                errors.append(('full_scope',Conflict('original managed terminal incomplete')))
            if not errors:
                row['managed_terminal']={**proof,'keeper_kernel_terminal':True,
                    'transport_reaped':True,'transport_status':process.returncode,
                    'original_protocol_closed':True,'original_manager_connection_closed':manager.closed,
                    'task_closed':row['task_closed']}
                row['status']='CLOSED'
        if errors:
            row['status']='UNKNOWN'
            error=Conflict('original configured CPU partial cleanup retained')
            for label,exc in errors:error.add_note(label+': '+repr(exc))
            raise error from errors[0][1]

    def shutdown_safety(self):
        """Retire only original parent handles; UNKNOWN is never terminal/FREE."""
        from .hybrid_usage_source import _registry,_owners
        self._actual()
        with _registry,self._lock:
            errors=[]
            for row in self._attempts.values():
                try:self._cleanup_attempt(row)
                except BaseException as exc:
                    manager=row.get('manager');process=row['producer']
                    parent_closed=(all(fd is None for fd in row['fds'].values()) and
                        (manager is None or manager.closed) and
                        (process is None or process.poll() is not None and process.stdin.closed and process.stdout.closed))
                    physically_known=(process is None or manager is not None and manager.stopped_raw is not None and
                                      self._kernel_terminals.get(id(row)) is row)
                    if not parent_closed or not physically_known:errors.append(exc)
            if errors:raise errors[0]
            self._live=False;_owners.pop(id(self),None)
        return {'state':'ORIGINAL_PARENT_CLOSED_EXPOSURE_UNKNOWN','runtime_stopped':False,
                'settlement_enabled':False,'refund_enabled':False}
