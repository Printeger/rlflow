import json
import sqlite3
import pytest
from rlflow.store import Store, Conflict, canonical, sha


def test_legacy_migration_preserves_event_bytes(tmp_path):
    store=Store(tmp_path)
    with store.connect() as db:
        payload=canonical({'set':{'paused':True,'historical':{'unknown':None}},'details':None}).decode()
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(1,'old','old','PAUSE','control',1,0,1,'legacy',1,'{}',payload,sha(json.loads(payload))))
        db.execute('DELETE FROM projection_meta')
        before=[tuple(r) for r in db.execute('SELECT * FROM events')]
    migrated=Store(tmp_path)
    assert migrated.replay()==migrated.audit()
    assert migrated.replay()['historical']['unknown'] is None
    with migrated.connect() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM events')]==before
    migrated.transact('RESUME','new',lambda s:s.update(paused=False))
    assert migrated.audit()==migrated.replay()


def test_scoped_update_does_not_scan_events_or_rewrite_unrelated(tmp_path,monkeypatch):
    store=Store(tmp_path)
    store.transact('SETUP','setup',lambda s:s['historical'].update(a=1,b=2))
    traced=[];connect=store.connect
    def trace():
        db=connect();db.set_trace_callback(traced.append);return db
    monkeypatch.setattr(store,'connect',trace)
    store.transact_objects('UPDATE','update',[('historical','a')],lambda s:s['historical'].update(a=3))
    assert store.get('historical','a')==3
    assert not any('SELECT * FROM events' in q for q in traced)
    assert not any("'historical','b'" in q for q in traced)
    assert store.replay()==store.audit()
    with store.connect() as db:
        assert db.execute("SELECT version FROM projection WHERE section='historical' AND object_key='b'").fetchone()[0]==1


def test_snapshot_recovery_and_corruption(tmp_path):
    store=Store(tmp_path)
    store.transact('A','a',lambda s:s['historical'].update(x=1))
    store.snapshot()
    store.transact('B','b',lambda s:s['historical'].update(x=2))
    expected=store.audit()
    with store.connect() as db: db.execute('DELETE FROM projection')
    assert store.recover()==expected
    with store.connect() as db: db.execute("UPDATE snapshots SET state=x'00'")
    with pytest.raises(Conflict,match='snapshot'):store.recover()
    assert store.replay()==expected


def test_commit_failure_rolls_back_event_and_objects(tmp_path,monkeypatch):
    store=Store(tmp_path)
    original=store._commit
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('crash before commit')
    monkeypatch.setattr(store,'_commit',fail)
    with pytest.raises(RuntimeError):
        store.transact_objects('A','a',[('historical','x')],lambda s:s['historical'].update(x=1))
    assert store.version()==0
    assert store.audit()==store.replay()


def test_large_immutable_values_and_optional_map_replay(tmp_path):
    store=Store(tmp_path)
    value='a'*100000
    store.transact_objects('A','a',[('accounting_corrections','x')],lambda s:s.setdefault('accounting_corrections',{}).update(x=value))
    assert store.audit()==store.replay()
    assert store.get('accounting_corrections','x')==value
    with store.connect() as db:
        assert len(db.execute('SELECT payload FROM events').fetchone()[0])<1000
        with pytest.raises(sqlite3.IntegrityError):db.execute('DELETE FROM blobs')


def test_scope_and_duplicate_guard(tmp_path):
    store=Store(tmp_path)
    with pytest.raises(Conflict):
        store.transact_objects('A','a',[('historical','x')],lambda s:s['historical'].update(y=2))
    calls=[]
    def change(s):calls.append(1);s['historical']['x']=1
    store.transact_objects('A','a',[('historical','x')],change)
    assert store.transact_objects('A','a',[('historical','x')],change)['duplicate']
    assert calls==[1]


