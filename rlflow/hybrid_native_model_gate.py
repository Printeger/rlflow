"""Fixed packet-only same-PID native gate; runtime launch remains DENIED.

No credential acquisition or caller command. Uses one hash-pinned existing
kernel helper. Ready is sandbox proof only, never account/model/usage proof.
"""
import fcntl
import hashlib
import json
import os
import re
import resource
import select
import signal
import stat
import sys

HELPER_SHA256 = '7321930320afbbd1451f0dcef669826fd5263a215f71cd162697aa18204ecb31'
FIELDS = {'role','model','effort','workspace_id','seconds','packet_sha256',
          'output_schema_sha256','binary_sha256'}
DISABLED = ('shell_tool','unified_exec','apply_patch_freeform','view_image','js_repl',
    'code_mode','code_mode_only','code_mode_host','apps','plugins','multi_agent',
    'multi_agent_v2','collab','hooks','codex_hooks','plugin_hooks','shell_snapshot',
    'shell_snapshot_v2','browser_use','computer_use','image_generation','imagegenext',
    'memory_tool','memories','skill_search','skill_mcp_dependency_install',
    'remote_control','search_tool','tool_suggest','request_permissions_tool',
    'request_rule','goals','worktrees','codex_git_commit','standalone_web_search',
    'web_search','tool_search','sleep_tool','send_message_to_user_async',
    'deferred_executor','token_budget','current_time_reminder','recommended_plugins')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode('utf-8')


def unique(pairs):
    result = {}
    for key,value in pairs:
        if key in result:raise RuntimeError('duplicate frozen launch key')
        result[key] = value
    return result


def validate(config):
    if (type(config) is not dict or set(config) != FIELDS or
            config['role'] not in ('Engineer','Evaluator') or config['model'] != 'gpt-6.1-sol' or
            config['effort'] not in ('medium','high') or type(config['seconds']) is not int or
            not 1 <= config['seconds'] <= 300 or type(config['workspace_id']) is not str or
            re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',config['workspace_id']) is None or
            any(type(config[k]) is not str or re.fullmatch('sha256:[0-9a-f]{64}',config[k]) is None
                for k in ('packet_sha256','output_schema_sha256','binary_sha256'))):
        raise RuntimeError('closed original generating launch config required')
    return config


def command(home,work,schema_fd,config):
    """Data only. Explicit env has no API/proxy/account-switch fallback."""
    validate(config)
    argv = ['codex','exec','--ignore-user-config','--ignore-rules','--ephemeral',
        '--skip-git-repo-check','--sandbox','read-only','--json','-C',work,
        '-m','gpt-6.1-sol','--output-schema','/proc/self/fd/'+str(schema_fd)]
    settings = {'approval_policy':'never','model_provider':'openai',
        'model_reasoning_effort':config['effort'],'forced_login_method':'chatgpt',
        'forced_chatgpt_workspace_id':config['workspace_id'],
        'project_doc_max_bytes':0,'allow_login_shell':False,'web_search':'disabled',
        'skills.include_instructions':False,'skills.bundled.enabled':False,
        'tools.update_plan.enabled':False,'tools.experimental_request_user_input.enabled':False,
        'features.skip_host_skill_discovery':True,'history.persistence':'none',
        'feedback.enabled':False,'analytics.enabled':False}
    settings.update({'features.'+feature:False for feature in DISABLED})
    for key,value in settings.items():
        argv.extend(['-c',key+'='+json.dumps(value,separators=(',',':'))])
    argv.append('-')
    return argv,{'HOME':home,'CODEX_HOME':home,'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
        'CUDA_VISIBLE_DEVICES':'','NVIDIA_VISIBLE_DEVICES':'none','TMPDIR':work}


def material(fd,bound):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != 0o600 or
            fcntl.fcntl(fd,fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY or
            not 0 < info.st_size <= bound):
        raise RuntimeError('original private readonly bounded gate material required')
    raw = os.pread(fd,bound+1,0)
    after = os.fstat(fd)
    fields = lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
    if len(raw) != info.st_size or fields(info) != fields(after):
        raise RuntimeError('frozen gate material changed')
    return raw


def helper(fd):
    raw = material(fd,16384)
    if hashlib.sha256(raw).hexdigest() != HELPER_SHA256:
        raise RuntimeError('fixed hash-pinned kernel helper required')
    namespace = {'__name__':'rlflow_hash_pinned_gate_helper'}
    exec(compile(raw,'<hash-pinned-native-kernel-helper>','exec'),namespace)
    return namespace


