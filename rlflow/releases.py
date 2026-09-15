"""Content-addressed control releases; idle-boundary deployment preserves pause intent."""
import hashlib
import json
from pathlib import Path
import shutil
from .store import Conflict,atomic,canonical,sha

ROOT=Path(__file__).resolve().parents[1]


def files(root=ROOT):
    return {str(p.relative_to(root)):p for folder in ('rlflow','schemas','roles','tests')
            for p in sorted((root/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts} | {name:root/name for name in ('model_policy.yaml','bootstrap.py','pyproject.toml','requirements.lock')}


def freeze(destination, root=ROOT):
    sources=files(root);manifest={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in sources.items()}
    digest=sha(manifest);target=Path(destination)/digest
    if target.exists():
        verify(target);return target
    target.mkdir(parents=True)
    for name,p in sources.items():
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=manifest[name]:raise Conflict('control source changed while freezing')
        atomic(target/name,data)
    atomic(target/'release.json',canonical({'id':digest,'files':manifest}))
    verify(target)
    return target


def verify(target):
    target=Path(target);record=json.loads((target/'release.json').read_text())
    if sha(record['files'])!=record['id']:raise Conflict('release manifest identity mismatch')
    actual={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files(target).items()}
    if actual!=record['files']:raise Conflict('frozen release bytes changed')
    return record


def deploy(store, report):
    from .verification import code_identity
    validation=json.loads(Path(report).read_text())
    if validation.get('exit_code')!=0 or validation.get('code_identity')!=code_identity() or not validation.get('isolated_state'):
        raise Conflict('exact passing isolated test evidence required')
    target=freeze(store.root/'releases');record=verify(target)
    def change(s):
        if any(x['status'] in {'START_INTENT','RUNNING','RECONCILE'} for x in s['sessions'].values()) or any(j['status'] in {'START_INTENT','RUNNING','RECONCILE'} for j in s['jobs'].values()):
            raise Conflict('release requires idle reconciled boundary')
        s.setdefault('releases',{})[record['id']]={'path':str(target),'validation':validation,'capabilities':[
            'work-packages/1','model-reservations/2','conditional-experiments/1','research-routing/1',
            'long-goals/1','bounded-parameter-search/1','research-completion/1','bounded-history/1',
            'process-recovery/1','h1-control-adapter/1','durable-regression-worker/1'],
            'published_sequence':s['version']+1, 'unique_dispatcher':'rlflow.engine', 'paused_at_release':s['paused'], 'enabled_at_release':s['enabled']}
    with store.lock('dispatch-release'):
        state=store.transact('CONTROL_RELEASE_DEPLOYED','release:'+record['id'],change,object_id=record['id'])
        atomic(store.root/'runtime/current-release.json',canonical({'id':record['id'],'path':str(target)}))
    return state['releases'][record['id']]


def committed_release(state):
    rows=[(v.get('published_sequence',0),k,v) for k,v in state.get('releases',{}).items() if v.get('published_sequence')]
    if not rows:return None
    _,rid,record=max(rows)
    return {'id':rid,'path':record['path']}


def reconcile_pointer(store):
    """Finish a committed publication after a crash before pointer export."""
    with store.lock('dispatch-release'):
        selected=committed_release(store.replay())
        if selected is None:return None
        target=Path(selected['path']).resolve(strict=True)
        if not target.is_relative_to(store.root/'releases') or verify(target)['id']!=selected['id']:raise Conflict('committed control release drift')
        pointer=store.root/'runtime/current-release.json'
        if not pointer.exists() or json.loads(pointer.read_text())!=selected:atomic(pointer,canonical(selected))
        return selected


def handoff(root, old_identity):
    """A separate helper waits for the old dispatch lock owner to exit."""
    import subprocess,sys
    with (Path(root)/'runtime/handoff.log').open('ab') as log:
        subprocess.Popen([sys.executable,'-m','rlflow.releases','_handoff',str(root),canonical(old_identity).decode()],
                         cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)


if __name__=='__main__':
    import sys,time,os
    from .jobs import owns
    from .store import Store
    root=Path(sys.argv[2]);previous=json.loads(sys.argv[3]);deadline=time.monotonic()+60
    while owns(previous):
        if time.monotonic()>deadline:raise SystemExit('previous dispatcher remains alive; no double dispatch')
        time.sleep(.1)
    pointer=json.loads((root/'runtime/current-release.json').read_text());verify(pointer['path'])
    os.chdir(pointer['path'])
    os.execv(sys.executable,[sys.executable,'-m','rlflow.cli','--state-dir',str(root),'_daemon'])
