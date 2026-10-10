"""Pure publication integrity checks, not original grants or crash qualification."""
from copy import deepcopy
import hashlib
import json
import os

import pytest

from rlflow.hybrid_goals import digest
from rlflow.hybrid_local_cpu_recovery import recover,validate_source
from rlflow.hybrid_protocol import ProtocolError
from rlflow.hybrid_runtime_boundary import directory_chain
from rlflow.store import Conflict
from rlflow.hybrid_local_runner_signature import Signer,verify


@pytest.fixture
def publication(tmp_path):
    tmp_path.chmod(0o700)
    task={'pid':123,'starttime':'45','source_sha256':'a'*64,'sandbox':'CPU_LOCAL_LANDLOCK_SECCOMP'}
    keeper={'pid':124,'starttime':'46','boot_id':'12345678-1234-1234-1234-123456789012',
        'invocation_id':'b'*32}
    stopped={'control_terminal_reason':'CONTROL_EOF','cpu_stat':'','handoff_unknown':False,
        'keeper_still_live':True,'memory_peak':0,'protocol_cleanup_unknown':False,
        'reaped':[{'pid':123,'status':9}],'release_attempted':True,'stop_latched':True,
        'task_empty':True,'whole_scope_stopped':False}
    closed={'type':'local_cpu.task_closed','config_sha256':'c'*64,'keeper':keeper,'task':task,
        'stopped':stopped,'closed':{'keeper_protocol_handles_closed':True,'stop_latched':True,
            'task_handles_closed':True,'whole_scope_stopped':False},
        'original_output_fds_closed':True,'original_control_fd_closed':True,'whole_scope_stopped':False}
    report={'format':'local_cpu_recovery/1','task_closed':closed,
        'outputs':{name:hashlib.sha256(raw).hexdigest() for name,raw in [('stdout',b'original\n'),('stderr',b'')]}}
    signer=Signer();public_key=signer.public_key
    try:report['signature']=signer.sign(report)
    finally:signer.close()
    bodies={'task-report':json.dumps(report).encode()+b'\n','task-stdout':b'original\n','task-stderr':b''}
    for name,body in bodies.items():
        path=tmp_path/name;path.write_bytes(body);path.chmod(0o600)
    source={'source_id':'original_source','path':str(tmp_path),'chain':directory_chain(tmp_path),
        'config_sha256':'c'*64,'unit':'rlflow-local-'+'d'*32+'.service',
        'files':{name:[(tmp_path/name).stat().st_dev,(tmp_path/name).stat().st_ino,os.geteuid()] for name in bodies}}
    spec={'purpose':'research','code':'not executed','inputs':{},'seconds':20,
        'limits':{'memory_max':67108864,'cpu_max':'100000 100000','pids_max':12},
        'acceptance':{'method':'EXACT_STDOUT_UTF8','stdout':'original\n','stderr_empty':True}}
    runtime={'phase':'RELEASE_INTENT','local_cpu_recovery_public_key':public_key,
        'producer':{key:keeper[key] for key in ('pid','starttime','boot_id')},
        'origin':{'lease_id':'lease','local_cpu':{'code_sha256':'sha256:'+'a'*64,'spec_sha256':digest(spec)}}}
    return tmp_path,source,runtime,spec,report


@pytest.mark.parametrize('body',[b'',b'{"partial":',b'{}'])
def test_incomplete_publication_never_recovers_evidence(publication,body):
    path,source,runtime,spec,_=publication
    (path/'task-report').write_bytes(body)
    assert recover(source,runtime,spec) is None


