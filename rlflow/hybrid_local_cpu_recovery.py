"""Original pre-dispatch publication recovery; no STOP, settlement or replay."""
import hashlib
import json
import os
from pathlib import Path
import stat

from .hybrid_protocol import obj,ID,validate_schema
from .hybrid_local_cpu_result import COUNT,HEX,UNIT,TASK_CLOSED,execution_from_closed,evaluate_execution,validate_result
from .hybrid_runtime_boundary import _held_chain,_stamp
from .store import Conflict

NUMBER={'type':'integer','minimum':0,'maximum':2**64-1}
INODE={'type':'array','minItems':3,'maxItems':3,'items':NUMBER}
SOURCE=obj({'source_id':ID,'path':{'type':'string','minLength':1,'maxLength':4096},
    'chain':{'type':'array','minItems':1,'maxItems':64,'items':INODE},
    'config_sha256':HEX,'unit':UNIT,
    'files':obj({name:INODE for name in ('task-report','task-stdout','task-stderr')})})
REPORT=obj({'format':{'const':'local_cpu_recovery/1'},'task_closed':TASK_CLOSED,
    'signature':{'type':'string','pattern':'^[0-9a-f]{128}$'},
    'outputs':obj({name:{'oneOf':[HEX,{'type':'null'}]} for name in ('stdout','stderr')})})


def validate_source(value):
    validate_schema(SOURCE,value)
    path=Path(value['path'])
    if (not path.is_absolute() or '..' in path.parts or '\x00' in value['path'] or
            len(value['chain'])!=len(path.parts) or
            len({tuple(row[:2]) for row in value['files'].values()})!=3):
        raise Conflict('closed original recovery namespace required')


def _pairs(rows):
    value={}
    for key,item in rows:
        if key in value:raise Conflict('duplicate original recovery report key')
        value[key]=item
    return value


def recover(source,runtime,spec,libcrypto_sha256=None):
    """Bounded read of exact originals, never recreates original live handles."""
    validate_source(source)
    public_key=runtime.get('local_cpu_recovery_public_key')
    if public_key is None:return None
    with _held_chain(Path(source['path'])) as (directories,chain):
        if chain!=source['chain']:raise Conflict('original recovery ancestors changed')
        info=os.fstat(directories[-1])
        if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise Conflict('private original recovery namespace required')
        opened={};cleanup_identities={}
        try:
            for name in source['files']:
                fd=os.open(name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=directories[-1])
                opened[name]=fd;cleanup_identities[name]=None
                info=os.fstat(fd);cleanup_identities[name]=[info.st_dev,info.st_ino,info.st_uid]
                if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or
                        stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or
                        [info.st_dev,info.st_ino,info.st_uid]!=source['files'][name]):
                    raise Conflict('original recovery file identity changed')
            report_fd=opened['task-report'];before=_stamp(os.fstat(report_fd))
            raw=os.pread(report_fd,32769,0)
            # Empty/incomplete publication is not durable trusted task evidence.
            if not raw or not raw.endswith(b'\n'):return None
            if len(raw)>32768 or len(raw)!=before[2]:raise Conflict('bounded original recovery report required')
            try:report=json.loads(raw,object_pairs_hook=_pairs)
            except (ValueError,UnicodeError) as exc:raise Conflict('original recovery report invalid') from exc
            validate_schema(REPORT,report)
            from .hybrid_local_runner_signature import verify
            payload={key:item for key,item in report.items() if key!='signature'}
            if not verify(public_key,payload,report['signature'],libcrypto_sha256):
                raise Conflict('original recovery signature differs')
            closed=report['task_closed'];producer=runtime['producer'];origin=runtime['origin']
            if (producer is None or closed['config_sha256']!=source['config_sha256'] or
                    any(closed['keeper'][key]!=producer[key] for key in ('pid','starttime','boot_id')) or
                    closed['task']['source_sha256']!=origin['local_cpu']['code_sha256'].removeprefix('sha256:') or
                    closed['stopped']['release_attempted'] and runtime['phase'] not in
                        ('RELEASE_INTENT','STARTED_AS_OBSERVED','STOP_REQUESTED','FIXTURE_SCOPE_STOPPED')):
                raise Conflict('original recovery task/config/phase differs')
            outputs={};available=closed['stopped']['release_attempted']
            for name in ('stdout','stderr'):
                fd=opened['task-'+name];stamp=_stamp(os.fstat(fd));raw=os.pread(fd,65537,0)
                seal=report['outputs'][name]
                if seal is None:
                    available=False
                elif (len(raw)>65536 or len(raw)!=stamp[2] or hashlib.sha256(raw).hexdigest()!=seal):
                    raise Conflict('original recovery output hash differs')
                else:
                    try:body=raw.decode()
                    except UnicodeError:available=False
                    else:outputs[name]={'text':body,'sha256':'sha256:'+seal}
                if _stamp(os.fstat(fd))!=stamp:raise Conflict('original recovery output changed during read')
            if _stamp(os.fstat(report_fd))!=before:raise Conflict('original recovery publication changed during read')
            # Ensure the selected paths still designate the held originals.
            for name,fd in opened.items():
                info=os.stat(name,dir_fd=directories[-1],follow_symlinks=False)
                if _stamp(info)!=_stamp(os.fstat(fd)):raise Conflict('original recovery path changed during read')
            result=None
            if available:
                execution=execution_from_closed(closed['task'],closed['stopped'])
                result={'lease_id':origin['lease_id'],'source_id':source['source_id'],'task':closed['task'],
                    'outputs':outputs,'approved_spec_sha256':origin['local_cpu']['spec_sha256'],
                    'approved_acceptance':spec.get('acceptance'),
                    'machine_acceptance':evaluate_execution(spec.get('acceptance'),outputs,execution),
                    'execution':execution,'independent_review_status':'NOT_PROVEN','condition_evidence':False}
                validate_result(result,origin,closed['task'],closed['stopped'],spec)
            return {'status':'ORIGINAL_TASK_EVIDENCE_RECOVERED','configured_local_result':result,
                'task_closed':closed,'managed_scope_status':'UNKNOWN','controls_available':False,
                'condition_evidence':False,'execution_replayed':False,'settlement_performed':False}
        finally:
            failures=[]
            for name,fd in opened.items():
                try:
                    info=os.fstat(fd)
                    if cleanup_identities[name] is None or [info.st_dev,info.st_ino,info.st_uid]!=cleanup_identities[name]:
                        raise OSError('original recovery descriptor identity uncertain')
                    os.close(fd)
                except OSError as exc:failures.append((name,fd,cleanup_identities[name],exc))
            if failures:
                error=Conflict('original recovery descriptor cleanup failed')
                error.original_recovery_fds=failures
                raise error
