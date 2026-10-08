"""CPU tool isolation. Fail closed; never falls back to an unrestricted shell.

Codex receives only the cpu_exec MCP tool. Its subprocess uses Linux Landlock
(read, write AND execute) plus seccomp, independent of Codex's write sandbox.
No model command is executed inside the trusted MCP server process.
"""
from __future__ import annotations
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import sys
import tempfile
import time

CODEX = '/usr/local/bin/codex'
PINNED_VERSION = '0.161.0'
ROLES = ('PI', 'Critic', 'Designer', 'Engineer', 'Evaluator', 'Scout')
ROOT = Path(__file__).resolve().parents[1]

class IsolationError(RuntimeError):
    pass


def _check(result: int, name: str) -> int:
    if result < 0:
        raise IsolationError(f'{name}: {os.strerror(ctypes.get_errno())}')
    return result


def _restrict(read_roots: list[str], write_roots: list[str], execute_paths: list[str] | None = None) -> None:
    """Called in a disposable process before exec; an exception aborts launch."""
    if platform.machine() != 'x86_64':
        raise IsolationError('Only tested Linux x86_64 syscall ABI is enabled')
    libc = ctypes.CDLL(None, use_errno=True)
    abi = _check(libc.syscall(444, 0, 0, 1), 'landlock ABI')
    if abi < 3:
        raise IsolationError('Landlock ABI >= 3 required for truncate protection')
    # EXECUTE, WRITE_FILE, READ_FILE, READ_DIR ... REFER, TRUNCATE.
    handled = (1 << 15) - 1
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int)]
    rs = Ruleset(handled)
    fd = _check(libc.syscall(444, ctypes.byref(rs), ctypes.sizeof(rs), 0), 'landlock create')
    try:
        entries: dict[str, int] = {}
        # Only system CPU tools have executable permission. Candidate binaries may
        # be read by Python/bash, but cannot introduce a new executable directly.
        for p in ['/usr/bin', '/usr/lib', '/usr/lib64', '/lib', '/lib64']:
            if Path(p).exists(): entries[str(Path(p).resolve())] = 4 | 8
        for name in ('bash','sh','python3','git','cat','ls','pwd','echo','printf','head','tail',
                     'wc','sort','uniq','cut','tr','sed','grep','rg','find','diff','cmp','cp','mv',
                     'mkdir','rmdir','rm','touch','date','sleep','true','false','env','test',
                     'xargs','timeout','basename','dirname','readlink','stat','sha256sum'):
            p = Path('/usr/bin')/name
            if p.exists(): entries[str(p.resolve())] = 1 | 4
        for p in ['/lib64/ld-linux-x86-64.so.2', '/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2']:
            if Path(p).exists(): entries[str(Path(p).resolve())] = 1 | 4
        for p in ['/usr/share', '/etc/ld.so.cache', '/etc/localtime']:
            if Path(p).exists(): entries[str(Path(p).resolve())] = 4 | (8 if Path(p).is_dir() else 0)
        for p in read_roots:
            q = Path(p).resolve(strict=True)
            entries[str(q)] = entries.get(str(q), 0) | 4 | (8 if q.is_dir() else 0)
        for p in execute_paths or []:
            q = Path(p).resolve(strict=True)
            if not (q.is_file() or q.is_dir()):
                raise IsolationError('Additional executable root must be a regular file or directory')
            entries[str(q)] = entries.get(str(q), 0) | 1 | 4 | (8 if q.is_dir() else 0)
        # Device whitelist deliberately excludes GPU/DRI/kfd and /proc.
        for p in ['/dev/null', '/dev/zero', '/dev/urandom']:
            entries[p] = 2 | 4
        for p in write_roots:
            q = Path(p).resolve(strict=True)
            # No execute, make-device or Unix-socket creation rights.
            rights = (handled & ~(1 | (1 << 6) | (1 << 9) | (1 << 11))) if q.is_dir() else (2 | 4 | (1 << 14))
            entries[str(q)] = entries.get(str(q), 0) | rights
        for p, rights in entries.items():
            pf = os.open(p, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = Beneath(rights, pf)
                _check(libc.syscall(445, fd, 1, ctypes.byref(rule), 0), f'landlock add {p}')
            finally: os.close(pf)
        _check(libc.prctl(38, 1, 0, 0, 0), 'no_new_privs')
        _check(libc.syscall(446, fd, 0), 'landlock restrict')
    finally: os.close(fd)
    # Deny networking (including Unix control sockets), namespace escape,
    # process inspection/signalling and process-group escape. The supervisor
    # remains outside this filter and kills the complete owned group.
    sec = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    sec.seccomp_init.argtypes = [ctypes.c_uint32]
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    sec.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    sec.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = sec.seccomp_init(0x7fff0000)
    if not ctx: raise IsolationError('seccomp_init failed')
    try:
        for name in ('socket','socketpair','connect','bind','listen','accept','accept4',
                     'ptrace','process_vm_readv','process_vm_writev','pidfd_getfd',
                     'kill','tkill','tgkill','pidfd_send_signal','setsid','setpgid',
                     'mount','umount2','pivot_root','chroot','unshare','setns',
                     'bpf','userfaultfd','io_uring_setup','open_by_handle_at','ioctl','memfd_create','execveat',
                     'reboot','kexec_load','init_module','finit_module',
                     'chmod','fchmod','fchmodat','fchmodat2','chown','fchown','lchown','fchownat',
                     'utime','utimes','futimesat','utimensat','setxattr','lsetxattr','fsetxattr',
                     'removexattr','lremovexattr','fremovexattr'):
            num = sec.seccomp_syscall_resolve_name(name.encode())
            if num >= 0 and sec.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, num, 0) != 0:
                raise IsolationError('seccomp rule failed: ' + name)
        if sec.seccomp_load(ctx) != 0: raise IsolationError('seccomp_load failed')
    finally: sec.seccomp_release(ctx)


