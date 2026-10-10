"""No-G real kernel gate tests. NEVER execute Codex or read credentials."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rlflow import hybrid_native_model_gate as gate
from rlflow.hybrid_native_diagnostic import pin_binary


def digest(raw):return 'sha256:'+hashlib.sha256(raw).hexdigest()


@pytest.fixture
def materials(tmp_path):
    tmp_path.chmod(0o700)
    for name in ('auth-private','work'):(tmp_path/name).mkdir(mode=0o700)
    binary=pin_binary(); descriptors=[binary['fd']]
    packet=b'{"objective":"Implement the frozen engineering requirement"}'
    schema=b'{"type":"object","additionalProperties":false}'
    config=dict(role='Engineer',model='gpt-6.1-sol',effort='medium',
        workspace_id='12345678-1234-1234-1234-123456789012',seconds=10,
        packet_sha256=digest(packet),output_schema_sha256=digest(schema),binary_sha256=binary['sha256'])
    rawhelper=Path(gate.__file__).with_name('hybrid_native_diagnostic_gate.py').read_bytes()
    try:
        items={}
        for key,name,raw in (('ready','ready.jsonl',b''),('config','launch.json',gate.canonical(config)),
                ('packet','packet.json',packet),('schema','schema.json',schema),('helper','helper.py',rawhelper)):
            path=tmp_path/name;path.write_bytes(raw);path.chmod(0o600)
            flags=os.O_WRONLY|os.O_APPEND if key=='ready' else os.O_RDONLY
            fd=os.open(path,flags|os.O_CLOEXEC|os.O_NOFOLLOW);descriptors.append(fd);items[key]=fd
        yield tmp_path,binary,items,config
    finally:
        for fd in reversed(descriptors):os.close(fd)


def invoke(materials):
    _,binary,items,_=materials
    argv=[sys.executable,'-B','-I','-S',gate.__file__,str(os.getpid()),'a'*32,'native_model',
          str(binary['fd']),*[str(items[k]) for k in ('ready','config','packet','schema','helper')]]
    # Closed stdin sends EOF, NEVER G. Even the real kernel positive cannot
    # reach native exec/model/auth. Original child has a bounded timeout.
    return subprocess.run(argv,input=b'',stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        pass_fds=(binary['fd'],*items.values()),env={'PATH':'/usr/bin:/bin'},timeout=10)


def test_actual_gate_ready_without_g_exits_before_native_exec(materials):
    path,_,_,config=materials
    result=invoke(materials)
    assert result.returncode==126,(result.stdout,result.stderr)
    assert result.stdout==b'' and result.stderr==b''
    ready=json.loads((path/'ready.jsonl').read_bytes())
    assert ready['type']=='model.sandbox.ready' and ready['pid']!=os.getpid()
    assert ready['packet_sha256']==config['packet_sha256']
    assert ready['output_schema_sha256']==config['output_schema_sha256']
    assert ready['landlock'] and ready['no_new_privs'] and ready['single_tgid']
    assert ready['packet_sealed'] and ready['schema_sealed']
    assert not ready['account_qualified']
    assert list((path/'auth-private').iterdir())==[]
    assert list((path/'work').iterdir())==[]


@pytest.mark.parametrize('kind',['packet','helper','config','binary'])
def test_wrong_frozen_material_never_reaches_ready_or_exec(materials,kind):
    path,_,_,config=materials
    if kind=='packet':(path/'packet.json').write_bytes(b'{}')
    elif kind=='helper':(path/'helper.py').write_bytes(b'raise AssertionError("must not execute")')
    elif kind=='binary':
        config['binary_sha256']='sha256:'+'0'*64
        (path/'launch.json').write_bytes(gate.canonical(config))
    else:
        config['argv']=['forbidden']
        (path/'launch.json').write_bytes(gate.canonical(config))
    result=invoke(materials)
    assert result.returncode!=0 and result.stdout==b''
    assert (path/'ready.jsonl').read_bytes()==b''
    assert list((path/'auth-private').iterdir())==[]


def test_command_has_closed_env_and_no_claimed_retry_override(materials):
    _,_,items,config=materials
    argv,env=gate.command('/private/auth-private','/private/work',items['schema'],config)
    assert argv[-1]=='-' and '--output-schema' in argv
    assert '-m' in argv and argv[argv.index('-m')+1]=='gpt-6.1-sol'
    settings=dict(value.split('=',1) for flag,value in zip(argv,argv[1:]) if flag=='-c')
    assert json.loads(settings['forced_login_method'])=='chatgpt'
    assert json.loads(settings['forced_chatgpt_workspace_id'])==config['workspace_id']
    assert all(json.loads(settings['features.'+name]) is False for name in gate.DISABLED)
    assert set(env)=={'HOME','CODEX_HOME','PATH','LANG','CUDA_VISIBLE_DEVICES','NVIDIA_VISIBLE_DEVICES','TMPDIR'}
    assert 'resume' not in argv
    # Absence of an override is NOT proof of zero native-provider retries.
    assert not any('retry' in key or 'base_url' in key for key in settings)


def test_kernel_sealed_copy_cannot_mutate_or_grow(materials):
    path,_,items,_=materials
    original=(path/'packet.json').read_bytes()
    gate.sealed_copy(items['packet'],original)
    with pytest.raises(OSError):os.write(items['packet'],b'changed')
    writable=os.open('/proc/self/fd/'+str(items['packet']),os.O_RDWR)
    try:
        with pytest.raises(OSError):os.write(writable,b'changed')
        with pytest.raises(OSError):os.ftruncate(writable,len(original)+1)
    finally:os.close(writable)
    seals=fcntl.fcntl(items['packet'],fcntl.F_GET_SEALS)
    assert seals & fcntl.F_SEAL_WRITE
    assert os.pread(items['packet'],len(original),0)==original
