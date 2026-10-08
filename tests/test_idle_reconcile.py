"""No-work optimization must preserve reconciliation and legacy return API."""
from rlflow import engine, telemetry
from rlflow.store import Store
from rlflow.observation import enable, ObservationReader
from tests.acceptance_tasks_v1 import task


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
