"""Closed zero-model diagnostic profile and original protected Runtime owner.

This does NOT authorize CodexExecAdapter.start or WorkingPlanService.start.
An isolated local rejecting receiver supplies no model/token/cost evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from .hybrid_fixture_runtime import FixtureRuntimeOwner
from .hybrid_fixture_materials import _read_bounded
from .hybrid_goals import digest
from .hybrid_protocol import HASH, ID, obj
from .hybrid_reads import ReadBudget
from .hybrid_runtime_boundary import _held_chain, directory_chain
from .store import Conflict, canonical, PREPARATION_READ_BYTES

PROFILE = 'FIXED_NATIVE_LOCAL_DIAGNOSTIC_V1'
KIND = 'LOCAL_NATIVE_DIAGNOSTIC'
AUTHORIZATION = 'LOCAL_NON_GENERATING_DIAGNOSTIC_ONLY'
BINARY = Path('/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex')
PACKAGE = BINARY.parents[3] / 'package.json'
LIMITS = {'mode':'native_local_diagnostic','enforcement':'partial',
          'single_tgid_enforcement':'SECCOMP_X86_64_NO_NEW_PROCESS',
          'execute_enforcement':'LANDLOCK_ORIGINAL_ELF_ONLY',
          'network_enforcement':'PARTIAL','command_seconds':20,'output_bytes':1024**2}
BINDING = obj({'profile':{'const':PROFILE},'binary_sha256':HASH,
    'evaluator_sha256':HASH,'command_sha256':HASH,'resource_sha256':HASH,
    'grant_id':ID,'proposal_hash':HASH,'approval_hash':HASH,'config_hash':HASH,'scope_hash':HASH})


@dataclass(frozen=True, eq=False)
class NativeDiagnosticGrant:
    id: str
    raw: bytes


def _stamp(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def pin_binary():
    """Fixed installed root-owned ELF only; no caller path or wrapper process."""
    with _held_chain(BINARY.parent) as (fds,chain):
        for fd in fds:
            info=os.fstat(fd)
            if info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:
                raise Conflict('native installation ancestors must be root-owned immutable to user')
        fd=os.open(BINARY.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fds[-1])
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or not 0<info.st_size<=512*1024**2:
            raise Conflict('fixed bounded root-owned native ELF required')
        if os.pread(fd,4,0)!=b'\x7fELF':raise Conflict('native ELF required, not Node wrapper')
        value=hashlib.sha256();offset=0
        while offset<info.st_size:
            raw=os.pread(fd,min(1024**2,info.st_size-offset),offset)
            if not raw:raise Conflict('native binary truncated')
            value.update(raw);offset+=len(raw)
        if _stamp(os.fstat(fd))!=_stamp(info):raise Conflict('native binary changed during pin')
        return {'fd':fd,'stamp':_stamp(info),'chain':chain,'sha256':'sha256:'+value.hexdigest()}
    except BaseException:
        os.close(fd);raise


def check_binary(row):
    fd=row['fd']
    if fd is None or os.get_inheritable(fd) or _stamp(os.fstat(fd))!=row['stamp']:
        raise Conflict('original native ELF FD changed')
    if directory_chain(BINARY.parent)!=row['chain'] or _stamp(BINARY.stat(follow_symlinks=False))!=row['stamp']:
        raise Conflict('original native ELF installation changed')


def registration(program_sha256,evaluator_sha256,binary_sha256):
    definition={'profile':PROFILE,'program_sha256':program_sha256,
                'evaluator_sha256':evaluator_sha256,'binary_sha256':binary_sha256,'limits':LIMITS}
    return deepcopy({'tool':{'adapter':'fixed_native_local_diagnostic','definition':definition},
        'command':{'tool_id':'native_diagnostic','argv':[PROFILE],
            'parameter_schema':{'type':'object','properties':{},'additionalProperties':False},
            'network':'allowlist','allowed_hosts':['127.0.0.1']},
        'rule':{'definition':definition,'requires_datasets':False},
        'resources':{'fixed_native_local_diagnostic':definition,**LIMITS}})


def approved_binding(proposal,config,program_sha256,evaluator_sha256,binary_sha256):
    expected=registration(program_sha256,evaluator_sha256,binary_sha256)
    if (proposal['goal_kind']!='engineering' or proposal['risk']!='low' or
            proposal['allowed_tools']!=['native_diagnostic'] or
            proposal['scope']['allowed_command_templates']!=['native_diagnostic'] or
            proposal['scope']['network_access']!='allowlist' or proposal['scope']['allowed_hosts']!=['127.0.0.1'] or
            proposal['evaluation_data']!={'mode':'EXPLICIT_NONE','datasets':[],
                'evaluation_rule':{'id':'native_diagnostic_rule','version_hash':digest(expected['rule'])}} or
            config['tools'].get('native_diagnostic')!=expected['tool'] or
            config['commands'].get('native_diagnostic')!=expected['command'] or
            config['evaluation_rules'].get('native_diagnostic_rule')!=expected['rule'] or
            config['resource_profile']!=expected['resources'] or
            any(proposal['budget'][name]!=0 for name in ('model_sessions','model_input_tokens','model_output_tokens',
                'gpu_device_seconds','experiment_starts','experiment_retries'))):
        raise Conflict('exact original zero-model native local diagnostic approval required')
    return {'profile':PROFILE,'binary_sha256':binary_sha256,'evaluator_sha256':evaluator_sha256,
            'command_sha256':digest(expected['command']),'resource_sha256':digest(expected['resources'])}


class NativeDiagnosticOwner(FixtureRuntimeOwner):
    """Separate closed authority kind; shared original Budget/Pool writers."""
    def _actual(self):
        if type(self) is not NativeDiagnosticOwner:raise PermissionError('exact native diagnostic owner required')
        super()._actual()

    def _issued(self,lease):
        attempt=super()._issued(lease)
        if attempt['origin']['kind']!=KIND or attempt.get('diagnostic_grant') is None or canonical(attempt['origin'])!=lease.raw:
            raise PermissionError('native diagnostic owner cannot operate another kind')
        return attempt

    def check_guard(self,db,guard):
        self._issued(guard.attempt['lease'])
        return super().check_guard(db,guard)

    def issue_cpu_trial_grant(self,*args,**kwargs):raise PermissionError('closed native diagnostic owner')
    def issue_engineering_patch_grant(self,*args,**kwargs):raise PermissionError('closed native diagnostic owner')

    def _binding(self,loaded,binary_sha256):
        evaluator=Path(__file__)
        return approved_binding(loaded['record']['contract']['proposal'],json.loads(self.plans.registry._raw),
            self.program_hash,'sha256:'+hashlib.sha256(_read_bounded(evaluator,16384)).hexdigest(),binary_sha256)

    def issue_diagnostic_grant(self,bundle,token,observation):
        self._actual();self.controller._issued(token);self._plan_original(bundle,token,observation)
        row=pin_binary()
        try:
            with self.pool._lock,self.store.read_connection() as db:
                db.execute('BEGIN');read=ReadBudget(db,PREPARATION_READ_BYTES)
                loaded=self.budget._load(db,self._ready_for_bundle(bundle)['request']['goal_ref'],read)
                binding=self._binding(loaded,row['sha256'])
                binding.update({k:loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
                with self._lock:
                    if len(self._diagnostic_grants)>=32:raise Conflict('finite diagnostic grants exceeded')
                    key='diagnostic_grant_'+uuid.uuid4().hex;binding['grant_id']=key
                    grant=NativeDiagnosticGrant(key,canonical(binding))
                    self._diagnostic_grants[id(grant)]={'grant':grant,'bundle':bundle,'token':token,
                        'observation':observation,'attempt':None}
                    return grant
        finally:os.close(row['fd'])

    def _issued_diagnostic_grant(self,grant,bundle,token,observation):
        self._actual();row=self._diagnostic_grants.get(id(grant))
        if (type(grant) is not NativeDiagnosticGrant or row is None or row['grant'] is not grant or
                any(row[k] is not v for k,v in (('bundle',bundle),('token',token),('observation',observation)))):
            raise PermissionError('original same-plan diagnostic grant required')
        return row

    def _fresh_diagnostic(self,loaded,attempt):
        grant=attempt['diagnostic_grant'];row=self._issued_diagnostic_grant(grant,attempt['bundle'],attempt['token'],attempt['observation'])
        expected=self._binding(loaded,json.loads(grant.raw)['binary_sha256'])
        expected.update(grant_id=grant.id,**{k:loaded[k] for k in ('proposal_hash','approval_hash','config_hash','scope_hash')})
        if row['attempt'] is not attempt or canonical(expected)!=grant.raw:raise Conflict('current original diagnostic approval changed')
        if attempt['source'] is not None:
            with self.sources._lock:self.sources._physical(self.sources._issued(attempt['source']))

    def _terminal_scope(self):return 'FIXED_NATIVE_SINGLE_TGID'

    def start(self,lease):
        attempt=self._issued(lease)
        if attempt.get('source_stop_latched') or attempt.get('physical_safety_freeze') or self._safety_freeze:
            raise Conflict('original native diagnostic canceled; no START after physical STOP')
        return super().start(lease)

    def _check_terminal(self,attempt):
        retained=self._retained_source(attempt)
        if retained is not None and (retained['status']!='CLOSED' or
                any(fd is not None for fd in retained['fds'].values()) or retained.get('server') is not None or
                retained.get('server_thread') is not None and retained['server_thread'].is_alive() or
                retained.get('accepted') is not None and (retained['accepted'][1] is None or retained['accepted'][0].fileno()>=0) or
                retained['producer'] is not None and (retained['producer'].poll() is None or
                    retained['producer'].stdin is not None and not retained['producer'].stdin.closed)):
            raise Conflict('original diagnostic partial allocation not fully closed; retain UNKNOWN')
        super()._check_terminal(attempt)
        source=None if attempt['source'] is None else self.sources._issued(attempt['source'])
        if source is not None and (source.get('server') is not None or
                source.get('server_thread') is not None and source['server_thread'].is_alive()):
            raise Conflict('original diagnostic receiver not completely closed')
        if attempt['terminal']!={
                'scope':self._terminal_scope(),'lease_id':attempt['lease'].id,
                'program_sha256':attempt['origin']['program_sha256'],'producer':attempt['producer_identity'],
                'all_original_source_fds_closed':True,'original_participant_reaped':True,
                **self._terminal_extra(attempt),'arbitrary_tree_stop':False,
                'wall_seconds':attempt['terminal']['wall_seconds'],'synthetic_tokens_settled':False}:
            raise Conflict('original diagnostic terminal proof differs')

    def _retained_source(self,attempt):
        self.sources._actual()
        row=self.sources._attempts.get(id(attempt['claim']))
        if row is not None and (row['claim'] is not attempt['claim'] or row['membership'] is not self.membership or
                row['scenario']!='runtime.native_diagnostic' or
                row['runtime'] is not None and row['runtime'] is not attempt or
                row['runtime'] is None and (row.get('native_allocation_entered') or row['launch_entered'])):
            raise PermissionError('original same-claim retained diagnostic allocation required')
        return row

    def _stop_original_participant(self,lease):
        attempt=self._issued(lease)
        if attempt['source'] is None:
            # Allocation/return failure cannot discard the Source owner's
            # original strongly retained row and FREE its still-open listener.
            with self.pool._lock,self._lock,self.sources._lock:
                retained=self._retained_source(attempt)
                if retained is not None:self.sources._cleanup_attempt(retained)
        return super()._stop_original_participant(lease)

    def _terminal_extra(self,attempt):
        source=None if attempt['source'] is None else self.sources._issued(attempt['source'])
        receipt=None if source is None else self.sources._sandbox_ready(attempt['source'])
        if attempt['release_entered'] and receipt is None:
            raise Conflict('native single-TGID restriction proof missing; retain UNKNOWN')
        ready=receipt is not None
        return {'new_process_creation_denied':ready,'native_release_attempted':attempt['release_entered'],
            'participant_proof':'ORIGINAL_KERNEL_FILTER' if ready else 'PRE_EXEC_FIXED_GATE_NO_RELEASE',
            'network_enforcement':'PARTIAL',
            'binary_sha256':json.loads(attempt['diagnostic_grant'].raw)['binary_sha256'],
            'sandbox_receipt_sha256':None if receipt is None else digest(json.loads(receipt.raw))}

    def poll(self,lease,*,seal=False):
        value=super().poll(lease,seal=seal)
        value.update(fixed_cpu_scope_only=False,native_execution_enabled=False,
            local_native_diagnostic=True,scope='FIXED_NATIVE_SINGLE_TGID',model_access_verified=False)
        return value

    def stop_to_terminal(self,lease):
        value=super().stop_to_terminal(lease)
        value.update(fixed_cpu_scope_only=False,local_native_diagnostic=True,scope='FIXED_NATIVE_SINGLE_TGID')
        return value

