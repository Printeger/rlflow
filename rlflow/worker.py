"""Independent role supervisor; no database writes or authority credentials."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from .store import atomic, canonical
from .policy import stopped
from .jobs import identity


def _group_identity(pid):
    """Keep zombie leader identity until wait(): its process group cannot be reused."""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'pgid': int(fields[2]), 'starttime': fields[19],
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def _kill_group(record):
    if record and record['pid'] == record['pgid'] and record == _group_identity(record['pid']):
        try:
            os.killpg(record['pgid'], signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(path):
    request = json.loads(Path(path).read_text())
    d = Path(request['directory'])
    start = time.monotonic()
    proc = None
    guard = None
    def interrupted(*_):raise RuntimeError('worker interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    owned = None
    model_start = None
    exit_code = 125
    reason = 'launch not released'
    deadline = start + request['limit']
    try:
        while not (d / 'release').exists():
            if time.monotonic() >= min(start + 10, deadline) or (d / 'cancel').exists() or stopped(request['root']):
                raise RuntimeError('bounded release cancelled/timed out')
            time.sleep(.02)
        release = json.loads((d / 'release').read_text())
        if release.get('session') != request['id'] or release.get('identity') != identity(os.getpid()):
            raise RuntimeError('release identity mismatch')
        if stopped(request['root']) or (d / 'cancel').exists() or time.monotonic() >= deadline:
            raise RuntimeError('STOP/cancel/budget before role release')
        if release.get('control_release'):
            from .releases import verify
            if verify(Path(__file__).resolve().parents[1])['id'] != release['control_release']:
                raise RuntimeError('frozen worker release mismatch')
            from .store import Store
            from .policy import require_stage
            state = Store(request['root']).replay()
            require_stage(state, request['stage_id'])
            from .packages import runnable
            if not runnable(state,state['tasks'][request['task_id']]):
                raise RuntimeError('package paused or dependencies changed before model launch')
            if state['paused'] and not request.get('explicit_step') and request['task_id'] not in state.get('autonomous_tasks', []):
                raise RuntimeError('paused before model launch')
        from .lifeguard import start as start_guard
        guard=start_guard(d,'role',identity(os.getpid()),request['root'],max(1,deadline-time.monotonic()),request['id'])
        from .isolation import codex_command
        compute = request.get('compute', {})
        runtime = request.get('cpu_runtime')
        read_extra = [str(d/'evidence')] if (d/'evidence').is_dir() else []
        execute_extra = []
        if runtime:
            read_extra.append(runtime['root'])
            execute_extra.append(runtime['root'])
        argv, env = codex_command(request['role'], Path(request['repo']), Path(request['scratch']),
                                  Path(request['schema']), d / 'result.json',
                                  model=compute.get('model', 'gpt-5.6-sol'), effort=compute.get('effort', 'medium'),
                                  read_extra=read_extra or None,
                                  execute_extra=execute_extra or None,
                                  write_roots=request.get('write_roots'),
                                  memory_bytes=runtime['address_space_bytes'] if runtime else 2*1024**3,
                                  command_seconds=request.get('command_seconds',120))
        atomic(d / 'command.json', canonical({'argv': argv, 'sandbox': 'legacy-landlock+cpu-exec', 'limit': request['limit']}))
        if stopped(request['root']) or (d / 'cancel').exists() or time.monotonic() >= deadline:
            raise RuntimeError('STOP/cancel/budget after role setup')
        with (d / 'events.jsonl').open('xb') as out, (d / 'stderr.log').open('xb') as err:
            launch={'directory':str(d),'owner':identity(os.getpid()),'root':request['root'],'scratch':request['scratch'],'argv':argv,'environment':env}
            atomic(d/'model-intent.json',canonical({k:v for k,v in launch.items() if k!='environment'}))
            # Environment is inherited by the held wrapper; credentials are never persisted.
            launch['environment']={}
            atomic(d/'held-role.json',canonical(launch))
            proc = subprocess.Popen([sys.executable,'-m','rlflow.lifeguard','held-role',str(d/'held-role.json')], cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True)
            owned=_group_identity(proc.pid)
            wait_deadline=min(deadline,time.monotonic()+5)
            while not (d/'codex-identity.json').exists():
                if proc.poll() is not None or time.monotonic()>wait_deadline:raise RuntimeError('held CLI identity unavailable')
                time.sleep(.01)
            owned=json.loads((d/'codex-identity.json').read_text())
            if owned!=_group_identity(proc.pid):raise RuntimeError('held CLI identity changed')
            if stopped(request['root']) or (d/'cancel').exists() or time.monotonic()>=deadline:raise RuntimeError('worker interrupted')
            if release.get('control_release'):
                state=Store(request['root']).replay()
                require_stage(state,request['stage_id'])
                if not runnable(state,state['tasks'][request['task_id']]):raise RuntimeError('worker interrupted')
                if state['paused'] and not request.get('explicit_step') and request['task_id'] not in state.get('autonomous_tasks',[]):raise RuntimeError('worker interrupted')
            atomic(d/'model-release.json',canonical({'identity':owned,'session':request['id'],'started_monotonic':time.monotonic()}))
            model_start = time.monotonic()
            owned = _group_identity(proc.pid)
            # Identity was persisted by the held wrapper before release.
            # A role that never reads stdin cannot block the hard wall/STOP checks.
            fd = proc.stdin.fileno()
            os.set_blocking(fd, False)
            pending = memoryview(request['prompt'].encode())
            while pending:
                if time.monotonic() >= deadline or stopped(request['root']) or (d/'cancel').exists():
                    raise RuntimeError('wall budget or STOP during prompt delivery')
                _, writable, _ = select.select([], [fd], [], min(.02, max(0, deadline - time.monotonic())))
                if writable:
                    try:
                        pending = pending[os.write(fd, pending[:4096]):]
                    except BlockingIOError:
                        pass
            proc.stdin.close()
            # WNOWAIT retains the group leader until owned descendant cleanup is done.
            while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if time.monotonic() >= deadline or stopped(request['root']) or (d/'cancel').exists():
                    reason = 'wall budget or STOP'
                    _kill_group(owned)
                    break
                time.sleep(.02)
            _kill_group(owned)
            exit_code = proc.wait(timeout=3)
            if exit_code == 0:
                reason = 'completed'
    except Exception as exc:
        reason = str(exc)
    finally:
        if proc is not None:
            _kill_group(owned)
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            exit_code = proc.wait(timeout=3)
        from .accounting import observe
        usage = observe(d, (d/'model-release.json').exists())
        atomic(d / 'receipt.json', canonical({'session_id': request['id'], 'exit_code': exit_code,
                'model_usage': usage, 'model_active_seconds': time.monotonic() - model_start if model_start else 0,
                'interrupted_and_reclaimed': bool(reason=='worker interrupted' or stopped(request['root']) or (d/'cancel').exists()),
                'reason': reason, 'elapsed_seconds': time.monotonic() - start, 'finished': time.time()}))
        atomic(d/'lifeguard-done',b'done')
        if guard is not None:guard.wait(timeout=3)


if __name__ == '__main__':
    run(sys.argv[1])
