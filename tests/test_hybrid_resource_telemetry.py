"""Actual original worker observation through authenticated cached telemetry."""
import copy
import json
import threading
import time

from fastapi.testclient import TestClient
import pytest

from rlflow.hybrid_resource_telemetry import FixedUnitTelemetry
from rlflow.hybrid_protocol import validate
from rlflow.web_api import Project, create_app
from rlflow.web_auth import AuthStore, Principal
from tests.test_hybrid_host_execution import shared, requests
from tests.test_execution_adapter import setup as native_setup

ORIGIN = 'http://127.0.0.1:8765'


def app_for(host, units, observers):
    auth = AuthStore([])
    projects = [Project(u.runtime.workspace.project_id,str(u.runtime.store.root),'fixture') for u in units]
    app = create_app(projects,auth,origin=ORIGIN,
        fixed_unit_telemetry={o.project_id:o for o in observers})
    tokens = [auth.issue_bearer(Principal('viewer_'+str(i),'human',{'viewer'},{p.id}))[0]
              for i,p in enumerate(projects)]
    return app, auth, [{'Authorization':'Bearer '+t} for t in tokens]


def test_original_actual_cpu_worker_sample_HTTP_then_STOP_retirement(shared, monkeypatch):
    host, units = shared
    observers = [FixedUnitTelemetry(host,u.lease) for u in units]
    app,auth,headers = app_for(host,units,observers)
    cpu = units[0]; owner = cpu.runtime; observer = observers[0]
    assert observer.latest() is None
    before = [u.runtime.store.version() for u in units]
    assert all(o.sample() for o in observers)
    assert [u.runtime.store.version() for u in units] == before
    first = observer.latest(); validate('Telemetry',first)
    assert first['host']['memory']['status']=='KNOWN' and first['host']['cpu']['status']=='UNKNOWN'
    assert first['workers'][0]['process']['status']=='UNKNOWN'
    captured = []
    register = owner._register_release
    def capture(attempt):
        value = register(attempt)
        assert observer.sample()
        sample = observer.latest(); captured.append(sample)
        assert sample['workers'][0]['process']['status']=='KNOWN'
        assert sample['workers'][0]['process']['scope']=='FIXED_WORKER_PROCESS'
        assert sample['workers'][0]['process']['rss_bytes']>0
        assert sample['host']['cpu']['status']=='KNOWN'
        return value
    monkeypatch.setattr(owner,'_register_release',capture)
    request = requests(units)[0]
    result = host.run(request[0],request[1],**request[2])
    assert result['status']=='EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'
    stopped = observer.latest()
    assert stopped['sample_seq']==captured[0]['sample_seq']+1
    assert stopped['observed_at']==captured[0]['observed_at']
    assert stopped['workers'][0]['process']['status']=='UNKNOWN'
    assert stopped['workers'][0]['heartbeat']['status']=='UNKNOWN'
    assert stopped['gpu']['status']=='UNKNOWN'
    assert observer.latest()['sample_id']==stopped['sample_id']
    version = owner.store.version()
    with monkeypatch.context() as patch:
        def no_effect(*args,**kwargs): pytest.fail('HTTP must only read original telemetry memory')
        for obj,name in ((observer,'sample'),(owner,'poll'),(owner,'collect_cpu_trial'),
                         (host.pool,'check'),(owner.sources,'poll'),(owner.store,'_commit')):
            patch.setattr(obj,name,no_effect)
        row = owner.sources._issued(owner._issued(cpu.lease)['source'])
        patch.setattr(row['producer'],'poll',no_effect)
        with TestClient(app,base_url=ORIGIN) as client:
            url = '/api/v1/projects/'+observer.project_id+'/telemetry'
            assert client.get(url).status_code==401
            assert client.get(url,headers=headers[1]).status_code==404
            response = client.get(url,headers=headers[0]); assert response.status_code==200
            validate('Telemetry',response.json())
            for secret in (str(owner.store.root),cpu.lease.id,owner._issued(cpu.lease)['origin']['nonce'],'boot_id','"pid"'):
                assert secret not in response.text
            detached = observer.latest(); detached['host']['memory']['status']='INVALID'
            assert observer.latest()['host']['memory']['status']=='KNOWN'
            read = observer.latest
            def revoke():
                value = read(); auth.revoke(headers[0]['Authorization'].split()[1]); return value
            patch.setattr(observer,'latest',revoke)
            assert client.get(url,headers=headers[0]).status_code==401
    assert owner.store.version()==version
    owner.shutdown()
    retired = observer.latest()
    assert all(m['status']=='UNKNOWN' for m in retired['host'].values())
    assert retired['sample_age_seconds']>=stopped['sample_age_seconds']
    assert retired['sample_seq']==captured[0]['sample_seq']+2
    print('actual_fixed_worker_known_sample',json.dumps(captured[0]),flush=True)
    print('actual_STOP_and_closed_owner_telemetry_UNKNOWN',json.dumps(retired),flush=True)


