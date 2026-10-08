"""Model-free OS sources and independent, non-authoritative latest slot."""
import copy
import json
import os
import sqlite3
import time
import pytest
from rlflow import telemetry, telemetry_sources as sources
from rlflow.worker_heartbeat import Heartbeat
from rlflow.jobs import identity
from rlflow.store import Store, atomic, canonical, sha
from rlflow.observation import enable, ObservationReader, public_id, rotate_epoch
from rlflow.hybrid_protocol import ProtocolError, validate
from test_web_api import web, login  # noqa: F401


@pytest.fixture
def observed(tmp_path):
    store = Store(tmp_path/'state');enable(store,'project_resources',data_mode='fixture')
    return store,ObservationReader(store.root)


def worker_fixture(store,sid='worker_one'):
    directory = store.root/'roles'/sid;directory.mkdir(parents=True,exist_ok=True)
    request = dict(id=sid,generation='generation_one',directory=str(directory),before={},recovery_protocol=2)
    owner = identity(os.getpid())
    binding = dict(session=sid,generation=request['generation'],identity=owner,
                   request_sha256=sha(request),candidate_sha256=sha(request['before']))
    session = dict(session_fixture(sid),directory=str(directory),generation=request['generation'],identity=owner,status='RUNNING',release_binding=binding)
    store.transact_objects('FIXTURE_WORKER',sid,[('sessions',sid)],lambda s:s.setdefault('sessions',{}).update({sid:session}))
    heartbeat = Heartbeat(request,clock=lambda:time.monotonic()-3);assert heartbeat.tick()
    return session,heartbeat,directory


def session_fixture(sid):
    return dict(id=sid,role='Engineer',task_id='task_fixture',task_version=1,stage_id='stage_fixture',
                input_state_version=0,status='RUNNING',directory='',scratch='',limit=1,
                before=dict(path='',head='',tree_sha256='0'*64,files={}),identity=None,created=0,
                generation='generation_fixture',release_binding={})


def confirmed(store,session,h):
    value,prior = sources.worker(store.root,'worker_one',session)
    assert value['heartbeat']['status']=='UNKNOWN'
    h.clock=time.monotonic;assert h.tick()
    value,prior = sources.worker(store.root,'worker_one',session,prior)
    assert value['heartbeat']['status']=='FRESH'
    return value,prior


def due(store):
    with sqlite3.connect(store.db) as db:db.execute('UPDATE telemetry_latest SET monotonic_seconds=monotonic_seconds-2')


def test_actual_os_scopes_and_cumulative_process_metrics(tmp_path):
    host,prior = sources.host(tmp_path)
    assert host['cpu']['status']=='UNKNOWN' and host['cpu']['utilization_percent'] is None
    assert host['memory']['status']==host['disk']['status']=='KNOWN'
    assert host['disk']['scope']=='STATE_FILESYSTEM'
    assert sources.process(identity(os.getpid()))['status']=='KNOWN'
    time.sleep(.02)
    current,_ = sources.host(tmp_path,prior)
    assert current['cpu']['status']=='KNOWN' and 0<=current['cpu']['utilization_percent']<=100
    owner = identity(os.getpid());owner['starttime']='0'
    assert sources.process(owner)['status']=='UNKNOWN'


def test_latest_slot_does_not_advance_domain_or_authority(observed):
    store,reader = observed
    session,heartbeat,directory = worker_fixture(store)
    before,version,cursor = store.replay(),store.version(),reader.head()['cursor']
    assert reader.telemetry() is None and telemetry.sample(store)
    assert reader.telemetry()['workers'][0]['heartbeat']['status']=='UNKNOWN'
    heartbeat.clock=time.monotonic;assert heartbeat.tick();due(store);assert telemetry.sample(store)
    value = reader.telemetry();validate('Telemetry',value)
    assert value['workers'][0]['execution_id']==public_id('worker_one')
    assert value['workers'][0]['heartbeat']['status']=='FRESH'
    assert value['gpu']['status']=='UNKNOWN' and value['gpu']['utilization_percent'] is None
    assert store.replay()==before and store.version()==version and reader.head()['cursor']==cursor
    assert reader.events(cursor)==[] and not telemetry.sample(store)
    assert reader.telemetry()['sample_age_seconds']>=value['sample_age_seconds']
    assert str(directory) not in json.dumps(value) and 'pid' not in json.dumps(value)


@pytest.mark.parametrize('damage',['future','generation','owner','counter','clock','same_counter','same_clock','extra','symlink'])
def test_bad_heartbeat_is_unknown_not_authority(observed,damage):
    store,reader = observed;session,h,directory = worker_fixture(store)
    value,prior = confirmed(store,session,h)
    assert value['heartbeat']['status']=='FRESH'
    path = directory/'worker-heartbeat.json';fact = json.loads(path.read_text())
    if damage=='future':fact['monotonic_seconds']=time.monotonic()+100
    elif damage=='generation':fact['context']['generation']='old'
    elif damage=='owner':fact['identity']['starttime']='0'
    elif damage=='counter':fact['counter']=0
    elif damage=='clock':fact['monotonic_seconds']-=1
    elif damage=='same_counter':fact['monotonic_seconds']+=.001
    elif damage=='same_clock':fact['counter']+=1
    elif damage=='extra':fact['raw']='PRIVATE'
    elif damage=='symlink':
        other = directory/'other.json';atomic(other,canonical(fact));path.unlink();path.symlink_to(other)
    if damage!='symlink':atomic(path,canonical(fact))
    value,checkpoint = sources.worker(store.root,'worker_one',session,prior)
    assert value['heartbeat']['status']=='UNKNOWN' and checkpoint==prior
    assert store.get('sessions','worker_one')['status']=='RUNNING'


