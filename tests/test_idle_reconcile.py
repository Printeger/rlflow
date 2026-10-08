"""No-work optimization must preserve reconciliation and legacy return API."""
from rlflow import engine, telemetry
from rlflow.store import Store
from rlflow.observation import enable, ObservationReader
from tests.acceptance_tasks_v1 import task
import pytest
import sqlite3
import json
from test_engine import harness
from rlflow.store import Conflict


def test_no_work_reconcile_can_omit_discarded_view(tmp_path,monkeypatch):
    store=Store(tmp_path/'state')
    enable(store,'project_idle_reconcile',data_mode='fixture')
    store.transact_objects('TASK_PROBE_BOOTSTRAP','fixture',[('tasks','archived')],
        lambda s:s['tasks'].update(archived=task('archived')))
    version=store.version();calls=[];reader=ObservationReader(store.root)
    cursor=reader.head()['cursor']
    with store.connect() as db:before=db.execute('SELECT sample_seq FROM telemetry_latest WHERE singleton=1').fetchone()[0]
    original=telemetry.sample
    def sample(s):
        calls.append(s);return original(s)
    monkeypatch.setattr(telemetry,'sample',sample)
    def forbidden(*args,**kwargs):raise AssertionError('discarded view enumerated archived keys')
    with monkeypatch.context() as patch:
        patch.setattr(store,'view',forbidden)
        result=engine.reconcile(store,return_view=False)
    assert result is None and calls==[store] and store.version()==version
    with store.connect() as db:after=db.execute('SELECT sample_seq FROM telemetry_latest WHERE singleton=1').fetchone()[0]
    assert after==before+1 and reader.head()['cursor']==cursor
    legacy=engine.reconcile(store)
    assert legacy['version']==version and legacy['tasks']['archived']['status']=='DONE'
    assert calls==[store,store] and store.version()==version


def test_closed_control_view_never_discovers_archive_keys(tmp_path,monkeypatch):
    store=Store(tmp_path/'state')
    store.transact_objects('TASK_PROBE_BOOTSTRAP','fixture',[('tasks','archived')],
        lambda s:s['tasks'].update(archived=task('archived')))
    def forbidden(*args,**kwargs):raise AssertionError('collection keys discovered')
    monkeypatch.setattr('rlflow.store.ObjectMap',forbidden)
    control=store.control_view()
    assert control=={'version':1,'paused':False,'enabled':False,'autonomous_tasks':[]}
    with store.connect() as db:db.execute("DELETE FROM projection WHERE section='paused'")
    with pytest.raises(Conflict,match='paused'):store.control_view()


def test_paused_dispatch_early_gate_avoids_full_view(tmp_path,monkeypatch):
    store=Store(tmp_path/'state')
    store.transact('PAUSE','fixture',lambda s:s.update(paused=True))
    def forbidden(*args,**kwargs):raise AssertionError('paused early gate read full view')
    monkeypatch.setattr(store,'view',forbidden)
    result=engine.dispatch_one(store)
    assert result is None and store.version()==1


def test_control_view_decodes_large_autonomous_blob(tmp_path):
    store=Store(tmp_path/'state');keys=[f'task_{i:05d}' for i in range(10000)]
    store.transact('AUTONOMOUS_FIXTURE','fixture',lambda s:s.update(autonomous_tasks=keys))
    with store.connect() as db:
        raw=db.execute("SELECT value FROM projection WHERE section='autonomous_tasks' AND object_key=''").fetchone()[0]
    assert '$rlflow_blob' in raw and store.control_view()['autonomous_tasks']==keys


def test_control_view_keeps_one_snapshot_and_closes_owned_reader(tmp_path,monkeypatch):
    store=Store(tmp_path/'state');writer=Store(store.root);original=store.connect
    readers=[];changed=[]
    def connect():
        db=original();readers.append(db)
        def trace(sql):
            if sql.startswith('SELECT section,value') and not changed:
                changed.append(True)
                writer.transact('PAUSE','concurrent',lambda s:s.update(paused=True))
        db.set_trace_callback(trace);return db
    with monkeypatch.context() as patch:
        patch.setattr(store,'connect',connect)
        control=store.control_view()
    assert changed and control['version']==0 and control['paused'] is False
    assert store.control_view()['version']==1 and store.control_view()['paused'] is True
    with pytest.raises(sqlite3.ProgrammingError,match='closed database'):readers[0].execute('SELECT 1')


@pytest.mark.parametrize('section,value',[
    ('paused',1),('enabled',None),('autonomous_tasks',{}),
    ('autonomous_tasks',[3]),('autonomous_tasks',{'$rlflow_blob':'0'*64}),
])
def test_control_view_invalid_fields_fail_closed_and_close_reader(tmp_path,monkeypatch,section,value):
    store=Store(tmp_path/'state')
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO projection(section,object_key,value,version) VALUES(?,'',?,0)",(section,json.dumps(value)))
    original=store.connect;readers=[]
    def connect():
        db=original();readers.append(db);return db
    monkeypatch.setattr(store,'connect',connect)
    with pytest.raises(Conflict):store.control_view()
    with pytest.raises(sqlite3.ProgrammingError,match='closed database'):readers[0].execute('SELECT 1')


def test_no_candidate_dispatch_avoids_full_view_but_keeps_code_guard(tmp_path,monkeypatch):
    store=Store(tmp_path/'state')
    store.transact_objects('TASK_PROBE_BOOTSTRAP','fixture',[('tasks','archived')],
        lambda s:s['tasks'].update(archived=task('archived')))
    version=store.version();calls=[];original=engine.daemon_generation
    def generation():
        calls.append(True);return original()
    def forbidden(*args,**kwargs):raise AssertionError('no-candidate full view')
    monkeypatch.setattr(engine,'daemon_generation',generation)
    monkeypatch.setattr(store,'view',forbidden)
    result=engine.dispatch_one(store)
    assert result is None and calls==[True] and store.version()==version


@pytest.mark.parametrize('change',['pause','blocked','delete','stop'])
def test_formal_dispatch_discards_hint_candidates_on_state_change(harness,monkeypatch,change):
    h=harness;before=h.store.replay();original=engine._dispatch_candidates;changed=[]
    def candidates(store,state,allow_paused):
        result=original(store,state,allow_paused)
        if set(state)=={'version','paused','enabled','autonomous_tasks'} and not changed:
            assert result,'fixture must reach the formal transition'
            changed.append(True)
            if change=='stop':(store.root/'STOP').write_text('isolated fixture stop')
            else:
                def mutate(s):
                    if change=='pause':s['paused']=True
                    elif change=='blocked':s['tasks'][h.task_id]['last_failure']={'blocked':True}
                    else:del s['tasks'][h.task_id]
                store.transact('FIXTURE_TRANSITION',change,mutate)
        return result
    def forbidden(*args,**kwargs):raise AssertionError('stale candidate reached preparation')
    monkeypatch.setattr(engine,'_dispatch_candidates',candidates)
    monkeypatch.setattr('rlflow.isolation.require_doctor',forbidden)
    result=engine.dispatch_one(h.store)
    after=h.store.replay()
    assert changed and result is None and after['sessions']=={}
    assert after['stages']==before['stages']
