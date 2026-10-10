"""Fixed same-PID native diagnostic gate. Never a caller command executor.

Only Linux x86_64; failure of either kernel restriction aborts before G/exec.
Stdout belongs to the eventual CLI; sandbox receipt has a distinct original FD.
"""
import ctypes
import errno
import hashlib
import json
import os
import platform
import resource
import select
import signal
import stat
import sys

NATIVE='/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex'


def native_identity(binary_fd):
    """The fixed root-owned installed ELF, never any caller-selected FD."""
    descriptors=[os.open('/',os.O_PATH|os.O_DIRECTORY|os.O_CLOEXEC)]
    try:
        for part in NATIVE.split('/')[1:-1]:
            descriptors.append(os.open(part,os.O_PATH|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=descriptors[-1]))
        for fd in descriptors:
            info=os.fstat(fd)
            if info.st_uid!=0 or info.st_mode&0o022:raise RuntimeError('immutable root-owned native installation required')
        original=os.stat('codex',dir_fd=descriptors[-1],follow_symlinks=False)
        info=os.fstat(binary_fd)
        fields=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_uid,value.st_mode)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or
                fields(original)!=fields(info) or not 0<info.st_size<=512*1024**2 or os.pread(binary_fd,4,0)!=b'\x7fELF'):
            raise RuntimeError('fixed original native ELF FD required')
        value=hashlib.sha256();offset=0
        while offset<info.st_size:
            raw=os.pread(binary_fd,min(1024**2,info.st_size-offset),offset)
            if not raw:raise RuntimeError('native ELF truncated')
            value.update(raw);offset+=len(raw)
        if fields(os.fstat(binary_fd))!=fields(info):raise RuntimeError('native ELF changed')
        return {'binary_identity':[info.st_dev,info.st_ino],'binary_sha256':'sha256:'+value.hexdigest()}
    finally:
        for fd in reversed(descriptors):os.close(fd)


def native_command(home,work,port):
    """One closed, credential-free local diagnostic policy, no caller options."""
    if type(port) is not int or not 1<=port<=65535:raise RuntimeError('original local receiver port required')
    argv=['codex','exec','--ignore-user-config','--ignore-rules','--ephemeral',
        '--skip-git-repo-check','--sandbox','read-only','--json','-C',work,'-m','rlflow-local-non-generating']
    config={'approval_policy':'never','model_reasoning_effort':'medium','project_doc_max_bytes':0,
        'allow_login_shell':False,'web_search':'disabled','skills.include_instructions':False,
        'skills.bundled.enabled':False,'model_catalog_json':home+'/catalog.json',
        'tools.update_plan.enabled':False,'tools.experimental_request_user_input.enabled':False,
        'model_provider':'rlflow_diagnostic','model_providers.rlflow_diagnostic.name':'Local non-model diagnostic',
        'model_providers.rlflow_diagnostic.base_url':f'http://127.0.0.1:{port}/v1',
        'model_providers.rlflow_diagnostic.wire_api':'responses',
        'model_providers.rlflow_diagnostic.requires_openai_auth':False,
        'model_providers.rlflow_diagnostic.request_max_retries':0,
        'model_providers.rlflow_diagnostic.stream_max_retries':0,
        'features.enable_request_compression':False,'features.skip_host_skill_discovery':True}
    for feature in ('shell_tool','unified_exec','apply_patch_freeform','view_image','js_repl','code_mode',
        'code_mode_only','code_mode_host','apps','plugins','multi_agent','multi_agent_v2','collab',
        'hooks','codex_hooks','plugin_hooks','shell_snapshot','shell_snapshot_v2','browser_use',
        'computer_use','image_generation','imagegenext','memory_tool','memories','skill_search',
        'skill_mcp_dependency_install','remote_control','search_tool','tool_suggest',
        'request_permissions_tool','request_rule','goals','worktrees','codex_git_commit',
        'standalone_web_search','web_search','tool_search','sleep_tool','send_message_to_user_async',
        'deferred_executor','token_budget','current_time_reminder','recommended_plugins'):
        config['features.'+feature]=False
    for key,value in config.items():argv.extend(['-c',key+'='+json.dumps(value,separators=(',',':'))])
    argv.append('Local non-generating diagnostic. No model or tool work.')
    env={'HOME':home,'CODEX_HOME':home,'PATH':'/usr/bin:/bin','LANG':'C.UTF-8',
        'CUDA_VISIBLE_DEVICES':'','NVIDIA_VISIBLE_DEVICES':'none','TMPDIR':work}
    return argv,env


def check(value):
    if value < 0: raise OSError(ctypes.get_errno(), 'native diagnostic restriction failed')
    return value


