"""Independent role supervisor; no database writes or authority credentials."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from .store import atomic, canonical, sha
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
    artifact_dir=d
    resource_record=request.get("resources")
    if resource_record and resource_record.get("disk"):
        artifact_dir=Path(resource_record["disk"]["raw"])
    start = time.monotonic()
    proc = None
    guard = None
    def interrupted(*_):raise RuntimeError('worker interrupted')
    previous_sigterm=signal.signal(signal.SIGTERM,interrupted)
    owned = None
    model_start = None
    exit_code = 125
    reason = 'launch not released'
    deadline = min(start + request['limit'],request.get('overall_deadline_monotonic',float('inf')))
    phase_policy=request.get('startup_policy',{'preparing_seconds':60,'release_seconds':60,'ack_seconds':60})
    try:
        def prepare():
            from .isolation import codex_command
            compute = request.get('compute', {})
            runtime = request.get('cpu_runtime')
            read_extra = [str(d/'evidence')] if (d/'evidence').is_dir() else []
            execute_extra = []
            if runtime:
                read_extra.append(runtime['root'])
                execute_extra.append(runtime['root'])
            tool_context = None
            if request.get('recovery_protocol',1) >= 2:
                tool_context = {'schema_version':'1.0','session':request['id'],'generation':request['generation'],
                                'request_sha256':sha(request),'candidate_sha256':sha(request['before'])}
            argv, env = codex_command(request['role'], Path(request['repo']), Path(request['scratch']),
                                      Path(request['schema']), artifact_dir / 'result.json',
                                      model=compute.get('model', 'gpt-5.6-sol'), effort=compute.get('effort', 'medium'),
                                      read_extra=read_extra or None,
                                      execute_extra=execute_extra or None,
                                      write_roots=request.get('write_roots'),
                                      memory_bytes=runtime['address_space_bytes'] if runtime else 2*1024**3,
                                      command_seconds=request.get('command_seconds',120),tool_context=tool_context,
                                      tool_launch_directory=str(d) if tool_context is not None else None)
            if resource_record and resource_record.get('disk'):
                home=artifact_dir/'codex-home';home.mkdir(mode=0o700)
                original=Path(env.get('CODEX_HOME',str(Path(env.get('HOME',str(Path.home())))/'.codex')))
                if (original/'auth.json').is_file():(home/'auth.json').symlink_to((original/'auth.json').resolve())
                temporary=artifact_dir/'tmp';temporary.mkdir()
                env.update(CODEX_HOME=str(home),TMPDIR=str(temporary),XDG_CACHE_HOME=str(home/'cache'),XDG_CONFIG_HOME=str(home/'config'),XDG_DATA_HOME=str(home/'data'))
                for name in ('events.jsonl','stderr.log','result.json','result.json.commands.jsonl'):
                    (d/name).symlink_to(artifact_dir/name)
            atomic(d / 'command.json', canonical({'argv': argv, 'sandbox': 'legacy-landlock+cpu-exec', 'limit': request['limit']}))
            return argv,env
        from .startup import record,validate_release
        if request.get('recovery_protocol',1)>=2:
            from .lifeguard import start as start_guard
            guard=start_guard(d,'role',identity(os.getpid()),request['root'],max(.01,deadline-time.monotonic()),request['id'],spec={'resources':request.get('resources')})
            record(d,'PREPARING',{'session':request['id'],'generation':request['generation'],'identity':identity(os.getpid())})
            argv,env=prepare()
            if time.monotonic()-start>phase_policy['preparing_seconds']:raise RuntimeError('preparation deadline exceeded')
            record(d,'READY',{'session':request['id'],'generation':request['generation'],'identity':identity(os.getpid())})
        release_started=time.monotonic()
        while not (d / 'release').exists():
            release_deadline = min(release_started + request.get('release_wait_seconds', phase_policy['release_seconds']), deadline)
            if time.monotonic() >= release_deadline or (d / 'cancel').exists() or stopped(request['root']):
                raise RuntimeError('bounded release cancelled/timed out')
            time.sleep(.02)
        release = json.loads((d / 'release').read_text())
        validate_release(request,release,identity(os.getpid()))
        if stopped(request['root']) or (d / 'cancel').exists() or time.monotonic() >= deadline:
            raise RuntimeError('STOP/cancel/budget before role release')
        if release.get('control_release'):
            from .releases import verify
            if verify(Path(__file__).resolve().parents[1])['id'] != release['control_release']:
                raise RuntimeError('frozen worker release mismatch')
            from .store import Store
            from .policy import require_stage
            state = Store(request['root']).view()
            require_stage(state, request['stage_id'])
            from .packages import runnable
            if not runnable(state,state['tasks'][request['task_id']]):
                raise RuntimeError('package paused or dependencies changed before model launch')
            if state['paused'] and not request.get('explicit_step') and request['task_id'] not in state.get('autonomous_tasks', []):
                raise RuntimeError('paused before model launch')
        if request.get('recovery_protocol',1)<2:argv,env=prepare()
        from .lifeguard import start as start_guard
        if guard is None:guard=start_guard(d,'role',identity(os.getpid()),request['root'],max(.01,deadline-time.monotonic()),request['id'],spec={'resources':request.get('resources')})
        if stopped(request['root']) or (d / 'cancel').exists() or time.monotonic() >= deadline:
            raise RuntimeError('STOP/cancel/budget after role setup')
        with (artifact_dir / 'events.jsonl').open('xb') as out, (artifact_dir / 'stderr.log').open('xb') as err:
            launch={'directory':str(d),'owner':identity(os.getpid()),'root':request['root'],'scratch':request['scratch'],'argv':argv,'environment':env,'generation':request.get('generation'),'session':request['id'],'release_wait_seconds':request.get('release_wait_seconds',60),'deadline':deadline,'resources':request.get('resources')}
            atomic(d/'model-intent.json',canonical({k:v for k,v in launch.items() if k!='environment'}))
            # Environment is inherited by the held wrapper; credentials are never persisted.
            launch['environment']={}
            atomic(d/'held-role.json',canonical(launch))
            proc = subprocess.Popen([sys.executable,'-m','rlflow.lifeguard','held-role',str(d/'held-role.json')], cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True)
            owned=_group_identity(proc.pid)
            wait_deadline=min(deadline,time.monotonic()+phase_policy['ack_seconds'])
            while not (d/'codex-identity.json').exists():
                if proc.poll() is not None or time.monotonic()>wait_deadline:raise RuntimeError('held CLI identity unavailable')
                time.sleep(.01)
            owned=json.loads((d/'codex-identity.json').read_text())
            if request.get('resources'):
                from .resources import verify_group
                verify_group(request['resources'],owned)
            if owned!=_group_identity(proc.pid):raise RuntimeError('held CLI identity changed')
            if stopped(request['root']) or (d/'cancel').exists() or time.monotonic()>=deadline:raise RuntimeError('worker interrupted')
            if release.get('control_release'):
                state=Store(request['root']).view()
                require_stage(state,request['stage_id'])
                if not runnable(state,state['tasks'][request['task_id']]):raise RuntimeError('worker interrupted')
                if state['paused'] and not request.get('explicit_step') and request['task_id'] not in state.get('autonomous_tasks',[]):raise RuntimeError('worker interrupted')
            atomic(d/'model-release.json',canonical({'identity':owned,'session':request['id'],'started_monotonic':time.monotonic(),'generation':request.get('generation')}))
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
                if request.get('resources'):
                    from .resources import verify_group,stats
                    group=verify_group(request['resources']);observed=stats(group)
                    if observed['cpu.stat']['usage_usec']>=request['resources']['policy']['cpu_seconds']*1000000:
                        reason='cumulative CPU budget';(group/'cgroup.kill').write_text('1');break
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
        # Cleanup must finish even when the guardian delivers the deadline signal.
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        if proc is not None:
            _kill_group(owned)
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            exit_code = proc.wait(timeout=3)
        if request.get('resources'):
            from .resources import verify_group,stats
            group=verify_group(request['resources'])
            (group/'cgroup.kill').write_text('1')
            resource_usage={'tree':stats(group),'disk':None}
            if request['resources'].get('disk'):
                from .resources import quota
                disk=request['resources']['disk']['directory']
                try:resource_usage['disk']=quota(disk['path'],disk['device'],disk.get('reader'))
                except Exception as exc:resource_usage['disk']={'status':'UNKNOWN','reason':str(exc)}
            atomic(d/'resource-usage.json',canonical(resource_usage))
        from .accounting import observe
        usage = observe(d, (d/'model-release.json').exists())
        atomic(d / 'receipt.json', canonical({'session_id': request['id'], 'exit_code': exit_code,
                'resource_usage':json.loads((d/'resource-usage.json').read_text()) if (d/'resource-usage.json').exists() else None,
                'model_usage': usage, 'model_active_seconds': time.monotonic() - model_start if model_start else 0,
                'interrupted_and_reclaimed': bool(reason=='worker interrupted' or stopped(request['root']) or (d/'cancel').exists()),
                'reason': reason, 'elapsed_seconds': time.monotonic() - start, 'finished': time.time()}))
        atomic(d/'lifeguard-done',b'done')
        if guard is not None:guard.wait(timeout=3)
        signal.signal(signal.SIGTERM,previous_sigterm)


if __name__ == '__main__':
    run(sys.argv[1])