def _command_writers_quiescent(directory, timeout=3):
    """Never remove control files while the independent guardian can write."""
    from .jobs import owns
    def valid_identity(record):
        return (isinstance(record,dict) and set(record)=={'pid','pgid','starttime','boot_id'}
                and all(type(record[k]) is int and 0<record[k]<2**31 for k in ('pid','pgid'))
                and isinstance(record['starttime'],str) and record['starttime'].isascii()
                and record['starttime'].isdigit() and 0<len(record['starttime'])<=20
                and isinstance(record['boot_id'],str)
                and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',record['boot_id']) is not None)
    ready=directory/'lifeguard-ready.json';request=directory/'lifeguard-request.json'
    if not request.exists():return True
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            guardian=json.loads(ready.read_text())['identity']
            supervisor=json.loads(request.read_text())['owner']
            if not valid_identity(guardian) or not valid_identity(supervisor):return False
            if not owns(guardian) and not owns(supervisor):return True
        except (OSError,ValueError,KeyError,TypeError):
            pass  # Missing or ambiguous identity is not permission to delete.
        time.sleep(.01)
    return False


def cpu_exec(command: str, candidate: str | Path, scratch: str | Path,
             role: str, *, timeout: float = 60, read_extra: list[str] | None = None,
             write_roots: list[str] | None = None,
             execute_extra: list[str] | None = None,
             memory_bytes: int = 2 * 1024**3, command_seconds: int = 120, artifact_dir: Path | None = None) -> dict:
    if role not in ROLES: raise IsolationError('Unknown role')
    if not isinstance(command, str) or len(command) > 100000:
        raise IsolationError('Command must be a string <= 100000 characters')
    if type(command_seconds) is not int or not 1 <= command_seconds <= 1800:
        raise IsolationError('Invalid authorized command limit')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= command_seconds:
        raise IsolationError(f'Tool timeout must be within (0, {command_seconds}] seconds')
    if type(memory_bytes) is not int or not 2 * 1024**3 <= memory_bytes <= 16 * 1024**3:
        raise IsolationError('CPU address-space limit must be an integer from 2 to 16 GiB')
    candidate = Path(candidate).resolve(strict=True)
    scratch = Path(scratch).resolve(strict=True)
    if candidate == scratch or candidate in scratch.parents or scratch in candidate.parents:
        raise IsolationError('Candidate and scratch must be separate directory trees')
    if artifact_dir is None:
        # Create trusted control artifacts in the CALLER, before giving the
        # sandbox TMPDIR=scratch. The independent guardian must never accept
        # role-writable identity/done/release files. A killed caller leaves its
        # private diagnostic directory for recovery rather than deleting it
        # underneath the still-running guardian.
        private=Path(tempfile.mkdtemp(prefix='rlflow-command-private-'))
        try:
            return cpu_exec(command,candidate,scratch,role,timeout=timeout,
                            read_extra=read_extra,write_roots=write_roots,execute_extra=execute_extra,
                            memory_bytes=memory_bytes,command_seconds=command_seconds,
                            artifact_dir=private)
        finally:
            if _command_writers_quiescent(private/'process'):
                import shutil
                shutil.rmtree(private)
    writes = [str(scratch)]
    if role == 'Engineer':
        writes += write_roots if write_roots is not None else [str(candidate)]
    for p in writes:
        q = Path(p).resolve(strict=True)
        if q != scratch and q != candidate and candidate not in q.parents:
            raise IsolationError('Write root outside candidate/scratch')
    env = {'PATH':'/usr/bin:/bin', 'HOME':str(scratch), 'TMPDIR':str(scratch),
           'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1',
           'CUDA_VISIBLE_DEVICES':'','NVIDIA_VISIBLE_DEVICES':'none',
           'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
    cfg = {'read':[str(candidate),str(scratch)] + (read_extra or []),'write':writes,
           'execute': execute_extra or [],
           'memory_bytes': memory_bytes,
           'command':command,'timeout':timeout}
    if artifact_dir is not None:cfg['guard_directory']=str(Path(artifact_dir).resolve()/'process')
    # The module is read by the trusted launcher before restricting itself.
    argv = [sys.executable, '-I', str(Path(__file__).resolve()), '_supervised', json.dumps(cfg)]
    t = time.monotonic()
    timed_out = False
    if artifact_dir is not None:
        artifact_dir=Path(artifact_dir).resolve()
        if artifact_dir.is_relative_to(candidate) or artifact_dir.is_relative_to(scratch):
            raise IsolationError('Command artifacts must be outside role writable storage')
        for allowed in (read_extra or []) + (execute_extra or []):
            path=Path(allowed).resolve(strict=True)
            if path==artifact_dir or path in artifact_dir.parents or path.is_relative_to(artifact_dir):
                raise IsolationError('Extra access cannot include trusted command artifacts')
    with (open(artifact_dir/'stdout.log','x+b') if artifact_dir else tempfile.TemporaryFile()) as out, (open(artifact_dir/'stderr.log','x+b') if artifact_dir else tempfile.TemporaryFile()) as err:
        p = subprocess.Popen(argv, cwd=scratch, env=env, stdin=subprocess.DEVNULL,
                             stdout=out, stderr=err, start_new_session=True)
        if artifact_dir:
            fields=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()
            checkpoint={'pid':p.pid,'pgid':p.pid,'starttime':fields[19],
                        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'argv':argv}
            with (artifact_dir/'identity.json').open('x') as record:
                json.dump(checkpoint,record);record.flush();os.fsync(record.fileno())
        try:
            p.wait(timeout=timeout+2)
        except subprocess.TimeoutExpired:
            timed_out = True
            p.terminate()
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        finally:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        def tail(stream):
            stream.seek(0,2)
            stream.seek(max(0,stream.tell()-100000))
            return stream.read()
        stdout, stderr = tail(out), tail(err)
    sandbox_error=Path(cfg['guard_directory'])/'sandbox-error.json' if cfg.get('guard_directory') else None
    infrastructure_error='CPU_SANDBOX_SETUP_FAILED' if sandbox_error and sandbox_error.exists() else None
    return {'infrastructure_error':infrastructure_error,'command':command,'argv':['/bin/bash','--noprofile','--norc','-c',command],
            'cwd':str(scratch),'exit_code':p.returncode,'timed_out':timed_out or p.returncode==124,
            'wall_seconds':round(time.monotonic()-t,6),
            'stdout':stdout.decode(errors='replace')[-100000:],
            'stderr':stderr.decode(errors='replace')[-100000:]}


def tool_context_valid(value):
    """Provenance pointer only; this does NOT grant release/command authority."""
    return (isinstance(value, dict) and set(value) == {'schema_version','session','generation','request_sha256','candidate_sha256'}
            and value['schema_version'] == '1.0'
            and all(isinstance(value[k], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', value[k])
                    for k in ('session','generation'))
            and all(isinstance(value[k], str) and re.fullmatch(r'[0-9a-f]{64}', value[k])
                    for k in ('request_sha256','candidate_sha256')))


def tool_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def tool_return_observation(intent, result):
    """Fixed private return fact, never command/output text or model activity.

    An intent alone does not prove launch. A return can be a sandbox setup
    failure; no STARTED/RUNNING or process termination claim is inferred here.
    Public collectors must independently bind the committed release/request.
    """
    import math
    if not tool_context_valid(intent.get('tool_context')):
        raise IsolationError('Invalid tool context')
    code, elapsed = result.get('exit_code'), result.get('wall_seconds')
    if (type(code) is not int or not -2**31 <= code < 2**31 or type(result.get('timed_out')) is not bool
            or type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed < 0
            or result.get('infrastructure_error') not in (None,'CPU_SANDBOX_SETUP_FAILED')):
        raise IsolationError('Invalid CPU return metadata')
    state = ('SETUP_FAILED' if result.get('infrastructure_error') else
             'TIMED_OUT' if result['timed_out'] else 'RETURNED')
    return {'schema_version':'1.0','kind':'CPU_EXEC_RETURN','tool':'cpu_exec',
            'context':intent['tool_context'],'intent_sha256':tool_digest(intent),
            'result_sha256':tool_digest(result),'state':state,'exit_code':code,
            'timed_out':result['timed_out'],'wall_seconds':elapsed,
            'infrastructure_error':result.get('infrastructure_error')}


def persistent_cpu_exec(config, args):
    """An explicit command ID is a checkpoint, not permission to rerun an unknown launch."""
    import uuid
    command_id = args.get('command_id', uuid.uuid4().hex)
    if not isinstance(command_id, str) or not command_id or len(command_id) > 200:
        raise IsolationError('Invalid command ID')
    context = config.get('tool_context')
    if context is not None and not tool_context_valid(context):
        raise IsolationError('Invalid tool context')
    digest = hashlib.sha256(json.dumps({'id': command_id}, sort_keys=True).encode()).hexdigest()
    path = Path(config['audit']).parent / 'commands' / digest
    path.mkdir(parents=True, exist_ok=True)
    intent = {'command_id': command_id, 'command': args['command'], 'timeout': args.get('timeout',60),
              'candidate': config['candidate'], 'role': config['role'],
              'permissions': {k:config.get(k) for k in ('write_roots','read_extra','execute_extra','command_seconds')}}
    if context is not None:
        intent.update(tool_context=context,scratch=config['scratch'],memory_bytes=config.get('memory_bytes',2*1024**3))
    def save(name, value):
        raw = json.dumps(value, sort_keys=True).encode()
        tmp = path / (name + '.' + uuid.uuid4().hex)
        with tmp.open('xb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path / name)
        fd=os.open(path, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    import fcntl
    def record_return(value):
        if context is None:return
        observation = tool_return_observation(intent,value)
        name = 'return-observation.json'
        if (path/name).exists():
            if json.loads((path/name).read_text()) != observation:
                raise IsolationError('CPU return observation mismatch')
        else:save(name,observation)
    with (path/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (path/'intent.json').exists():
            if json.loads((path/'intent.json').read_text()) != intent:
                raise IsolationError('Command ID content mismatch')
            if (path/'result.json').exists():
                value = json.loads((path/'result.json').read_text())
                record_return(value)
                return value
            raise IsolationError('Command outcome unknown; inspect checkpoint, do not re-execute')
        save('intent.json', intent)
        value = cpu_exec(args['command'], config['candidate'], config['scratch'], config['role'],
                         timeout=args.get('timeout',60), read_extra=config.get('read_extra'),
                         write_roots=config.get('write_roots'), execute_extra=config.get('execute_extra'),
                         memory_bytes=config.get('memory_bytes',2*1024**3),
                         command_seconds=config.get('command_seconds',120), artifact_dir=path)
        value['checkpoint'] = str(path)
        if context is not None:tool_return_observation(intent,value)
        save('result.json', value)
        record_return(value)
        return value


def _serve(config: dict) -> None:
    """Minimal newline-delimited MCP stdio server, fixed tool and no resources."""
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            ident, method = request.get('id'), request.get('method')
            with open(config['audit']+'.transport', 'a') as trace:
                trace.write(json.dumps({'method':method})+'\n')
            if ident is None: continue
            if method == 'initialize':
                result = {'protocolVersion':request.get('params',{}).get('protocolVersion','2024-11-05'),
                          'capabilities':{'tools':{}},'serverInfo':{'name':'rlflow-cpu','version':'1'}}
            elif method == 'tools/list':
                result = {'tools':[{'name':'cpu_exec','description':'Run bounded CPU bash command. Read candidate; write only assigned workspace. No network, GPU, runtime, control plane or nested agents.',
                    'inputSchema':{'type':'object','properties':{'command':{'type':'string'},'timeout':{'type':'number','minimum':1,'maximum':config.get('command_seconds',120)},'command_id':{'type':'string'}},'required':['command'],'additionalProperties':False}}]}
            elif method == 'tools/call':
                params = request['params']
                if params['name'] != 'cpu_exec': raise IsolationError('Unknown tool')
                args = params.get('arguments',{})
                if set(args)-{'command','timeout','command_id'}: raise IsolationError('Unknown argument')
                value = persistent_cpu_exec(config, args)
                with open(config['audit'], 'a') as log: log.write(json.dumps(value,ensure_ascii=False)+'\n')
                result = {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}], 'isError':False}
            elif method == 'ping': result = {}
            elif method in ('resources/list','resources/templates/list','prompts/list'):
                result = { {'resources/list':'resources','resources/templates/list':'resourceTemplates','prompts/list':'prompts'}[method]:[] }
            else:
                print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'unsupported method'}}),flush=True);continue
            print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
        except Exception as exc:
            print(json.dumps({'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,
                              'error':{'code':-32000,'message':str(exc)}}),flush=True)