def sealed_copy(fd,raw):
    """Freeze consumed bytes in kernel, not a mutable mode-0600 disk file."""
    writable = os.memfd_create('rlflow-native-packet',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    readonly = None
    try:
        if os.write(writable,raw) != len(raw):raise RuntimeError('sealed packet copy incomplete')
        seals = fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL
        fcntl.fcntl(writable,fcntl.F_ADD_SEALS,seals)
        readonly = os.open('/proc/self/fd/'+str(writable),os.O_RDONLY|os.O_CLOEXEC)
        os.dup2(readonly,fd,inheritable=False)
    finally:
        if readonly is not None:os.close(readonly)
        os.close(writable)


def run(parent,nonce,binary_fd,ready_fd,config_fd,packet_fd,schema_fd,helper_fd):
    if (os.getppid() != parent or re.fullmatch('[0-9a-f]{32}',nonce) is None or
            len({binary_fd,ready_fd,config_fd,packet_fd,schema_fd,helper_fd}) != 6 or
            any(fd < 3 for fd in (binary_fd,ready_fd,config_fd,packet_fd,schema_fd,helper_fd))):
        raise RuntimeError('original parent and distinct gate descriptors required')
    kernel = helper(helper_fd)
    libc = kernel['ctypes'].CDLL(None,use_errno=True)
    kernel['check'](libc.prctl(1,signal.SIGKILL,0,0,0))
    if os.getppid() != parent:raise RuntimeError('original owner died')
    raw = material(config_fd,8192)
    config = validate(json.loads(raw,object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('nonfinite launch config'))))
    if canonical(config) != raw:raise RuntimeError('canonical original launch config required')
    packet = material(packet_fd,60000); schema = material(schema_fd,8192)
    if any('sha256:'+hashlib.sha256(data).hexdigest() != config[field]
           for data,field in ((packet,'packet_sha256'),(schema,'output_schema_sha256'))):
        raise RuntimeError('approved packet/schema material differs')
    sealed_copy(packet_fd,packet); sealed_copy(schema_fd,schema)
    binary = kernel['native_identity'](binary_fd)
    if binary['binary_sha256'] != config['binary_sha256']:
        raise RuntimeError('approved original native ELF differs')
    control = os.path.dirname(os.readlink('/proc/self/fd/'+str(config_fd)))
    if os.readlink('/proc/self/fd/'+str(config_fd)) != control+'/launch.json':
        raise RuntimeError('original launch namespace required')
    home = control+'/auth-private'; work = control+'/work'
    argv,env = command(home,work,schema_fd,config)
    for fd in (binary_fd,config_fd,packet_fd,helper_fd,ready_fd):os.set_inheritable(fd,False)
    os.set_inheritable(schema_fd,True)
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(config['seconds']+5,config['seconds']+5))
    os.chdir(work)
    directories = kernel['restrict'](binary_fd,home,work)
    ready = {'type':'model.sandbox.ready','pid':os.getpid(),'nonce':nonce,
        'config_sha256':'sha256:'+hashlib.sha256(raw).hexdigest(),
        'packet_sha256':config['packet_sha256'],'output_schema_sha256':config['output_schema_sha256'],
        'helper_sha256':'sha256:'+HELPER_SHA256,'role':config['role'],
        'single_tgid':True,'landlock':True,'no_new_privs':True,
        'packet_sealed':True,'schema_sealed':True,
        'network_enforcement':'PARTIAL','account_qualified':False,**binary,**directories}
    receipt = canonical(ready)+b'\n'
    if os.write(ready_fd,receipt) != len(receipt):raise RuntimeError('original ready write incomplete')
    os.fsync(ready_fd)
    for fd in (ready_fd,config_fd,helper_fd):os.close(fd)
    if not select.select([0],[],[],20)[0] or os.read(0,1) != b'G':raise SystemExit(126)
    # G/control input is never model context. The original immutable packet is
    # a distinct read-only FD, positioned independently of prior pread checks.
    os.lseek(packet_fd,0,os.SEEK_SET); os.dup2(packet_fd,0); os.close(packet_fd)
    signal.alarm(config['seconds'])
    os.execve('/proc/self/fd/'+str(binary_fd),argv,env)


if __name__ == '__main__':
    if len(sys.argv) != 10 or sys.argv[3] != 'native_model':raise SystemExit(126)
    run(int(sys.argv[1]),sys.argv[2],*map(int,sys.argv[4:]))