def test_original_busy_expiry_copy_scope_and_cancel_latch_are_fail_closed(shared, monkeypatch):
    host,units = shared; observer = FixedUnitTelemetry(host,units[0].lease)
    assert observer.sample()
    original = observer.latest()
    with pytest.raises(PermissionError): copy.copy(observer).latest()
    with pytest.raises(ValueError):
        create_app([Project(units[1].runtime.workspace.project_id,str(units[1].runtime.store.root),'fixture')],
            AuthStore([]),fixed_unit_telemetry={units[1].runtime.workspace.project_id:observer})
    for lock in (host.pool._lock,units[0].runtime._lock,units[0].runtime.sources._lock):
        acquired = threading.Event(); release = threading.Event()
        def hold():
            with lock: acquired.set(); assert release.wait(5)
        thread = threading.Thread(target=hold);thread.start();assert acquired.wait(1)
        try:
            began = time.monotonic();assert not observer.sample();assert time.monotonic()-began<.5
            assert observer.latest()['sample_id']==original['sample_id']
        finally: release.set();thread.join(5);assert not thread.is_alive()
    units[0]._cancelled.set()
    assert observer.latest()['host']['memory']['status']=='UNKNOWN'
    value,issued,source = observer._slot
    with monkeypatch.context() as patch:
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued+16)
        stale = observer.latest(); assert stale['sample_age_seconds']==16
        assert stale['sample_id']==original['sampler_epoch']+':'+str(original['sample_seq']+2)
        assert all(m['status']=='UNKNOWN' for m in stale['host'].values())
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued-1)
        assert all(m['status']=='UNKNOWN' for m in observer.latest()['host'].values())
    assert all(not u.runtime._issued(u.lease)['spawn_entered'] for u in units)


def test_uncancelled_clock_regression_cannot_revive_retired_sample(shared, monkeypatch):
    host,units=shared;observer=FixedUnitTelemetry(host,units[0].lease)
    assert observer.sample();original=observer.latest();issued=observer._slot[1]
    assert not units[0]._cancelled.is_set()
    with monkeypatch.context() as patch:
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued+16)
        stale=observer.latest();assert stale['host']['memory']['status']=='UNKNOWN'
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued+1)
        backwards=observer.latest();assert backwards['sample_id']==stale['sample_id']
        assert backwards['sample_age_seconds']==16 and backwards['host']['memory']['status']=='UNKNOWN'
    assert observer.latest()['sample_id']==stale['sample_id']
    assert observer.sample();fresh=observer.latest()
    assert fresh['sample_seq']>stale['sample_seq'] and fresh['host']['memory']['status']=='KNOWN'
    issued=observer._slot[1]
    with monkeypatch.context() as patch:
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued-1)
        bad=observer.latest()
        patch.setattr('rlflow.hybrid_resource_telemetry.time.monotonic',lambda:issued+1)
        assert observer.latest()['sample_id']==bad['sample_id']
        assert observer.latest()['host']['memory']['status']=='UNKNOWN'
    assert observer.latest()['observed_at']==fresh['observed_at']
    assert original['workers'][0]['process']['status']=='UNKNOWN'