def test_lazy_mapping_unpack_and_nested_blob_deduplication(tmp_path):
    store=Store(tmp_path)
    manifest={'a':'x'*100000}
    store.transact('A','a',lambda s:s['historical'].update(one={'manifest':manifest,'counter':1},two=2))
    view=store.view()
    assert dict(view['historical'])==store.replay()['historical']
    assert {**view['historical']}==store.replay()['historical']
    store.transact('B','b',lambda s:s['historical']['one'].update(counter=2))
    assert store.audit()==store.replay()
    with store.connect() as db:assert db.execute('SELECT count(*) FROM blobs').fetchone()[0]==1
    literal={'$rlflow_blob':'user data'}
    store.transact('C','c',lambda s:s['historical'].update(literal=literal))
    assert store.audit()==store.replay() and store.get('historical','literal')==literal


def test_indexed_scheduler_query_does_not_load_closed_objects(tmp_path,monkeypatch):
    store=Store(tmp_path)
    store.transact('A','a',lambda s:s['historical'].update(active={'status':'RUNNING'},closed={'status':'DONE','large':'x'*100000}))
    observed=[];connect=store.connect
    def trace():
        db=connect();db.set_trace_callback(observed.append);return db
    monkeypatch.setattr(store,'connect',trace)
    assert store.objects('historical',{'RUNNING'})==[('active',{'status':'RUNNING'})]
    assert not any('FROM blobs' in q for q in observed)
    assert not any('FROM events' in q for q in observed)


@pytest.mark.parametrize('boundary,expected',[('before_commit',0),('after_commit',1),('snapshot',0),('export',0)])
def test_actual_process_exit_at_durability_boundaries(tmp_path,boundary,expected):
    import subprocess,sys
    store=Store(tmp_path/'state')
    program=r'''
import os,sys,sqlite3
from rlflow.store import Store
root,boundary=sys.argv[1:];armed=False
class Connection(sqlite3.Connection):
    def commit(self):
        super().commit()
        if armed and boundary=='after_commit':os._exit(91)
    def execute(self,sql,*args,**kwargs):
        result=super().execute(sql,*args,**kwargs)
        if armed and boundary=='snapshot' and sql.startswith('INSERT OR REPLACE INTO snapshots'):os._exit(92)
        return result
original=sqlite3.connect
sqlite3.connect=lambda *a,**k:original(*a,**k,factory=Connection)
store=Store(root);armed=True
if boundary=='before_commit':
    original_commit=store._commit
    def crash(*a,**k):original_commit(*a,**k);os._exit(90)
    store._commit=crash
if boundary=='snapshot':store.snapshot()
elif boundary=='export':
    import rlflow.store as module
    original_atomic=module.atomic
    def crash(path,data):original_atomic(path,data);os._exit(93)
    module.atomic=crash;store.export()
else:store.transact('CRASH','one',lambda s:s['historical'].update(count=1))
'''
    result=subprocess.run([sys.executable,'-c',program,str(store.root),boundary],capture_output=True,text=True)
    assert result.returncode in {90,91,92,93},result.stderr
    recovered=Store(store.root)
    assert recovered.version()==expected
    assert recovered.replay()==recovered.audit()
    if expected:
        recovered.transact('CRASH','one',lambda s:pytest.fail('duplicate mutation'))
        assert recovered.get('historical','count')==1


def test_summary_does_not_expand_large_unselected_evidence(tmp_path,monkeypatch):
    store=Store(tmp_path)
    store.transact('A','a',lambda s:s['historical'].update(item={'status':'DONE','evidence':'x'*100000,'receipt':{'usage':{'tokens':5},'log':'y'*100000}}))
    traced=[];connect=store.connect
    def trace():
        db=connect();db.set_trace_callback(traced.append);return db
    monkeypatch.setattr(store,'connect',trace)
    assert store.summaries('historical',('status','receipt.usage'))=={'item':{'status':'DONE','receipt.usage':{'tokens':5}}}
    assert not any('FROM blobs' in q for q in traced)
