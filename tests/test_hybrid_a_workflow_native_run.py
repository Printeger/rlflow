"""Native sequence wiring. Real G is intercepted; fabricated unit DATA is NOT qualification."""
import subprocess
import threading
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from rlflow.hybrid_native_model_runtime import NativeModelOwner,NativeModelLaunch
from rlflow.hybrid_native_model_source import NativeModelSourceOwner
from rlflow.store import Conflict,canonical
from tests.test_hybrid_native_account_cache import account_original,original,native_setup
from tests.test_hybrid_native_model_launch import register,ACTUAL_POPEN


def test_original_native_run_intercepted_g_cleans_and_never_redispatches(account_original,monkeypatch):
    owner,lease,home=register(account_original)
    owner.prepare_current_account_cache(lease);launch=owner.prepare_native_launch(lease)
    attempt=owner._issued(lease);row=owner.sources._issued(attempt['source']);writes=[]
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    with pytest.raises(PermissionError):
        owner.run_workflow_native(lease,launch=NativeModelLaunch(launch.id,launch.raw))
    assert owner._workflow_native_run is None
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    class NoG:
        def __init__(self,pipe):self.pipe=pipe
        def fileno(self):return self.pipe.fileno()
        @property
        def closed(self):return self.pipe.closed
        def close(self):return self.pipe.close()
        def write(self,data):
            assert data==b'G';writes.append(data)
            raise PermissionError('TEST run G intercepted, no model exec')
        def flush(self):pytest.fail('no G flush')
    def gate_only(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        process=ACTUAL_POPEN(argv,*args,**kwargs);process.stdin=NoG(process.stdin)
        return process
    monkeypatch.setattr(subprocess,'Popen',gate_only)
    with pytest.raises(PermissionError,match='TEST run G intercepted'):
        owner.run_workflow_native(lease,launch=launch)
    assert writes==[b'G'] and owner._workflow_native_completed is None
    assert owner._workflow_native_run['phase']=='STOP'
    assert owner._current(attempt)['status']=='UNKNOWN' and owner.pool.snapshot()['occupied']==0
    assert row['producer'].poll() is not None and row['producer'].stdin.closed
    assert all(fd is None for fd in row['fds'].values())
    assert not owner.sources._account_caches[id(attempt['source'])].descriptors()
    versions=(owner.store.version(),owner.pool.snapshot()['version'])
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('no redispatch'))
    with pytest.raises(Conflict,match='unresolved; no redispatch'):
        owner.run_workflow_native(lease,launch=launch)
    assert (owner.store.version(),owner.pool.snapshot()['version'])==versions
    assert (home/'auth.json').read_bytes()==b'{"synthetic":"NOT_A_TOKEN"}'
    assert owner.store.audit()==owner.store.replay()


def sequence_harness():
    """Pure flow harness deliberately bypasses issuers, never a product receipt."""
    calls=[];lease=object();launch=object();cap=object()
    attempt={'origin':{'native_model':{'seconds':1,'workflow':{
        'stage':'FIRST_ENGINEER','accounting_version':'A_REGISTRATION_CEILINGS_V1'}}}}
    @contextmanager
    def gate(*args):calls.append('guard');yield
    fake=SimpleNamespace(_issued=lambda value:attempt,_unit_check=lambda value:None,
        controller=SimpleNamespace(_refuse_nested_writer=lambda:None),
        _workflow_native_run_lock=threading.Lock(),_workflow_cpu_admission_lock=threading.RLock(),
        _workflow_native_run=None,_workflow_native_completed=None,_workflow_native_deadline=None,_safety_freeze=False,
        _actual=lambda:None,_check_launch=lambda *args:None,
        pool=SimpleNamespace(_lock=threading.RLock()),_gate=gate,
        sources=SimpleNamespace(_issued=lambda value:SimpleNamespace()),
        _current=lambda value:{'fixture_runtime':{'phase':'REGISTER_NO_HANDOFF'}},
        start=lambda *args,**kwargs:calls.append('start'),
        poll_native=lambda value:{'started_observed':True},
        collect_native_result=lambda value:cap,
        stop_to_terminal=lambda value:calls.append('stop'),
        _workflow_native_completion=lambda *args:{'SYNTHETIC_UNIT_DATA_NOT_QUALIFIED':True})
    fake._check_workflow_native_deadline=lambda value:NativeModelOwner._check_workflow_native_deadline(fake,value)
    return fake,lease,launch,cap,calls