def restrict(binary_fd, home, work):
    if platform.machine() != 'x86_64': raise RuntimeError('unsupported syscall ABI')
    libc = ctypes.CDLL(None, use_errno=True)
    if check(libc.syscall(444, 0, 0, 1)) < 3: raise RuntimeError('Landlock ABI >=3 required')
    class Ruleset(ctypes.Structure):
        _fields_ = [('rights', ctypes.c_uint64)]
    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('rights', ctypes.c_uint64), ('fd', ctypes.c_int)]
    handled = (1 << 15) - 1
    value = Ruleset(handled)
    rules = check(libc.syscall(444, ctypes.byref(value), ctypes.sizeof(value), 0))
    directories={}
    try:
        entries = [(binary_fd, 1 | 4)]
        opened = []
        try:
            for path in ('/usr/lib', '/usr/lib64', '/lib', '/lib64', '/usr/share',
                         '/etc/ld.so.cache', '/etc/localtime', '/proc/self'):
                if os.path.exists(path):
                    fd = os.open(path, os.O_PATH | os.O_CLOEXEC); opened.append(fd)
                    entries.append((fd, 4 | (8 if os.path.isdir(path) else 0)))
            for path in ('/dev/null', '/dev/zero', '/dev/urandom'):
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC); opened.append(fd)
                entries.append((fd, 2 | 4))
            for path in (home, work):
                fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC); opened.append(fd)
                info=os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
                    raise RuntimeError('original private diagnostic directory required')
                directories['home_identity' if path==home else 'work_identity']=[info.st_dev,info.st_ino,info.st_uid,stat.S_IMODE(info.st_mode)]
                entries.append((fd, handled & ~(1 | (1 << 6) | (1 << 9) | (1 << 11))))
            for fd, rights in entries:
                rule = Beneath(rights, fd)
                check(libc.syscall(445, rules, 1, ctypes.byref(rule), 0))
            check(libc.prctl(38, 1, 0, 0, 0))
            check(libc.syscall(446, rules, 0))
        finally:
            for fd in opened: os.close(fd)
    finally: os.close(rules)
    # Explicit ABI fence, including x32. No new TGID, namespaces, ptrace,
    # io_uring or alternate-ABI process creation. clone3 ENOSYS permits libc's
    # normal thread fallback; clone is permitted ONLY with CLONE_THREAD.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                   ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, 0xc000003e), (6, 0, 0, 0x80000000),
                    (0x20, 0, 0, 0), (0x45, 0, 1, 0x40000000), (6, 0, 0, 0x80000000)]
    for number in (57, 58, 101, 310, 311, 438, 424, 425, 426, 427, 272, 308,
                   165, 166, 155, 161, 321, 323, 304, 62, 200):
        instructions.extend([(0x15, 0, 1, number), (6, 0, 0, 0x50000 | errno.EPERM)])
    instructions.extend([(0x15, 0, 1, 435), (6, 0, 0, 0x50000 | errno.ENOSYS),
                         (0x15, 0, 4, 56), (0x20, 0, 0, 16),
                         (0x45, 1, 0, 0x10000), (6, 0, 0, 0x50000 | errno.EPERM),
                         (6, 0, 0, 0x7fff0000), (6, 0, 0, 0x7fff0000)])
    array = (Filter * len(instructions))(*(Filter(*row) for row in instructions))
    program = Program(len(instructions), array)
    check(libc.prctl(22, 2, ctypes.byref(program), 0, 0))
    return directories


def run(parent, nonce, binary_fd, ready_fd, config_fd):
    if os.getppid() != parent or len(nonce) != 32: raise RuntimeError('original gate owner required')
    libc = ctypes.CDLL(None, use_errno=True)
    check(libc.prctl(1, signal.SIGKILL, 0, 0, 0))
    if os.getppid() != parent: raise RuntimeError('original gate owner died')
    raw = os.pread(config_fd, 32769, 0)
    if len(raw) > 32768: raise RuntimeError('fixed config bound exceeded')
    config = json.loads(raw)
    control=os.path.dirname(os.readlink('/proc/self/fd/'+str(config_fd)))
    home=control+'/auth-empty';work=control+'/work'
    argv,env=native_command(home,work,config['port'])
    if config!={'home':home,'work':work,'port':config['port'],'argv':argv,'env':env}:
        raise RuntimeError('closed original local diagnostic config required')
    binary=native_identity(binary_fd)
    os.close(config_fd)
    # The binary FD and receipt do NOT survive exec. /proc/self/fd identifies
    # the original held ELF at exec, not a mutable pathname or wrapper.
    os.set_inheritable(binary_fd, False); os.set_inheritable(ready_fd, False)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    os.chdir(config['work'])
    directories=restrict(binary_fd, config['home'], config['work'])
    receipt = {'type': 'diagnostic.sandbox.ready', 'pid': os.getpid(), 'nonce': nonce,
               'config_sha256': hashlib.sha256(raw).hexdigest(), 'single_tgid': True,
               'landlock': True, 'no_new_privs': True, 'network_enforcement': 'PARTIAL',
               **binary,**directories}
    os.write(ready_fd, json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()+b'\n')
    os.fsync(ready_fd); os.close(ready_fd)
    if not select.select([0], [], [], 20)[0] or os.read(0, 1) != b'G': raise SystemExit(126)
    fd = os.open('/dev/null', os.O_RDONLY); os.dup2(fd, 0); os.close(fd)
    signal.alarm(20)  # Survives exec; finite safety bound even after lost return.
    os.execve('/proc/self/fd/'+str(binary_fd), config['argv'], config['env'])


if __name__ == '__main__':
    if len(sys.argv) != 7 or sys.argv[3]!='native_diagnostic': raise SystemExit(126)
    run(int(sys.argv[1]), sys.argv[2], *map(int, sys.argv[4:]))
