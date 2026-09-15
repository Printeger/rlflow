"""Durable, bounded regression worker. Dispatcher loss does not restart tests."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
from .store import atomic,canonical,Conflict,sha
from .jobs import identity,owns
from .lifeguard import start as start_guard,kill_group


def poll(directory,argv,cwd,code_identity,root,timeout=1800):
    d=Path(directory);d.mkdir(parents=True,exist_ok=True)
    intent={'argv':argv,'cwd':str(cwd),'code_identity':code_identity,'root':str(root),'timeout':timeout}
    if (d/'intent.json').exists():
        if json.loads((d/'intent.json').read_text())!=intent:raise Conflict('validation candidate or procedure drift')
        if (d/'result.json').exists():
            result=json.loads((d/'result.json').read_text())
            if result['code_identity']!=code_identity or result.get('intent_sha256')!=sha(intent):raise Conflict('validation result identity mismatch')
            return result
        # An unknown launch is never automatically retried. A live worker will finish.
        return None
    atomic(d/'intent.json',canonical(intent))
    with (d/'worker.log').open('ab') as log:
        p=subprocess.Popen([sys.executable,'-m','rlflow.validation_job',str(d/'intent.json')],
                           cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    atomic(d/'identity.json',canonical(identity(p.pid)))
    return None


def run(path):
    d=Path(path).parent;r=json.loads(Path(path).read_text());owner=identity(os.getpid());child=None;owned=None;guard=None
    code=137;error=None;start=time.monotonic()
    def stop(*_):raise RuntimeError('validation cancelled')
    signal.signal(signal.SIGTERM,stop)
    try:
        from .policy import stopped
        if stopped(r['root']):raise Conflict('STOP before validation')
        guard=start_guard(d,'command',owner,r['root'],r['timeout'],'validation')
        held={'directory':str(d),'owner':owner,'root':r['root'],'scratch':r['cwd'],'argv':r['argv']}
        atomic(d/'held-role.json',canonical(held))
        environment={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONSTARTUP','OPENAI_API_KEY','CODEX_API_KEY'}}
        environment.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1')
        with (d/'stdout.log').open('xb') as out,(d/'stderr.log').open('xb') as err:
            child=subprocess.Popen([sys.executable,'-m','rlflow.lifeguard','held-role',str(d/'held-role.json')],
                cwd=Path(__file__).resolve().parents[1],env=environment,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
            deadline=time.monotonic()+5
            while not (d/'codex-identity.json').exists():
                if child.poll() is not None or time.monotonic()>deadline:raise Conflict('validation child identity missing')
                time.sleep(.01)
            owned=json.loads((d/'codex-identity.json').read_text())
            if owned!=identity(child.pid):raise Conflict('validation child identity mismatch')
            atomic(d/'command-child-identity.json',canonical(owned))
            atomic(d/'model-release.json',canonical({'identity':owned}))
            while os.waitid(os.P_PID,child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is None:
                if stopped(r['root']) or time.monotonic()-start>=r['timeout']:raise RuntimeError('validation STOP or deadline')
                time.sleep(.03)
            kill_group(owned);code=child.wait()
    except BaseException as exc:error=f'{type(exc).__name__}: {exc}'
    finally:
        if owned:kill_group(owned)
        if child is not None:child.wait(timeout=3)
        result={'exit_code':code,'error':error,'code_identity':r['code_identity'],'intent_sha256':sha(r),
                'isolated_state':True,'stdout':str(d/'stdout.log'),'stderr':str(d/'stderr.log'),'time':time.time()}
        atomic(d/'result.json',canonical(result));atomic(d/'lifeguard-done',b'done')
        if guard is not None:guard.wait(timeout=3)


if __name__=='__main__':run(sys.argv[1])