def test_pure_flow_stops_before_receipt_and_repeats_only_frozen_data():
    fake,lease,launch,cap,calls=sequence_harness()
    result=NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    assert calls==['start','guard','stop'] and fake._workflow_native_run['phase']=='COMPLETE'
    result.clear()
    assert NativeModelOwner.run_workflow_native(fake,lease,launch=launch)=={'SYNTHETIC_UNIT_DATA_NOT_QUALIFIED':True}
    assert calls==['start','guard','stop']
    with pytest.raises(PermissionError):NativeModelOwner.run_workflow_native(fake,object(),launch=launch)


def test_pure_stop_failure_never_completes_or_restarts():
    fake,lease,launch,cap,calls=sequence_harness()
    def failed_stop(value):calls.append('failed_stop');raise OSError('TEST stop unresolved')
    fake.stop_to_terminal=failed_stop
    with pytest.raises(OSError,match='stop unresolved'):NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    assert fake._workflow_native_completed is None
    with pytest.raises(Conflict,match='unresolved; no redispatch'):
        NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    assert calls==['start','guard','failed_stop']


@pytest.mark.parametrize('stage',['guard','poll','collect'])
def test_pure_original_deadline_crossed_during_observation_never_completes(monkeypatch,stage):
    fake,lease,launch,cap,calls=sequence_harness();clock=[100.0]
    monkeypatch.setattr('rlflow.hybrid_native_model_runtime.time.monotonic',lambda:clock[0])
    if stage=='guard':
        @contextmanager
        def gate(*args):calls.append('guard');yield;clock[0]=101.0
        fake._gate=gate
    elif stage=='poll':
        def poll(value):clock[0]=101.0;return {'started_observed':True}
        fake.poll_native=poll
    else:
        def collect(value):clock[0]=101.0;return cap
        fake.collect_native_result=collect
    with pytest.raises(Conflict,match='deadline exceeded'):
        NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    assert calls==['start','guard','stop'] and fake._workflow_native_completed is None
    with pytest.raises(Conflict,match='unresolved; no redispatch'):
        NativeModelOwner.run_workflow_native(fake,lease,launch=launch)


def test_pure_primary_and_stop_failure_both_retained():
    fake,lease,launch,cap,calls=sequence_harness()
    def failed_start(*args,**kwargs):raise PermissionError('TEST original start failure')
    def failed_stop(*args):raise OSError('TEST original stop failure')
    fake.start=failed_start;fake.stop_to_terminal=failed_stop
    with pytest.raises(PermissionError,match='original start failure') as failure:
        NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    assert isinstance(failure.value.__cause__,OSError)
    assert 'Original native STOP incomplete: OSError' in failure.value.__notes__
    assert fake._workflow_native_completed is None


@pytest.mark.parametrize('freeze',['owner','physical','stop'])
def test_pure_source_entry_freeze_denies_new_result(freeze):
    runtime={};owner=SimpleNamespace(_safety_freeze=freeze=='owner')
    if freeze=='physical':runtime['physical_safety_freeze']=True
    if freeze=='stop':runtime['source_stop_latched']=True
    source=object()
    fake=SimpleNamespace(_lock=threading.RLock(),_model_results={},
        _released_original=lambda *args:(runtime,source,None,None))
    with pytest.raises(Conflict,match='STOP prohibits'):
        NativeModelSourceOwner.collect_native_result(fake,owner,object())
    assert not fake._model_results