@pytest.mark.parametrize('mutation',['config','keeper','code','phase','output','duplicate','extra','replacement','symlink','chain','paired','fifo'])
def test_closed_original_source_and_report_required(publication,mutation):
    path,source,runtime,spec,report=publication
    if mutation=='config':report['task_closed']['config_sha256']='e'*64
    elif mutation=='keeper':report['task_closed']['keeper']['starttime']='99'
    elif mutation=='code':report['task_closed']['task']['source_sha256']='e'*64
    elif mutation=='phase':runtime['phase']='PROCESS_REGISTERED'
    elif mutation=='output':(path/'task-stdout').write_bytes(b'forged\n')
    elif mutation=='extra':report['controls_available']=True
    elif mutation=='chain':source['chain'][-1][1]+=1
    elif mutation=='paired':
        (path/'task-stdout').write_bytes(b'forged\n')
        report['outputs']['stdout']=hashlib.sha256(b'forged\n').hexdigest()
        report['task_closed']['stopped']['reaped'][0]['status']=0
        report['task_closed']['stopped']['control_terminal_reason']='PRODUCER_EXIT'
    elif mutation=='fifo':
        (path/'task-stdout').unlink();os.mkfifo(path/'task-stdout',0o600)
    elif mutation in ('replacement','symlink'):
        (path/'task-stdout').rename(path/'old-output')
        if mutation=='symlink':(path/'task-stdout').symlink_to(path/'old-output')
        else:(path/'task-stdout').write_bytes(b'original\n');(path/'task-stdout').chmod(0o600)
    if mutation=='duplicate':
        raw=json.dumps(report).encode().removesuffix(b'}')+b',"format":"local_cpu_recovery/1"}\n'
    else:raw=json.dumps(report).encode()+b'\n'
    (path/'task-report').write_bytes(raw)
    descriptors=set(os.listdir('/proc/self/fd'))
    with pytest.raises((Conflict,ProtocolError,OSError)):recover(source,runtime,spec)
    assert set(os.listdir('/proc/self/fd'))==descriptors


def test_synthetic_publication_only_recovers_task_not_managed_scope(publication):
    _,source,runtime,spec,_=publication
    value=recover(source,runtime,spec)
    assert value['configured_local_result']['machine_acceptance']['status']=='FAIL'
    assert value['managed_scope_status']=='UNKNOWN'
    assert value['physical_scope_status']=='UNKNOWN' and value['physical_scope_proof'] is None
    assert not value['controls_available'] and not value['condition_evidence']
    assert not value['settlement_performed'] and not value['execution_replayed']


def test_legacy_no_original_public_key_is_not_upgraded(publication):
    _,source,runtime,spec,_=publication
    del runtime['local_cpu_recovery_public_key']
    assert recover(source,runtime,spec) is None


def test_signature_uses_only_original_public_key_and_covers_full_payload():
    signer=Signer();other=Signer();payload={'format':'local_cpu_recovery/1','data':'original'}
    try:
        signature=signer.sign(payload)
        assert verify(signer.public_key,payload,signature)
        assert not verify(other.public_key,payload,signature)
        assert not verify(signer.public_key,{**payload,'data':'forged'},signature)
    finally:signer.close();other.close()


def test_report_read_close_failure_attempts_other_original_descriptors(publication,monkeypatch):
    _,source,runtime,spec,_=publication;original=os.close;retained=[];closed=[]
    def fault(fd):
        info=os.fstat(fd)
        if [info.st_dev,info.st_ino,info.st_uid]==source['files']['task-report']:
            retained.append(fd);raise OSError(5,'one original close failed')
        closed.append(fd);original(fd)
    with monkeypatch.context() as patch:
        patch.setattr(os,'close',fault)
        with pytest.raises(Conflict,match='descriptor cleanup failed') as caught:recover(source,runtime,spec)
    assert retained and len(closed)>=2
    assert caught.value.original_recovery_fds[0][1]==retained[0]
    original(retained[0])


@pytest.mark.parametrize('mutation',['relative','traversal','bool','alias','extra'])
def test_source_descriptor_closed_and_bounded(publication,mutation):
    _,source,_,_,_=publication;source=deepcopy(source)
    if mutation=='relative':source['path']='relative'
    elif mutation=='traversal':source['path']+='/../work'
    elif mutation=='bool':source['files']['task-report'][1]=True
    elif mutation=='alias':source['files']['task-report']=source['files']['task-stdout']
    else:source['replay']=True
    with pytest.raises((Conflict,ProtocolError)):validate_source(source)