def test_reread_does_not_refresh_and_stale_remains_stale(observed,monkeypatch):
    store,reader = observed;session,h,directory = worker_fixture(store)
    value,prior = confirmed(store,session,h)
    fact = json.loads((directory/'worker-heartbeat.json').read_text())
    monkeypatch.setattr(sources.time,'monotonic',lambda:fact['monotonic_seconds']+20)
    value,prior = sources.worker(store.root,'worker_one',session,prior)
    assert value['heartbeat']['status']=='STALE' and value['heartbeat']['age_seconds']==20
    assert sources.worker(store.root,'worker_one',session,prior)[0]==value


def test_heartbeat_loop_rate_failure_and_disabled_legacy(tmp_path):
    request = dict(id='worker',generation='gen',directory=str(tmp_path),before={},recovery_protocol=2)
    clock = [10];writes = []
    def write(*args):writes.append(args);raise OSError('fixture write failure')
    h = Heartbeat(request,clock=lambda:clock[0],write=write)
    assert not h.tick() and not h.tick() and len(writes)==1
    clock[0]+=2;assert not h.tick() and len(writes)==2
    assert not Heartbeat({},write=lambda *a:pytest.fail('invalid request disabled')).tick()
    request['recovery_protocol']=1
    assert not Heartbeat(request,write=lambda *a:pytest.fail('legacy disabled')).tick()


def test_busy_writer_drops_without_waiting(observed):
    store,reader = observed
    with store.lock():
        start = time.monotonic();assert not telemetry.sample(store)
        assert time.monotonic()-start<.5
    with sqlite3.connect(store.db) as db:
        db.execute('BEGIN IMMEDIATE')
        start = time.monotonic();assert not telemetry.sample(store)
        assert time.monotonic()-start<.5
    assert reader.telemetry() is None


def test_readonly_does_not_upgrade_old_store_and_corrupt_slot_fails_closed(observed):
    store,reader = observed;assert telemetry.sample(store)
    with sqlite3.connect(store.db) as db:db.execute("UPDATE telemetry_latest SET digest='bad'")
    with pytest.raises(ProtocolError):reader.telemetry()
    with sqlite3.connect(store.db) as db:db.execute('DROP TABLE telemetry_latest')
    assert reader.telemetry() is None and not telemetry.sample(store)
    with sqlite3.connect(store.db) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='telemetry_latest'").fetchone()
    with pytest.raises(ProtocolError):enable(store,'project_resources',data_mode='fixture')
    with sqlite3.connect(store.db) as db:db.execute('DROP TABLE telemetry_worker_witness')
    enable(store,'project_resources',data_mode='fixture');assert reader.telemetry() is None


def test_stopped_sampler_does_not_leave_worker_fresh(observed):
    store,reader = observed;session,h,directory = worker_fixture(store)
    assert telemetry.sample(store);h.clock=time.monotonic;assert h.tick();due(store);assert telemetry.sample(store)
    assert reader.telemetry()['workers'][0]['heartbeat']['status']=='FRESH'
    with sqlite3.connect(store.db) as db:db.execute('UPDATE telemetry_latest SET monotonic_seconds=monotonic_seconds-20')
    value = reader.telemetry()
    assert value['workers'][0]['heartbeat']['status']=='STALE' and value['workers'][0]['heartbeat']['age_seconds']>=20


def test_changed_generation_cannot_reuse_latest_fresh_worker(observed):
    store,reader = observed;session,h,directory = worker_fixture(store)
    assert telemetry.sample(store);h.clock=time.monotonic;assert h.tick();due(store);assert telemetry.sample(store)
    assert reader.telemetry()['workers'][0]['heartbeat']['status']=='FRESH'
    store.transact_objects('FIXTURE_CHANGE','change',[('sessions','worker_one')],lambda s:s['sessions']['worker_one'].update(generation='new'))
    value = reader.telemetry()['workers'][0]
    assert value['heartbeat']['status']==value['process']['status']=='UNKNOWN'


def test_old_boot_or_epoch_sample_not_returned(observed,monkeypatch):
    store,reader = observed;assert telemetry.sample(store)
    with monkeypatch.context() as patch:
        patch.setattr(sources,'boot_id',lambda:'a-new-boot')
        assert reader.telemetry() is None
    rotate_epoch(store);assert reader.telemetry() is None
    assert telemetry.sample(store) and reader.telemetry()['sample_seq']==1


