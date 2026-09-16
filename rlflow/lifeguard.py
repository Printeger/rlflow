"""Independent, identity-bound cleanup after supervisor death or loss of control."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
from .jobs import identity,owns
from .store import atomic,canonical,sha
from .policy import stopped


def group_identity(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return {'pid':pid,'pgid':int(fields[2]),'starttime':fields[19],
                'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError,ProcessLookupError):return None


def kill_group(record):
    if record and record['pid']==record['pgid'] and group_identity(record['pid'])==record:
        try:os.killpg(record['pgid'],signal.SIGKILL)
        except ProcessLookupError:pass


def start(directory,kind,owner,root,limit,object_id,spec=None,resources=None):
    d=Path(directory);request={'directory':str(d),'kind':kind,'owner':owner,'root':str(root),
        'limit':limit,'id':object_id,'spec':spec,'resources':resources,'started_wall':time.time(),'started_monotonic':time.monotonic()}
    path=d/'lifeguard-request.json';atomic(path,canonical(request))
    with (d/'lifeguard.log').open('ab') as log:
        proc=subprocess.Popen([sys.executable,'-m','rlflow.lifeguard',str(path)],
            cwd=Path(__file__).resolve().parents[1],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+5
    while not (d/'lifeguard-ready.json').exists():
        if proc.poll() is not None or time.monotonic()>deadline:raise RuntimeError('lifeguard failed before child launch')
        time.sleep(.01)
    ready=json.loads((d/'lifeguard-ready.json').read_text())
    if not owns(ready['identity']) or ready['request_sha256']!=sha(request):raise RuntimeError('lifeguard identity mismatch')
    return proc


def run(path):
    request=json.loads(Path(path).read_text());d=Path(request['directory']);owner=request['owner']
    atomic(d/'lifeguard-ready.json',canonical({'identity':identity(os.getpid()),'request_sha256':sha(request)}))
    cause='supervisor lost'
    while owns(owner):
        resource_record=request.get('resources') or ((request.get('spec') or {}).get('resources') if request['kind']=='role' else None)
        if resource_record:
            from .resources import verify_group,stats
            observed=stats(verify_group(resource_record))
            if observed['cpu.stat']['usage_usec']>=resource_record['policy']['cpu_seconds']*1000000:
                cause='cumulative CPU budget exceeded';break
        if (d/'lifeguard-done').exists():return
        if stopped(request['root']) or (d/'cancel').exists():cause='STOP/cancel';break
        if time.monotonic()-request['started_monotonic']>request['limit']:cause='supervisor deadline exceeded';break
        time.sleep(.02)
    reclaim(request,cause)

def reclaim(request,cause='supervisor lost during dispatcher recovery'):
    d=Path(request['directory']);owner=request['owner']
    child_file=d/({'role':'codex-identity.json','experiment':'process-identity.json','command':'command-child-identity.json'}[request['kind']])
    child=json.loads(child_file.read_text()) if child_file.exists() else None
    # Stop the owner before reading a possibly still-being-persisted identity.
    if owns(owner):
        os.kill(owner['pid'],signal.SIGTERM)
        deadline=time.monotonic()+.5
        while owns(owner) and time.monotonic()<deadline:
            # The owner has completed cleanup and is waiting for this guardian.
            if (d/'lifeguard-done').exists():return
            time.sleep(.01)
        if owns(owner):os.kill(owner['pid'],signal.SIGKILL)
    if child_file.exists():child=json.loads(child_file.read_text())
    kill_group(child)
    resources=request.get('resources') or ((request.get('spec') or {}).get('resources') if request['kind']=='role' else None)
    if resources:
        from .resources import verify_group,stats
        group=verify_group(resources);(group/'cgroup.kill').write_text('1')
        atomic(d/'resource-usage.json',canonical(stats(group)))
    if (d/'receipt.json').exists():return
    deadline=time.monotonic()+2
    while (owns(owner) or owns(child)) and time.monotonic()<deadline:time.sleep(.01)
    elapsed=max(0,time.monotonic()-request['started_monotonic'])
    fact={'cause':cause,'owner':owner,'child':child,'owner_dead':not owns(owner),'child_alive':owns(child),'elapsed_seconds':elapsed}
    atomic(d/('recovery-'+str(time.time_ns())+'.json'),canonical(fact))
    atomic(d/'recovery.json',canonical(fact))
    if owns(owner) or owns(child):return
    if request['kind']=='command':
        atomic(d/'receipt.json',canonical({'exit_code':137,'recovery':fact}))
        return
    if request['kind']=='role':
        from .accounting import observe
        released=(d/'model-release.json').exists()
        usage=observe(d,released)
        model_start=json.loads((d/'model-release.json').read_text()).get('started_monotonic',request['started_monotonic']) if released else None
        elapsed=max(0,time.monotonic()-request['started_monotonic'])
        active=max(0,elapsed-(model_start-request['started_monotonic'])) if released else 0
        receipt={'session_id':request['id'],'exit_code':137,'model_usage':usage,'model_active_seconds':active,
            'reason':'supervisor lost; owned child reclaimed','elapsed_seconds':elapsed,'finished':time.time(),'recovery':fact}
    else:
        release_path=d/'held-child.json';held=json.loads(release_path.read_text()) if release_path.exists() else {}
        released=bool(held.get('released_after_durable_record'))
        uncertain=(d/'release-intent.json').exists() and not released
        allocation=json.loads((d/'release-intent.json').read_text()).get('allocated_monotonic') if (d/'release-intent.json').exists() else None
        receipt={'job_id':request['id'],'spec_sha256':sha(request['spec']),'status':'STOPPED' if cause=='STOP/cancel' else 'FAILED',
            'exit_code':137,'error':cause,'elapsed_seconds':elapsed,'released':released,
            'definitely_not_released':not released and not uncertain,'recovery':fact,
            'allocated_seconds':max(0,time.monotonic()-allocation) if allocation is not None else None}
    atomic(d/'receipt.json',canonical(receipt))


def held_role(path):
    """No CLI executes until its own durable identity and release are bound."""
    r=json.loads(Path(path).read_text());d=Path(r['directory'])
    if r.get('resources'):
        from .resources import enter
        enter(r['resources'])
    atomic(d/'codex-identity.json',canonical(group_identity(os.getpid())))
    deadline=min(time.monotonic()+r.get('release_wait_seconds',60),r.get('deadline',float('inf')))
    while not (d/'model-release.json').exists():
        if not owns(r['owner']) or time.monotonic()>deadline or stopped(r['root']):raise SystemExit(126)
        time.sleep(.01)
    release=json.loads((d/'model-release.json').read_text())
    if release['identity']!=group_identity(os.getpid()) or not owns(r['owner']) or stopped(r['root']) or (d/'cancel').exists():raise SystemExit(126)
    if release.get('generation')!=r.get('generation') or release.get('session')!=r.get('session',release.get('session')):raise SystemExit(126)
    from .startup import record
    record(d,'START_ACK',{'session':release.get('session'),'generation':r.get('generation'),'identity':group_identity(os.getpid())})
    if r.get('resources',{} ) and r['resources'].get('disk'):
        from .resources import confine_writes
        confine_writes(r['resources']['disk']['root'])
    os.chdir(r['scratch'])
    os.execvpe(r['argv'][0],r['argv'],os.environ)


if __name__=='__main__':
    if sys.argv[1]=='held-role':held_role(sys.argv[2])
    else:run(sys.argv[1])
