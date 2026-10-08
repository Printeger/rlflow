import json
import sqlite3
import time
import pytest
from rlflow.store import Store, canonical, Conflict
from rlflow.snapshot_maintenance import maintain, Maintenance
from rlflow.observation import enable, ObservationReader


@pytest.fixture
def due(tmp_path):
    store=Store(tmp_path/'state');store.transact_objects('FIXTURE','initial',[('historical','item')],lambda s:s['historical'].update(item={'value':1}))
    with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=1')
    return store


def slot(store):
    with store.connect() as db:return tuple(db.execute('SELECT due_version,last_complete FROM snapshot_due').fetchone())


def test_thousandth_write_only_marks_due_and_marker_query_is_indexed(tmp_path,monkeypatch):
    store=Store(tmp_path/'state')
    with store.lock(),store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for i in range(1,1000):store._commit(db,'FIXTURE',str(i),dict(format=2,put=[],delete=[],details=None),i-1,'fixture','fixture',None)
    monkeypatch.setattr(store,'replay',lambda *a:pytest.fail('whole projection inside write'))
    store.transact_objects('FIXTURE','1000',[('historical','item')],lambda s:s['historical'].update(item=1))
    assert slot(store)==(1000,0)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==0
        plan=' '.join(str(tuple(r)) for r in db.execute("EXPLAIN QUERY PLAN SELECT section,value FROM projection WHERE object_key=''") )
        assert 'projection_markers' in plan


def test_complete_snapshot_preserves_business_and_restores_tail(due):
    store=due;enable(store,'project_snapshot',data_mode='fixture');reader=ObservationReader(store.root)
    version,cursor,state=store.version(),reader.head()['cursor'],store.replay()
    assert maintain(store) and slot(store)==(0,version)
    assert store.version()==version and reader.head()['cursor']==cursor and store.replay()==state
    store.transact_objects('NEXT','next',[('historical','item')],lambda s:s['historical'].update(item={'value':2}))
    expected=store.audit()
    with store.connect() as db:db.execute('DELETE FROM projection')
    assert store.recover()==expected


def test_new_writer_proceeds_during_build_and_newer_due_survives(due,monkeypatch):
    store=due;from rlflow import snapshot_maintenance as module
    original=module.canonical
    def concurrent(value):
        store.transact_objects('NEXT','next',[('historical','item')],lambda s:s['historical'].update(item={'value':2}))
        with store.connect() as db:db.execute('UPDATE snapshot_due SET due_version=2')
        return original(value)
    monkeypatch.setattr(module,'canonical',concurrent)
    assert maintain(store) and slot(store)==(2,1) and store.version()==2
    with store.connect() as db:
        state=json.loads(db.execute('SELECT state FROM snapshots WHERE version=1').fetchone()[0])
        assert state['historical']['item']=={'value':1}
    assert store.recover()==store.audit()


@pytest.mark.parametrize('options',[{'max_bytes':1},{'max_rows':1},{'max_nodes':1},{'seconds':1e-12}])
def test_limits_leave_due_and_no_partial_snapshot(due,options):
    assert not maintain(due,**options) and slot(due)==(1,0)
    with due.connect() as db:assert not db.execute('SELECT 1 FROM snapshots').fetchone()


def test_corrupt_blob_or_descriptor_does_not_publish(due):
    store=due
    with store.connect() as db:
        db.execute("UPDATE projection SET value=? WHERE section='historical' AND object_key='item'",(json.dumps({'$rlflow_blob':'0'*64}),))
    assert not maintain(store) and slot(store)==(1,0)


def test_busy_writer_or_maintenance_lock_drops_without_wait(due):
    with due.lock():
        start=time.monotonic();assert not maintain(due);assert time.monotonic()-start<.5
    with due.lock('snapshot-maintenance'):
        start=time.monotonic();assert not maintain(due);assert time.monotonic()-start<.5
    assert slot(due)==(1,0)


def test_old_store_migration_preserves_events_and_existing_snapshots(due):
    store=due;store.snapshot()
    with store.connect() as db:
        before=[tuple(r) for r in db.execute('SELECT * FROM events')];snapshots=[tuple(r) for r in db.execute('SELECT * FROM snapshots')]
        db.execute('DROP TABLE snapshot_due')
    migrated=Store(store.root)
    assert slot(migrated)==(0,1) and not maintain(migrated)
    with migrated.connect() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM events')]==before
        assert [tuple(r) for r in db.execute('SELECT * FROM snapshots')]==snapshots


def test_corrupt_existing_snapshot_not_accepted_by_digest_column_alone(due):
    assert maintain(due)
    with due.connect() as db:
        db.execute("UPDATE snapshots SET state=x'00'")
        db.execute('UPDATE snapshot_due SET due_version=1')
    assert not maintain(due) and slot(due)==(1,1)


def test_existing_snapshot_wrong_storage_type_not_accepted(due):
    assert maintain(due)
    with due.connect() as db:
        db.execute('UPDATE snapshots SET state=CAST(state AS TEXT)')
        db.execute('UPDATE snapshot_due SET due_version=1')
    assert not maintain(due) and slot(due)==(1,1)