def test_real_worker_release_wait_heartbeat_failure_is_nonfatal(tmp_path,monkeypatch):
    from rlflow import worker, worker_heartbeat
    directory = tmp_path/'role';directory.mkdir();scratch = directory/'scratch';scratch.mkdir()
    candidate = tmp_path/'candidate';candidate.mkdir()
    request = dict(id='worker_fixture',generation='generation_fixture',recovery_protocol=2,before={},
                   directory=str(directory),scratch=str(scratch),repo=str(candidate),root=str(tmp_path),
                   role='PI',schema='unused',limit=1,prompt='',release_wait_seconds=.05)
    atomic(directory/'request.json',canonical(request))
    original = worker_heartbeat.Heartbeat
    def failing(request):
        def fail(*args):raise OSError('fixture heartbeat write failure')
        return original(request,write=fail)
    monkeypatch.setattr(worker_heartbeat,'Heartbeat',failing)
    worker.run(directory/'request.json')
    receipt = json.loads((directory/'receipt.json').read_text())
    assert receipt['model_usage']['state']=='NOT_STARTED' and 'bounded release cancelled/timed out' in receipt['reason']
    assert not (directory/'codex-identity.json').exists()


def test_deeply_nested_heartbeat_cannot_escape_optional_source(observed):
    store,reader = observed;session,h,directory = worker_fixture(store)
    atomic(directory/'worker-heartbeat.json',('['*1500+'0'+']'*1500).encode())
    assert sources.worker(store.root,'worker_one',session)[0]['heartbeat']['status']=='UNKNOWN'
    assert telemetry.sample(store) and reader.telemetry()['workers'][0]['heartbeat']['status']=='UNKNOWN'


def test_rotation_retains_counter_witness_and_gc_is_bounded(observed):
    store,reader = observed;session,h,directory = worker_fixture(store)
    sessions = {'worker_%03d'%i:session_fixture('worker_%03d'%i) for i in range(40)}
    store.transact_objects('FIXTURE_MANY','many',[('sessions',sid) for sid in sessions],lambda s:s['sessions'].update(sessions))
    for _ in range(2):assert telemetry.sample(store);due(store)
    h.clock=time.monotonic;assert h.tick()
    for _ in range(2):assert telemetry.sample(store);due(store)
    with sqlite3.connect(store.db) as db:
        witness = json.loads(db.execute("SELECT witness FROM telemetry_worker_witness WHERE session_id='worker_one'").fetchone()[0])
    assert witness['confirmed'] and witness['counter']==2
    fact = json.loads((directory/'worker-heartbeat.json').read_text());fact['counter']=1
    atomic(directory/'worker-heartbeat.json',canonical(fact))
    for _ in range(2):assert telemetry.sample(store);due(store)
    value = next(w for w in reader.telemetry()['workers'] if w['execution_id']==public_id('worker_one'))
    assert value['heartbeat']['status']=='UNKNOWN'
    store.transact_objects('FIXTURE_DONE','done',[('sessions','worker_one')],lambda s:s['sessions']['worker_one'].update(status='ACCEPTED'))
    assert telemetry.sample(store)
    with sqlite3.connect(store.db) as db:assert not db.execute("SELECT 1 FROM telemetry_worker_witness WHERE session_id='worker_one'").fetchone()


def test_session_and_epoch_cas_discards_racing_sample(observed,monkeypatch):
    store,reader = observed;worker_fixture(store)
    original = sources.host
    def changed(*args):
        store.transact_objects('FIXTURE_CHANGE','change',[('sessions','worker_one')],lambda s:s['sessions']['worker_one'].update(generation='new'))
        return original(*args)
    monkeypatch.setattr(sources,'host',changed)
    assert not telemetry.sample(store) and reader.telemetry() is None


def test_indexed_worker_rotation_reports_partial_on_tail(observed,monkeypatch):
    store,reader = observed
    sessions = {'worker_%03d'%i:session_fixture('worker_%03d'%i) for i in range(40)}
    store.transact_objects('FIXTURE_MANY','many',[('sessions',sid) for sid in sessions],lambda s:s.setdefault('sessions',{}).update(sessions))
    clock = [time.monotonic()];monkeypatch.setattr(telemetry.time,'monotonic',lambda:clock[0])
    assert telemetry.sample(store);first = reader.telemetry()
    clock[0]+=2;assert telemetry.sample(store);second = reader.telemetry()
    assert len(first['workers'])==32 and len(second['workers'])==8
    assert first['workers_truncated'] and second['workers_truncated']
    assert {w['execution_id'] for w in first['workers']+second['workers']}=={public_id(sid) for sid in sessions}


def test_api_requires_auth_scope_and_returns_null_before_sample(web):
    store,auth,app,client = web
    path = '/api/v1/projects/project_one/telemetry'
    assert client.get(path).status_code==401
    login(client);assert client.get(path).json() is None
    assert telemetry.sample(store);value = client.get(path).json();validate('Telemetry',value)
    assert value['project_id']=='project_one' and client.get('/api/v1/projects/project_two/telemetry').status_code==404
