"""Generation-bound local startup facts; release intent is committed before delivery."""
import json
import time
from pathlib import Path
from .store import Conflict, atomic, canonical, sha
from .jobs import owns

PHASES=('PREPARING','READY','RELEASE_COMMITTED','START_ACK','RUNNING')


def record(directory, phase, binding):
    if phase not in PHASES:raise Conflict('unknown launch phase')
    fact={'phase':phase,'binding':binding,'binding_sha256':sha(binding),'time':time.time()}
    path=Path(directory)/('launch-'+phase.lower()+'.json')
    if path.exists():
        old=json.loads(path.read_text())
        if old['binding']!=binding:raise Conflict('launch generation changed')
        return old
    atomic(path,canonical(fact));return fact


def validate_release(request, release, process):
    from .hybrid_runtime_boundary import check_request
    check_request(request)
    if release.get('session')!=request['id'] or release.get('identity')!=process:
        raise Conflict('release identity mismatch')
    if request.get('recovery_protocol',1)<2:return
    if release.get('generation')!=request['generation'] or release.get('request_sha256')!=sha(request):
        raise Conflict('stale launch generation/request')
    if not owns(process):raise Conflict('released process no longer owns identity')
    from .store import Store
    session=Store(request['root']).get('sessions',request['id'])
    if not session or session.get('launch_phase')!='RELEASE_COMMITTED' or session.get('release_binding')!=release:
        raise Conflict('release lacks committed authority')