def test_structure_budget_is_checked_before_json_tree_allocation(due,monkeypatch):
    from rlflow import snapshot_maintenance as module
    monkeypatch.setattr(module.json,'loads',lambda *a:pytest.fail('oversize tree parsed before budget check'))
    assert not maintain(due,max_nodes=1) and slot(due)==(1,0)


def test_real_background_builder_does_not_hold_business_writer(due,monkeypatch):
    import threading
    from rlflow import snapshot_maintenance as module
    entered,release=threading.Event(),threading.Event();result=[];original=module.canonical
    def paused(value):entered.set();assert release.wait(3);return original(value)
    monkeypatch.setattr(module,'canonical',paused)
    job=threading.Thread(target=lambda:result.append(maintain(due)),daemon=True);job.start()
    try:
        assert entered.wait(2)
        due.transact_objects('NEXT','thread_next',[('historical','item')],lambda s:s['historical'].update(item={'value':2}))
        with due.connect() as db:db.execute('UPDATE snapshot_due SET due_version=2')
    finally:release.set();job.join(3)
    assert not job.is_alive() and result==[True] and slot(due)==(2,1)


@pytest.mark.parametrize('damage',['missing','negative','future','missing_snapshot'])
def test_existing_metadata_corruption_is_not_silently_reinitialized(due,damage):
    with due.connect() as db:
        if damage=='missing':db.execute('DELETE FROM snapshot_due')
        elif damage=='negative':db.execute('UPDATE snapshot_due SET due_version=-1')
        elif damage=='future':db.execute('UPDATE snapshot_due SET due_version=2')
        else:db.execute('UPDATE snapshot_due SET last_complete=1')
    with pytest.raises(Conflict,match='snapshot maintenance metadata'):Store(due.root)


def test_publication_failure_rolls_back_snapshot_and_ack(due,monkeypatch):
    original=sqlite3.connect
    class Failed(sqlite3.Connection):
        def execute(self,sql,*args,**kwargs):
            result=super().execute(sql,*args,**kwargs)
            if sql.startswith('INSERT OR IGNORE INTO snapshots'):raise sqlite3.OperationalError('injected before publication commit')
            return result
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k:original(*a,**k,factory=Failed))
    assert not maintain(due) and slot(due)==(1,0)
    with due.connect() as db:assert not db.execute('SELECT 1 FROM snapshots').fetchone()


def test_metadata_removed_during_build_does_not_publish(due,monkeypatch):
    from rlflow import snapshot_maintenance as module
    original=module.canonical
    def removed(value):
        with due.connect() as db:db.execute('DELETE FROM snapshot_due')
        return original(value)
    monkeypatch.setattr(module,'canonical',removed)
    assert not maintain(due)
    with due.connect() as db:assert not db.execute('SELECT 1 FROM snapshots').fetchone()


def test_maintenance_rate_and_single_job(due,monkeypatch):
    from rlflow import snapshot_maintenance as module
    now=[100];jobs=[]
    class Thread:
        def __init__(self,**kwargs):jobs.append(kwargs);self.active=False
        def start(self):self.active=True
        def is_alive(self):return self.active
    monkeypatch.setattr(module.threading,'Thread',Thread);monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    maintenance=Maintenance(due);assert maintenance.tick() and not maintenance.tick()
    now[0]+=61;assert not maintenance.tick()
    maintenance.thread.active=False;assert maintenance.tick() and len(jobs)==2


@pytest.mark.parametrize('boundary',['construct','publish','committed'])
def test_actual_process_exit_at_maintenance_boundaries(due,boundary):
    import subprocess,sys
    program=r'''
import contextlib,os,sqlite3,sys
from rlflow.store import Store
from rlflow import snapshot_maintenance as module
store=Store(sys.argv[1]);boundary=sys.argv[2]
if boundary=='construct':
    module.canonical=lambda value:os._exit(90)
elif boundary=='publish':
    original=sqlite3.connect
    class Connection(sqlite3.Connection):
        def execute(self,sql,*a,**k):
            result=super().execute(sql,*a,**k)
            if sql.startswith('INSERT OR IGNORE INTO snapshots'):os._exit(91)
            return result
    sqlite3.connect=lambda *a,**k:original(*a,**k,factory=Connection)
else:
    original=store.lock
    @contextlib.contextmanager
    def lock(name='writer',nonblocking=False):
        with original(name,nonblocking):yield
        if name=='writer':os._exit(92)
    store.lock=lock
module.maintain(store)
raise RuntimeError('death boundary was not reached')
'''
    result=subprocess.run([sys.executable,'-c',program,str(due.root),boundary],capture_output=True,text=True,timeout=10)
    assert result.returncode in {90,91,92},result.stderr
    restarted=Store(due.root)
    assert slot(restarted)==((0,1) if boundary=='committed' else (1,0))
    with restarted.connect() as db:assert db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==int(boundary=='committed')
    assert restarted.recover()==restarted.audit() and restarted.get('historical','item')=={'value':1}