@pytest.mark.parametrize('fence',['owner','physical','stop','deadline',
    'after_identity_owner','after_identity_physical','after_identity_stop'])
def test_synthetic_source_final_issue_fence_after_archive_preflight(tmp_path,fence):
    """Deliberately fabricated provenance. Tests only final-fence control flow."""
    source=object();lease=object();ack=object();clock=[0];samples=[]
    event={'type':'thread.started','thread_id':'SYNTHETIC_NOT_A_MODEL'}
    line=canonical(event)+b'\n';path=tmp_path/'synthetic-events';path.write_bytes(line)
    binding={'role':'Evaluator'}
    runtime={'started_ack':ack,'native_model_grant':SimpleNamespace(raw=canonical(binding)),
        'origin':{'native_model':binding}}
    review={'SYNTHETIC_REVIEW_DATA_NOT_QUALIFIED':True}
    # The ack must expose original-line-shaped DATA, but all provenance gates
    # below are explicit test substitutions, never actual Source qualification.
    ack=SimpleNamespace(raw=canonical({'line_sha256':'sha256:'+hashlib.sha256(line).hexdigest(),'event':event}))
    runtime['started_ack']=ack
    reader=SimpleNamespace(transcript=SimpleNamespace(offset=len(line),state='DONE'),
        _stamp=lambda:(0,0,len(line)))
    owner=SimpleNamespace(_safety_freeze=False,
        _current=lambda value:{'fixture_runtime':{'phase':'STARTED_AS_OBSERVED'}})
    def deadline(value):
        samples.append(True)
        if len(samples)==2:
            if fence=='after_identity_owner':owner._safety_freeze=True
            elif fence=='after_identity_physical':runtime['physical_safety_freeze']=True
            elif fence=='after_identity_stop':runtime['source_stop_latched']=True
        if clock[0]:raise Conflict('TEST original deadline expired at Source issue')
    owner._check_workflow_native_deadline=deadline
    def preflight(*args):
        if fence=='owner':owner._safety_freeze=True
        elif fence=='physical':runtime['physical_safety_freeze']=True
        elif fence=='stop':runtime['source_stop_latched']=True
        elif fence=='deadline':clock[0]=1
    owner._preflight_native_result_archive=preflight
    with path.open('rb') as stream:
        attempt={'producer':SimpleNamespace(poll=lambda:0),'fds':{'read':stream.fileno()}}
        fake=SimpleNamespace(_lock=threading.RLock(),_model_results={},_packet_failures=set(),
            _released_original=lambda *args:(runtime,source,attempt,(None,None,None,None,None,canonical({}))),
            _physical=lambda value:None,_runtime_started=lambda *args:ack,_check_pidfd=lambda *args,**kwargs:None,
            poll_packet_data=lambda value:{},finish_packet_data=lambda value:{'data_complete':True},
            _packet_origins={id(source):(None,reader)},_packet_completed={id(source):(canonical(review),)},
            packet_result_data=lambda value:{'usage':{'complete':True}},review_data=lambda value:review)
        message='deadline expired' if fence=='deadline' else 'STOP raced'
        with pytest.raises(Conflict,match=message):
            NativeModelSourceOwner.collect_native_result(fake,owner,lease)
        assert not fake._model_results


@pytest.mark.parametrize('damage',['cleared','foreign'])
def test_pure_strong_deadline_root_cannot_be_bypassed_by_sequence_cache(damage):
    fake,lease,launch,cap,calls=sequence_harness()
    NativeModelOwner.run_workflow_native(fake,lease,launch=launch)
    root=fake._workflow_native_deadline
    fake._workflow_native_run=None if damage=='cleared' else dict(root[0])
    with pytest.raises(PermissionError,match='original native workflow deadline'):
        fake._check_workflow_native_deadline(lease)
