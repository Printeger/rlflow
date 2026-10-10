"""Finite delegated CPU service entry, not an approval or public Core start.

Only the future exact original CPU owner may dispatch this after durable
handoff. Its transport PID is never the keeper/task identity. Protocol stdout
is trusted keeper output; candidate stdout/stderr are separate private files.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading

from .hybrid_local_runner_cgroup import OriginalTaskScope, _inode, _start
from .hybrid_local_runner_keeper import FiniteCpuKeeper


def _emit(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()+b'\n'
    if len(raw) > 16384 or os.write(1, raw) != len(raw):
        raise RuntimeError('original service protocol output incomplete')


def serve(config_path, expected_sha256):
    """One exact original service invocation; no resume/adoption or retries.

    Frozen config hash is integrity only, NOT a grant. Core must separately
    validate human approval, source lineage and budget before dispatch and G.
    On failure original strong scope/keeper handles remain live on the thrown
    exception for same-service cleanup; never imply Pool FREE from this entry.
    """
    invocation = os.environ.get('INVOCATION_ID', '')
    if not re.fullmatch('[0-9a-f]{32}', invocation):
        raise RuntimeError('original service invocation required')
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('frozen service config SHA256 required')
    creator = {'pid': os.getpid(), 'thread': threading.get_ident()}
    config_fd = os.open(config_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    config_identity = None
    try:
        config_identity = _inode(config_fd)
        info = os.fstat(config_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or
                not 0 < info.st_size <= 65536):
            raise RuntimeError('private bounded original service config required')
        raw = os.pread(config_fd, 65537, 0)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise RuntimeError('original service config hash differs')
        config = json.loads(raw)
    finally:
        try:
            if config_identity is None or _inode(config_fd) != config_identity:
                raise RuntimeError('original config FD identity uncertain')
            os.close(config_fd)
        except BaseException as exc:
            exc.original_config_cleanup = {'creator': creator, 'fd': config_fd,
                                           'identity': config_identity}
            raise
    if (type(config) is not dict or set(config) not in
            ({'code', 'work', 'stdout', 'stderr', 'limits', 'seconds'},
             {'code', 'work', 'stdout', 'stderr', 'limits', 'seconds','output_identities'})):
        raise ValueError('closed finite CPU service config required')
    for name in ('work', 'stdout', 'stderr'):
        if type(config[name]) is not str or not Path(config[name]).is_absolute():
            raise ValueError('exact absolute private service paths required')
    keeper_identity = {'pid': os.getpid(), 'starttime': _start(os.getpid()),
                       'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'invocation_id': invocation}
    # Original control FD is retained before preparation; task drops it before
    # ready/G and cannot write its own control or trusted protocol stdout.
    control = None
    control_identity = None
    sources = []
    scope = keeper = None
    try:
        control = os.dup(0)
        control_identity = _inode(control)
        for name in ('stdout', 'stderr'):
            original_outputs=config.get('output_identities')
            flags=os.O_APPEND if original_outputs is not None else os.O_CREAT|os.O_EXCL
            fd = os.open(config[name], os.O_WRONLY | flags |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            sources.append((fd, None))  # Retain BEFORE fallible identity IO.
            sources[-1] = (fd, _inode(fd))
            if original_outputs is not None and list(_inode(fd))!=original_outputs[name]:
                raise RuntimeError('original preallocated output source identity changed')
        scope = OriginalTaskScope(config['limits'])
        keeper = FiniteCpuKeeper(scope)
        ready = keeper.prepare_gate(config['code'], config['work'],
                                    sources[0][0], sources[1][0], seconds=config['seconds'])
        _emit({'type': 'local_cpu.ready', 'config_sha256': expected_sha256,
               'keeper': keeper_identity, 'task': ready})
        stopped = keeper.run_original_control(control)
        closed = keeper.close_stopped_task()
        for index, (fd, identity) in enumerate(sources):
            if _inode(fd) != identity:
                raise RuntimeError('original task output source changed')
            os.close(fd)
            sources[index] = (None, identity)
        if _inode(control) != control_identity:
            raise RuntimeError('original service control FD changed')
        os.close(control)
        control = None
        _emit({'type': 'local_cpu.task_closed', 'config_sha256': expected_sha256,
               'keeper': keeper_identity, 'task': ready, 'stopped': stopped,
               'closed': closed, 'original_output_fds_closed': True,
               'original_control_fd_closed': True, 'whole_scope_stopped': False})
    except BaseException as exc:
        # Failure cannot leave a known task running just because its trusted
        # report/source write failed. Cleanup participants are independent;
        # uncertainty is retained and never emitted as successful terminal.
        failures = []
        if keeper is not None and not keeper._closed:
            if not keeper._task_stopped:
                try: keeper.stop_and_reap_task()
                except BaseException as cleanup_exc: failures.append(('task_stop', repr(cleanup_exc)))
            try: keeper.close_stopped_task()
            except BaseException as cleanup_exc: failures.append(('task_close', repr(cleanup_exc)))
        elif scope is not None:
            try:
                scope.stop_task(5)
                scope.close_empty_task()
            except BaseException as cleanup_exc: failures.append(('scope', repr(cleanup_exc)))
        for index, (fd, identity) in enumerate(sources):
            if fd is None: continue
            try:
                if identity is None or _inode(fd) != identity:
                    raise RuntimeError('original source FD identity uncertain')
                os.close(fd)
            except BaseException as cleanup_exc: failures.append(('source', repr(cleanup_exc)))
            else: sources[index] = (None, identity)
        if control is not None:
            try:
                if control_identity is None or _inode(control) != control_identity:
                    raise RuntimeError('original control FD identity uncertain')
                os.close(control)
            except BaseException as cleanup_exc: failures.append(('control', repr(cleanup_exc)))
            else: control = None
        exc.original_service_cleanup = {'scope': scope, 'keeper': keeper,
                                        'control': control, 'sources': sources,
                                        'control_identity': control_identity,
                                        'creator': creator, 'failures': failures}
        raise


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        raise SystemExit('expected original config path and SHA256')
    serve(sys.argv[1], sys.argv[2])