def codex_command(role: str, candidate: str | Path, scratch: str | Path,
                  schema: str | Path, output: str | Path, *,
                  read_extra: list[str] | None = None, write_roots: list[str] | None = None,
                  execute_extra: list[str] | None = None,
                  memory_bytes: int = 2 * 1024**3,
                  model: str = 'gpt-5.6-sol', effort: str = 'medium', command_seconds: int = 120,
                  _census_catalog: dict | None = None,
                  tool_context: dict | None = None) -> tuple[list[str], dict[str,str]]:
    """Return argv/env; caller writes prompt to stdin and captures JSONL stdout.

    Output's parent is trusted control storage; it MUST be disjoint from role
    writable paths. It stores the MCP config, audit and constrained catalog.
    """
    if role not in ROLES: raise IsolationError('Unknown role')
    if tool_context is not None and not tool_context_valid(tool_context):raise IsolationError('Invalid tool context')
    candidate, scratch, output = (Path(p).resolve() for p in (candidate,scratch,output))
    trusted = output.parent
    for p in (candidate,scratch):
        if trusted == p or p in trusted.parents: raise IsolationError('Control output overlaps role workspace')
    trusted.mkdir(parents=True,exist_ok=True)
    scratch.mkdir(parents=True,exist_ok=True)
    version = subprocess.run([CODEX,'--version'],capture_output=True,text=True,timeout=10)
    if version.returncode or PINNED_VERSION not in version.stdout.split():
        raise IsolationError('Codex version does not match '+PINNED_VERSION)
    if _census_catalog is None:
        cache = Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'models_cache.json'
        catalog = json.loads(cache.read_text())
    else:
        # Only the local rejecting census uses a synthetic catalog. It must never
        # be a fallback for a real account/model missing from the operator cache.
        catalog = json.loads(json.dumps(_census_catalog))
    models = [m for m in catalog['models'] if m['slug']==model]
    if not models: raise IsolationError('Requested model absent from local Codex model catalog')
    if effort not in {x['effort'] for x in models[0].get('supported_reasoning_levels', [])}:
        raise IsolationError('Requested reasoning effort is not supported by selected model')
    for m in models:
        m.update(shell_type='disabled',apply_patch_tool_type=None,
                 experimental_supported_tools=[],supports_search_tool=False,
                 include_skills_usage_instructions=False,include_plugin_usage_instructions=False,
                 include_apps_usage_instructions=False,tool_mode='direct',multi_agent_version='disabled')
    catalog_path = trusted/(output.name+'.models.json')
    catalog_path.write_text(json.dumps({'models':models}))
    config_path = trusted/(output.name+'.mcp.json')
    tool_config = {'role':role,'candidate':str(candidate),'scratch':str(scratch),
        'read_extra':read_extra or [],'write_roots':write_roots,
        'execute_extra':execute_extra or [],'memory_bytes':memory_bytes,'command_seconds':command_seconds,
        'audit':str(trusted/(output.name+'.commands.jsonl'))}
    if tool_context is not None:tool_config['tool_context'] = tool_context
    config_path.write_text(json.dumps(tool_config))
    argv = [CODEX,'exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
            '--sandbox','workspace-write','-C',str(scratch),'--json','--output-schema',str(Path(schema).resolve()),
            '--output-last-message',str(output),'-m',model]
    config = {'model_reasoning_effort':effort,'use_legacy_landlock':True,'approval_policy':'never','project_doc_max_bytes':0,
        'allow_login_shell':False,'web_search':'disabled','model_catalog_json':str(catalog_path),
        'skills.include_instructions':False,'skills.bundled.enabled':False,
        'tools.update_plan.enabled':False,'tools.experimental_request_user_input.enabled':False,
        'features.tool_registry.turn_metadata_includes_tool_info':True,
        'mcp_servers.rlflow_cpu.command':sys.executable,
        'mcp_servers.rlflow_cpu.args':['-I',str(Path(__file__).resolve()),'_mcp',str(config_path)],
        'mcp_servers.rlflow_cpu.startup_timeout_sec':10,
        'mcp_servers.rlflow_cpu.tool_timeout_sec':command_seconds+10,
        'mcp_servers.rlflow_cpu.required':True}
    # Only the bounded, stage-scoped CPU tool is pre-approved. Native tools
    # remain disabled and the server still enforces Landlock/seccomp limits.
    config['mcp_servers.rlflow_cpu.enabled_tools'] = ['cpu_exec']
    config['mcp_servers.rlflow_cpu.tools.cpu_exec.approval_mode'] = 'approve'
    # Advertise the same writes to the role that cpu_exec enforces. A global
    # read-only declaration makes Engineer correctly refuse implementation.
    config['sandbox_workspace_write.writable_roots'] = ((write_roots or [str(candidate)]) if role == 'Engineer' else [])
    config['sandbox_workspace_write.exclude_slash_tmp'] = True
    config['sandbox_workspace_write.exclude_tmpdir_env_var'] = True
    for f in ['shell_tool','unified_exec','apply_patch_freeform','view_image','js_repl','code_mode',
              'code_mode_only','code_mode_host','apps','plugins','multi_agent','multi_agent_v2',
              'collab','hooks','codex_hooks','plugin_hooks','shell_snapshot','shell_snapshot_v2',
              'browser_use','computer_use','image_generation','imagegenext','memory_tool','memories',
              'skill_search','skill_mcp_dependency_install','remote_control','search_tool','tool_suggest',
              'request_permissions_tool','request_rule','goals','worktrees','codex_git_commit',
              'standalone_web_search','web_search','tool_search','sleep_tool','send_message_to_user_async',
              'deferred_executor','token_budget','current_time_reminder','recommended_plugins']:
        config['features.'+f] = False
    config['features.skip_host_skill_discovery'] = True
    config['features.use_legacy_landlock'] = True
    for k,v in config.items(): argv.extend(['-c', k+'='+json.dumps(v,separators=(',',':'))])
    argv.append('-')
    env = {k:v for k,v in os.environ.items() if k in ('HOME','USER','LANG','LC_ALL','CODEX_HOME','HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR')}
    env.update(PATH='/usr/local/bin:/usr/bin:/bin',CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none')
    return argv,env


def tool_census() -> dict:
    """Inspect the installed CLI's authoritative tool registry without an LLM.

    A local, unauthenticated HTTP stub rejects one request. Its custom provider
    has no external endpoint and receives no real login token. The installed
    CLI supplies the same registry metadata that is sent with real turns.
    """
    import http.server
    import threading
    seen=[]
    catalog = {'models':[{'slug':'gpt-5.6-sol','display_name':'Fixture census',
        'supported_reasoning_levels':[{'effort':'medium','description':'Fixture'}],
        'visibility':'list','supported_in_api':True,'priority':5,'support_verbosity':True,
        'truncation_policy':{'mode':'tokens','limit':10000},
        'base_instructions':'Non-generating local tool census only.','use_responses_lite':True}]}
    class Receiver(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            metadata=request.get('client_metadata',{}).get('x-codex-turn-metadata','{}')
            seen.append(json.loads(metadata).get('tool_namespaces_info',{}))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"local isolation census complete; no model called"}}')
        def log_message(self,*args):pass
    with tempfile.TemporaryDirectory(prefix='rlflow-census-') as tmp:
        root=Path(tmp)
        for name in ('candidate','scratch','control','auth-empty'):(root/name).mkdir()
        schema=root/'control/schema.json'
        schema.write_text('{"type":"object","properties":{},"required":[],"additionalProperties":false}')
        argv,env=codex_command('Engineer',root/'candidate',root/'scratch',schema,root/'control/result.json',
                               _census_catalog=catalog)
        env = {'HOME':str(root/'auth-empty'),'CODEX_HOME':str(root/'auth-empty'),
               'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
               'CUDA_VISIBLE_DEVICES':'','NVIDIA_VISIBLE_DEVICES':'none'}
        # The trusted MCP server needs no inherited secrets either.
        server=http.server.HTTPServer(('127.0.0.1',0),Receiver)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        config={'model_provider':'rlflow_census',
                'model_providers.rlflow_census.name':'Local non-model isolation census',
                'model_providers.rlflow_census.base_url':f'http://127.0.0.1:{server.server_port}/v1',
                'model_providers.rlflow_census.wire_api':'responses',
                'model_providers.rlflow_census.requires_openai_auth':False,
                'model_providers.rlflow_census.request_max_retries':0,
                'model_providers.rlflow_census.stream_max_retries':0,
                'features.enable_request_compression':False}
        for k,v in config.items():argv[-1:-1]=['-c',k+'='+json.dumps(v)]
        try:
            result=subprocess.run(argv,input='Local interface census only.',text=True,capture_output=True,
                                  env=env,cwd=root/'scratch',timeout=20)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
        expected={'functions.list_mcp_resources','functions.list_mcp_resource_templates',
                  'functions.read_mcp_resource','mcp__rlflow_cpu.cpu_exec'}
        actual=set()
        for registry in seen:
            for namespace,info in registry.items():
                actual.update(namespace+'.'+name for name in info.get('functions',{}))
        return {'ok':actual==expected and result.returncode==1 and len(seen)==1,
                'registered_tools':sorted(actual),'expected_tools':sorted(expected),
                'source':'installed CLI turn_metadata_includes_tool_info, local rejecting HTTP stub',
                'real_model_calls':0,'exit_code':result.returncode,
                'requests_observed':len(seen),
                'catalog_sha256':hashlib.sha256(json.dumps(catalog,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'registry_sha256':hashlib.sha256(json.dumps(sorted(actual),separators=(',',':')).encode()).hexdigest()}


def doctor(state_root: str | Path | None = None, *, workspace: str | Path = Path.home()/'.local/share/rlflow-standalone') -> dict:
    """No model calls or GPU initialization. Active OS protection probes."""
    checks = {}
    try:
        ver = subprocess.run([CODEX,'--version'],capture_output=True,text=True,timeout=10)
        checks['codex_version'] = {'ok':PINNED_VERSION in ver.stdout.split(),'observed':ver.stdout.strip()}
        login = subprocess.run([CODEX,'login','status'],capture_output=True,text=True,timeout=10)
        checks['chatgpt_login'] = {'ok':login.returncode == 0 and 'ChatGPT' in login.stdout+login.stderr,
                                   'observed':(login.stdout+login.stderr).strip()}
    except Exception as e: checks['codex']={'ok':False,'error':str(e)}
    with tempfile.TemporaryDirectory(prefix='rlflow-doctor-') as tmp:
        root = Path(tmp)
        for n in ('candidate','scratch','protected','shared.git','control','runtime'): (root/n).mkdir()
        for n in ('protected','shared.git','control','runtime'): (root/n/'sentinel').write_text('immutable')
        (root/'candidate'/'source').write_text('candidate')
        (root/'candidate'/'escape').symlink_to(root/'protected',target_is_directory=True)
        denied = [root/n/'sentinel' for n in ('protected','shared.git','control','runtime')]
        script = "import os,pathlib,socket,subprocess,json; r={}\n"
        script += f"paths={json.dumps([str(p) for p in denied])}\n"
        script += "for p in paths:\n for mode in ('r','w'):\n  try:\n   open(p,mode).close();r[p+mode]=False\n  except PermissionError:r[p+mode]=True\n"
        script += f"\ntry:\n open({str(root/'candidate'/'escape'/'sentinel')!r},'w').close();r['symlink']=False\nexcept PermissionError:r['symlink']=True\n"
        script += "\ntry:\n socket.socket();r['network']=False\nexcept PermissionError:r['network']=True\n"
        script += "\ntry:\n subprocess.run(['/usr/local/bin/codex','--version']);r['nested_codex']=False\nexcept PermissionError:r['nested_codex']=True\n"
        script += "\ntry:\n os.kill(os.getppid(),0);r['process_signal']=False\nexcept PermissionError:r['process_signal']=True\n"
        script += "print(json.dumps(r))"
        import shlex
        result = cpu_exec('/usr/bin/python3 -c '+shlex.quote(script),root/'candidate',root/'scratch','Engineer')
        try: values=json.loads(result['stdout']);checks['kernel_boundaries']={'ok':result['exit_code']==0 and all(values.values()),'checks':values,'execution':result}
        except Exception: checks['kernel_boundaries']={'ok':False,'execution':result}
        for role in ('Engineer','Evaluator'):
            cmd=f"echo ok > {shlex.quote(str(root/'candidate'/'role-write'))}; echo scratch > {shlex.quote(str(root/'scratch'/'own'))}"
            result=cpu_exec(cmd,root/'candidate',root/'scratch',role)
            allowed = (root/'candidate'/'role-write').exists()
            checks[role.lower()+'_write_scope']={'ok':allowed==(role=='Engineer') and (root/'scratch'/'own').exists(),'execution':result}
            (root/'candidate'/'role-write').unlink(missing_ok=True)
        checks['protected_bytes']={'ok':all(p.read_text()=='immutable' for p in denied)}
        actual_paths = [Path(workspace)/'STOP', Path.home()/'.codex/auth.json', Path(__file__).resolve()]
        present = [str(p) for p in actual_paths if p.exists()]
        actual_script = 'import os,json; r={}\n'
        actual_script += 'for p in '+repr(present)+':\n for flag in (os.O_RDONLY,os.O_WRONLY):\n  try:\n   fd=os.open(p,flag);os.close(fd);r[p+str(flag)]=False\n  except PermissionError:r[p+str(flag)]=True\n'
        actual_script += "print(json.dumps(r))"
        result=cpu_exec('/usr/bin/python3 -c '+shlex.quote(actual_script),root/'candidate',root/'scratch','Engineer')
        try:
            values=json.loads(result['stdout'])
            checks['actual_protected_paths']={'ok':bool(values) and all(values.values()) and result['exit_code']==0,'checks':values}
        except Exception:checks['actual_protected_paths']={'ok':False,'execution':result}
        gpu_binary=Path('/usr/bin/nvidia-smi')
        if gpu_binary.exists():
            # Kernel denies execve before the utility can initialize the GPU.
            result=cpu_exec('/usr/bin/nvidia-smi --version',root/'candidate',root/'scratch','Engineer')
            checks['gpu_entry_exec_denied']={'ok':result['exit_code']==126 and 'Permission denied' in result['stderr'],'execution':result}

    try: checks['native_tool_registry']=tool_census()
    except Exception as e:checks['native_tool_registry']={'ok':False,'error':str(e)}
    report = {'ok':all(c['ok'] for c in checks.values()),'checks':checks,
              'real_backend_enabled':False,'tool_transport':'MCP cpu_exec; Landlock ABI >=3 + seccomp',
              'native_tool_exposure':'Verified installed CLI registry; only cpu_exec and empty MCP resource interfaces',
              'isolation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'codex_version':PINNED_VERSION,'created_at':time.time(),
              'kernel':platform.release()}
    if state_root is not None:
        runtime = Path(state_root).resolve()/'runtime'
        runtime.mkdir(parents=True,exist_ok=True)
        target = runtime/'doctor.json'
        temporary = runtime/'doctor.json.tmp'
        temporary.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        temporary.replace(target)
    return report


def require_doctor(state_root: str | Path) -> dict:
    try:
        report=json.loads((Path(state_root)/'runtime'/'doctor.json').read_text())
    except (OSError,ValueError) as e:
        raise IsolationError('Run rlflow doctor before starting roles') from e
    if not report.get('ok'):
        raise IsolationError('Doctor isolation checks failed; no sandbox downgrade permitted')
    expected=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if report.get('isolation_sha256') != expected or report.get('kernel') != platform.release():
        raise IsolationError('Isolation implementation/kernel changed; rerun doctor')
    version=subprocess.run([CODEX,'--version'],capture_output=True,text=True,timeout=10)
    if version.returncode or PINNED_VERSION not in version.stdout.split():
        raise IsolationError('Codex version changed; sandbox is not certified for this CLI')
    if report.get('codex_version')!=PINNED_VERSION:
        raise IsolationError('Doctor was produced for a different Codex version')
    return report


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='_supervised':
        cfg=json.loads(sys.argv[2])
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from rlflow.lifeguard import start as start_guard,group_identity,kill_group
        from rlflow.store import atomic,canonical
        owner=os.getppid()
        if not cfg.get('guard_directory'):
            raise IsolationError('Trusted command guard directory required')
        directory=Path(cfg['guard_directory'])
        directory.mkdir(parents=True,exist_ok=True)
        cfg['guard_directory']=str(directory);cfg['supervisor_identity']=group_identity(os.getpid())
        import uuid
        cfg['generation']=uuid.uuid4().hex
        from rlflow.startup import record
        binding={'session':'command','generation':cfg['generation'],'identity':cfg['supervisor_identity']}
        record(directory,'PREPARING',binding)
        child=None;owned=None;interrupted=[False];timed=False
        def stop_signal(signum,frame):interrupted[0]=True
        signal.signal(signal.SIGTERM,stop_signal);signal.signal(signal.SIGINT,stop_signal)
        started=time.monotonic()
        cfg['overall_deadline_monotonic']=started+cfg['timeout']
        guard=start_guard(directory,'command',cfg['supervisor_identity'],cfg.get('control_root',str(directory)),cfg['timeout'],'command')
        try:
            child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'_child',json.dumps(cfg)],
                                   stdin=subprocess.DEVNULL,start_new_session=True)
            owned=group_identity(child.pid)
            while not (directory/'command-child-identity.json').exists():
                if interrupted[0] or time.monotonic()-started>=cfg['timeout']:raise TimeoutError('command startup deadline')
                if child.poll() is not None or time.monotonic()-started>min(60,cfg['timeout']):raise RuntimeError('command child identity unavailable')
                time.sleep(.01)
            owned=json.loads((directory/'command-child-identity.json').read_text())
            if owned!=group_identity(child.pid):raise RuntimeError('command child identity changed')
            binding={**binding,'identity':owned,'request_sha256':__import__('hashlib').sha256(canonical(cfg)).hexdigest()}
            record(directory,'READY',binding)
            record(directory,'RELEASE_COMMITTED',binding)
            atomic(directory/'command-release.json',canonical(binding))
            while os.waitid(os.P_PID,child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is None:
                if interrupted[0] or os.getppid()!=owner or time.monotonic()-started>cfg['timeout']:
                    timed=True;break
                time.sleep(.02)
        except TimeoutError:
            timed=True
        finally:
            kill_group(owned)
            if child is not None:child.wait()
            atomic(directory/'lifeguard-done',b'done');guard.wait(timeout=3)
        sys.exit(124 if timed else child.returncode if child.returncode>=0 else 128-child.returncode)
    elif len(sys.argv)>1 and sys.argv[1]=='_child':
        cfg=json.loads(sys.argv[2])
        if cfg.get('guard_directory'):
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
            from rlflow.lifeguard import group_identity
            from rlflow.jobs import owns
            from rlflow.store import atomic,canonical
            directory=Path(cfg['guard_directory']);atomic(directory/'command-child-identity.json',canonical(group_identity(os.getpid())))
            deadline=min(time.monotonic()+60,cfg['overall_deadline_monotonic'])
            while not (directory/'command-release.json').exists():
                if not owns(cfg['supervisor_identity']) or time.monotonic()>deadline:raise SystemExit(126)
                time.sleep(.01)
            release=json.loads((directory/'command-release.json').read_text())
            if release['identity']!=group_identity(os.getpid()) or release.get('generation')!=cfg['generation'] or not owns(cfg['supervisor_identity']):raise SystemExit(126)
            from rlflow.startup import record
            record(directory,'START_ACK',release)
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_CPU,(int(cfg['timeout'])+1,int(cfg['timeout'])+1))
        resource.setrlimit(resource.RLIMIT_AS,(cfg.get('memory_bytes',2*1024**3),cfg.get('memory_bytes',2*1024**3)))
        resource.setrlimit(resource.RLIMIT_FSIZE,(20*1024**2,20*1024**2))
        try:
            _restrict(cfg['read'],cfg['write'],cfg.get('execute'))
        except IsolationError as exc:
            if cfg.get('guard_directory'):
                atomic(Path(cfg['guard_directory'])/'sandbox-error.json',canonical({'code':'CPU_SANDBOX_SETUP_FAILED','error':str(exc)}))
            raise
        os.execv('/bin/bash',['/bin/bash','--noprofile','--norc','-c',cfg['command']])
    elif len(sys.argv)>1 and sys.argv[1]=='_mcp': _serve(json.loads(Path(sys.argv[2]).read_text()))
    else: print(json.dumps(doctor(),indent=2))
