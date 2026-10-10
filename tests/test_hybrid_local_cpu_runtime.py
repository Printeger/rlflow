"""Original configured Core execution and managed STOP; not model autonomy."""
import copy
import json
import os
from pathlib import Path
from contextlib import ExitStack

import pytest

from rlflow.isolated_local_cpu import isolated_session
from rlflow.hybrid_local_cpu_runtime import LocalCpuGrant
from rlflow.hybrid_local_cpu_source import LocalCpuSourceOwner
from rlflow.store import Conflict


def test_original_configured_cpu_grant_budget_pool_source_and_no_handoff_stop(tmp_path):
    tmp_path.chmod(0o700)
    spec=dict(purpose='research',code="import json; print(json.loads(open(WORK+'/parameters.json').read()))",
              inputs={'parameters.json':'{"threshold": 4}'},seconds=10,
              limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
    # Synthetic isolated confirmation, NOT independent product Review/human evidence.
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source'])
        assert attempt['origin']['kind']=='LOCAL_CONFIGURED_CPU'
        assert runtime._current(attempt)['status']=='HELD' and runtime.pool.snapshot()['occupied']==1
        assert row['status']=='ALLOCATED_NO_HANDOFF'
        before=(runtime.store.version(),runtime.pool.snapshot()['version'])
        assert before==(runtime.store.version(),runtime.pool.snapshot()['version'])
        assert not attempt['spawn_entered'] and not attempt['release_entered'] and row['producer'] is None
        with pytest.raises(PermissionError):copy.copy(runtime).start(lease)
        with pytest.raises(PermissionError):copy.copy(runtime.sources).poll(attempt['source'])
        with pytest.raises(PermissionError):session['adapter'].start(None)
        with pytest.raises(PermissionError):session['plans'].start(None)
        with pytest.raises(PermissionError):runtime.register(session['bundle'],session['token'],session['observation'],
            session['claim'],request_key='forged_grant',scenario='local_cpu',
            local_cpu_grant=LocalCpuGrant(session['grant'].id,session['grant'].raw))
        runtime.stop_to_terminal(lease)
        assert runtime.pool.snapshot()['occupied']==0 and runtime._current(attempt)['status']=='SETTLED'
        assert all(fd is None for fd in row['fds'].values())
        assert attempt['terminal']['wall_seconds']==0
        assert attempt['terminal']['managed_service_proof'] is None
        assert not attempt['terminal']['local_cpu_release_attempted']
        with pytest.raises(Conflict,match='STOP'):runtime.start(lease)


def test_actual_configured_core_task_result_managed_stop_budget_and_free(tmp_path):
    import time
    from rlflow.hybrid_local_cpu_manager import _originals,_stop_replies
    original_managers=set(_originals)
    original_replies=set(_stop_replies)
    tmp_path.chmod(0o700)
    spec=_spec();spec['code']="""import json,collections,os,time
data=json.loads(open(WORK+'/payload.txt').read())
print(json.dumps(dict(sorted(collections.Counter(data).items()))),flush=True)
child=os.fork()
if not child:
 os.setsid()
 while True:time.sleep(1)
"""
    spec['inputs']={'payload.txt':'["blue","gold","blue","red","gold","blue"]'}
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source'])
        runtime.start(lease)
        end=time.monotonic()+10
        while row['task_closed'] is None:
            runtime.poll(lease)
            assert time.monotonic()<end,'actual configured Core task deadline exceeded'
            time.sleep(.01)
        result=runtime.collect_local_result(lease)
        assert json.loads(result['outputs']['stdout']['text'])==dict(blue=3,gold=2,red=1)
        assert result['outputs']['stderr']['text']=='' and not result['condition_evidence']
        assert len({row['producer'].pid,row['ready']['keeper']['pid'],row['ready']['task']['pid']})==3
        assert attempt['release_entered'] and runtime.pool.snapshot()['occupied']==1
        runtime.stop_to_terminal(lease)
        assert runtime._current(attempt)['status']=='SETTLED' and runtime.pool.snapshot()['occupied']==0
        from rlflow.hybrid_budget_ledger import reservation_key
        from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
        reader=LocalCpuTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=runtime.plans.workspace.store_epoch)
        warm=reader.recover_task_evidence(reservation_key(session['reserve']))
        assert warm['task_evidence']['physical_scope_status']=='UNKNOWN'  # Original owner remains live.
        assert warm['task_evidence']['physical_scope_proof'] is None
        proof=attempt['terminal']['managed_service_proof']
        assert proof['job']['result']=='done' and proof['keeper_kernel_terminal']
        assert proof['original_manager_connection_closed'] and proof['original_protocol_closed']
        assert proof['manager']['MainPID']==0 and proof['manager']['ActiveState']=='inactive'
        assert all(fd is None for fd in row['fds'].values())
        manager=row['manager']
        assert manager.closed and _originals[id(manager)] is manager
        original_reply=_stop_replies[id(manager)]
        # Alias corruption must fail BEFORE deleting any original manager;
        # closed cached proofs still support the same owner's cleanup retry.
        alias=object();runtime.sources._attempts[id(alias)]=row
        try:
            with pytest.raises(Conflict,match='retirement row alias'):runtime.sources.shutdown()
            assert runtime.sources._live and _originals[id(manager)] is manager
            assert _stop_replies[id(manager)] is original_reply
            assert manager.stop()==json.loads(manager.stopped_raw)
        finally:del runtime.sources._attempts[id(alias)]
        (tmp_path/'actual-command.json').write_text(json.dumps(row['command']))
        (tmp_path/'actual-protocol.json').write_text(json.dumps(row['protocol_rows']))
        (tmp_path/'actual-terminal.json').write_text(json.dumps(attempt['terminal']))
        (tmp_path/'actual-result.json').write_text(json.dumps(result))
    assert set(_originals)==original_managers
    assert set(_stop_replies)==original_replies
    with pytest.raises(PermissionError):manager.close()


def test_original_input_close_failure_retained_without_free_or_duplicate_source(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    spec=dict(purpose='engineering',code="print(open(WORK+'/payload.txt').read())",
              inputs={'payload.txt':'original'},seconds=10,
              limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))
    with isolated_session(tmp_path,spec,approved=True,
            confirmation_reader=lambda proposal,confirmation:'APPROVE '+confirmation['scope_hash']) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);original=row['fds']['input:payload.txt']
        pinned=os.fstat(original)
        # Same inode rewrite cannot be laundered by changing the mutable row.
        path=row['path']/'work'/'payload.txt';path.write_text('changed')
        with pytest.raises(Conflict,match='input differs before G'):runtime.sources._physical(row)
        path.write_text('original')
        close=os.close
        def failed_input_close(fd):
            if fd==original:raise OSError(5,'injected original input close failure')
            close(fd)
        with monkeypatch.context() as fault:
            fault.setattr(os,'close',failed_input_close)
            with pytest.raises(Conflict,match='partial cleanup retained'):runtime.stop_to_terminal(lease)
        assert row['fds']['input:payload.txt']==original
        current=os.fstat(original)
        assert (current.st_dev,current.st_ino)==(pinned.st_dev,pinned.st_ino)
        assert all(fd is None for key,fd in row['fds'].items() if key!='input:payload.txt')
        assert runtime.pool.snapshot()['occupied']==1
        assert runtime._current(attempt)['status']!='SETTLED'
        assert not attempt['spawn_entered'] and not attempt['release_entered']
        runtime.stop_to_terminal(lease)
        assert all(fd is None for fd in row['fds'].values())
        assert runtime.pool.snapshot()['occupied']==0


def _spec():
    return dict(purpose='research',code="print(open(WORK+'/payload.txt').read())",
                inputs={'payload.txt':'approved'},seconds=10,
                limits=dict(memory_max=67108864,cpu_max='100000 100000',pids_max=12))


def _confirm(proposal,confirmation):return 'APPROVE '+confirmation['scope_hash']


def test_partial_recovery_allocation_failure_preserves_original_no_launch_cleanup(tmp_path,monkeypatch):
    from rlflow import hybrid_local_cpu_source as source_module
    from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
    from rlflow.hybrid_budget_ledger import reservation_key
    captured=[];allocate=LocalCpuSourceOwner._runtime_allocate;write=source_module._write_new
    tmp_path.chmod(0o700)
    def failed_report(path,raw):
        if path.name=='task-report':raise OSError(5,'original report allocation failed')
        return write(path,raw)
    def retained(source,owner,lease):
        try:return allocate(source,owner,lease)
        finally:
            attempt=owner._issued(lease);row=source._attempts.get(id(attempt['claim']))
            captured.append((owner,attempt,row))
            assert row is not None and not row.get('local_allocated')
            assert owner._recovery_source(attempt) is None
    monkeypatch.setattr(source_module,'_write_new',failed_report)
    monkeypatch.setattr(LocalCpuSourceOwner,'_runtime_allocate',retained)
    with pytest.raises(OSError,match='report allocation failed') as caught:
        with isolated_session(tmp_path,_spec(),approved=True,confirmation_reader=_confirm):
            pytest.fail('partial report allocation must not yield execution')
    assert not getattr(caught.value,'__notes__',[])
    owner,attempt,row=captured[0]
    assert not attempt['spawn_entered'] and not attempt['release_entered']
    assert not owner._live and all(fd is None for fd in row['fds'].values())
    entry=attempt['entries']['FIXTURE_SCOPE_STOPPED'];assert entry['decision']=='SETTLED'
    assert entry['request']['fixture_runtime']['producer'] is None
    reader=LocalCpuTaskReader(owner.store,project_id='isolated_local_cpu',store_epoch=owner.plans.workspace.store_epoch)
    key=entry['request']['reservation_id']
    assert reader.task(key)['task']['recorded_budget_status']=='SETTLED'
    assert reader.recover_task_evidence(key)['task_evidence'] is None


@pytest.mark.parametrize('expected_status',['PASS','FAIL'])
def test_actual_configured_machine_acceptance_runner_stop_and_original_cached_result(tmp_path,monkeypatch,expected_status):
    from rlflow.hybrid_local_cpu_manager import OriginalServiceManager
    bind=OriginalServiceManager.bind_ready;live_processes=[]
    def observed_bind(manager,keeper):
        bind(manager,keeper)
        manager._check_socket()
        pids=manager._call('GetUnitProcesses',b's',manager.unit.encode(),return_type=b'a(sus)')
        assert keeper['pid'] in pids
        live_processes.append(pids)
    monkeypatch.setattr(OriginalServiceManager,'bind_ready',observed_bind)
    tmp_path.chmod(0o700);spec=_spec();spec['purpose']='engineering'
    spec['code']="import json; data=json.loads(open(WORK+'/payload.txt').read()); print(','.join(sorted(set(data))))"
    spec['inputs']={'payload.txt':'["plum","pear","plum","apple"]'}
    spec['acceptance']={'method':'EXACT_STDOUT_UTF8',
        'stdout':'apple,pear,plum\n' if expected_status=='PASS' else 'wrong\n','stderr_empty':True}
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        result=runtime.run_local_cpu(lease)
        assert len(live_processes)==1 and live_processes[0]
        assert result['machine_acceptance']['status']==expected_status
        assert result['independent_review_status']=='NOT_PROVEN' and not result['condition_evidence']
        assert runtime.pool.snapshot()['occupied']==0 and runtime._current(attempt)['status']=='SETTLED'
        assert runtime._current(attempt)['fixture_runtime']['local_cpu_release_attempted']
        result['machine_acceptance']['status']='FORGED'
        assert runtime.run_local_cpu(lease)['machine_acceptance']['status']==expected_status
        assert attempt['terminal']['configured_local_result']['machine_acceptance']['status']==expected_status
        version=runtime.store.version();state=runtime.store.audit()
        assert runtime.store.replay()==state and runtime.store.recover()==state
        assert runtime.store.version()==version and runtime.pool.audit()['verified']
        result=runtime.collect_local_result(lease)
        (tmp_path/'configured-result.json').write_text(json.dumps(result))
        (tmp_path/'configured-terminal.json').write_text(json.dumps(attempt['terminal']))
        root=str(runtime.store.root);epoch=runtime.plans.workspace.store_epoch
        from rlflow.hybrid_budget_ledger import reservation_key
        reservation=reservation_key(session['reserve'])
    # A different process after original owner exit attaches only read-only
    # historical sources; it cannot recover original handles or replay G.
    import subprocess,sys
    script="""import json,sys
from rlflow.store import Store
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
store=Store.attach_existing(sys.argv[1],project_id='isolated_local_cpu',data_mode='fixture')
before=store.version()
reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=sys.argv[2])
result=reader.task(sys.argv[3],timeline=True)
assert store.version()==before
assert not hasattr(reader,'start') and not hasattr(reader,'stop')
print(json.dumps(result))
"""
    cold=subprocess.run([sys.executable,'-c',script,root,epoch,reservation],
        capture_output=True,text=True,timeout=15,check=True)
    view=json.loads(cold.stdout)
    assert view['task']['recorded_phase']=='FIXTURE_SCOPE_STOPPED'
    assert view['task']['current_execution_status']=='UNKNOWN' and not view['task']['controls_available']
    assert view['task']['local_result_status']=='ARCHIVED'
    assert view['task']['machine_acceptance_status']==expected_status and not view['task']['condition_evidence']
    assert view['managed_terminal_proof']['configured_local_result']==result
    assert view['managed_terminal_proof']['managed_service_proof']['job']['result']=='done'
    assert view['task']['recorded_release_attempted'] and view['events'][-1]['recorded_phase']=='FIXTURE_SCOPE_STOPPED'
    (tmp_path/'configured-cold.json').write_text(cold.stdout)
    # Root-controlled fixture corruption changes only private projections, not
    # original events. Both cold APIs must reject before publishing acceptance.
    from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
    from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET
    from rlflow.hybrid_goals import SECTIONS as GOALS
    from rlflow.hybrid_authority import SECTIONS as AUTHORITY
    from rlflow.store import Store,canonical
    from rlflow.hybrid_protocol import ProtocolError
    store=Store.attach_existing(root,project_id='isolated_local_cpu',data_mode='fixture')
    reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=epoch)
    with store.read_connection() as db:
        head=json.loads(db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',
            (BUDGET[2],reservation)).fetchone()[0])
        entry=json.loads(db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',
            (BUDGET[0],head['last_entry_key'])).fetchone()[0])
    for section,key in ((AUTHORITY[0],entry['policy_source']['approval_key']),
                        (GOALS[0],entry['policy_source']['contract_key'])):
        with store.connect() as db:
            raw=db.execute('SELECT value FROM projection WHERE section=? AND object_key=?',(section,key)).fetchone()[0]
            damaged=json.loads(raw)
            if section==AUTHORITY[0]:damaged['registry_witness']['tools']['local_cpu']['definition']['spec']['acceptance']['stdout']='changed'
            else:damaged['contract']['proposal']['objective']='changed original goal'
            db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(canonical(damaged).decode(),section,key))
        try:
            with pytest.raises((Conflict,ProtocolError)):reader.task(reservation)
            with pytest.raises((Conflict,ProtocolError)):reader.tasks()
        finally:
            with store.connect() as db:db.execute('UPDATE projection SET value=? WHERE section=? AND object_key=?',(raw,section,key))
    assert reader.task(reservation)['task']['machine_acceptance_status']==expected_status
    assert store.version()==version

    # Closed DTO gates are pure checks; these JSON copies are NEVER capabilities.
    from rlflow.hybrid_local_cpu_result import validate_terminal
    original=copy.deepcopy(view['managed_terminal_proof'])
    value=copy.deepcopy(entry['request']['fixture_runtime'])
    for mutation in ('status','criteria','extra','bool_pid','output','invocation'):
        damaged=copy.deepcopy(original);result=damaged['configured_local_result']
        if mutation=='status':result['machine_acceptance']['status']='UNRECOGNIZED'
        elif mutation=='criteria':result['machine_acceptance']['criteria_sha256']='sha256:'+'0'*64
        elif mutation=='extra':damaged['managed_service_proof']['manager']['unapproved']=True
        elif mutation=='bool_pid':damaged['managed_service_proof']['manager']['MainPID']=False
        elif mutation=='output':result['outputs']['stdout']['text']='forged'
        else:damaged['managed_service_proof']['manager']['InvocationID']='0'*32
        value['terminal_proof_sha256']=__import__('rlflow.hybrid_goals',fromlist=['digest']).digest(damaged)
        with pytest.raises((Conflict,ProtocolError)):validate_terminal(damaged,value)


def test_registration_allocation_registry_drift_cannot_freeze_unapproved_spec(tmp_path,monkeypatch):
    tmp_path.chmod(0o700)
    allocate=LocalCpuSourceOwner._runtime_allocate;captured=[]
    def changed_registry(source,owner,lease):
        original=owner.plans.registry._raw;config=json.loads(original)
        config['tools']['local_cpu']['definition']['spec']['code']="print('UNAPPROVED')"
        object.__setattr__(owner.plans.registry,'_raw',json.dumps(config).encode())
        try:return allocate(source,owner,lease)
        finally:
            object.__setattr__(owner.plans.registry,'_raw',original)
            attempt=owner._issued(lease)
            captured.append((attempt['source'],attempt['spawn_entered'],attempt['release_entered'],
                             len(source._attempts)))
    monkeypatch.setattr(LocalCpuSourceOwner,'_runtime_allocate',changed_registry)
    with pytest.raises(Conflict,match='spec differs from original approved grant'):
        with isolated_session(tmp_path,_spec(),approved=True,confirmation_reader=_confirm):
            pytest.fail('unapproved allocation accepted')
    assert captured==[(None,False,False,0)]


def test_mutable_allocation_marker_cannot_disable_frozen_source_checks(tmp_path):
    tmp_path.chmod(0o700)
    with isolated_session(tmp_path,_spec(),approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];attempt=runtime._issued(session['lease'])
        row=runtime.sources._issued(attempt['source']);path=row['path']/'launch.json'
        raw=path.read_bytes();config=json.loads(raw);config['code']="print('UNAPPROVED')"
        path.write_text(json.dumps(config));row['config_raw']=path.read_bytes();row['local_allocated']=False
        with pytest.raises(Conflict,match='binding incomplete'):runtime.sources._physical(row)
        row['local_allocated']=True
        with pytest.raises(Conflict,match='config changed'):runtime.sources._physical(row)
        path.write_bytes(raw);row['config_raw']=raw
        runtime.sources._physical(row)
        runtime.stop_to_terminal(session['lease'])


def test_stop_rejects_other_original_scope_before_any_source_cleanup(tmp_path):
    tmp_path.chmod(0o700)
    with ExitStack() as stack:
        sessions=[]
        for name in ('first','second'):
            parent=tmp_path/name;parent.mkdir(mode=0o700)
            sessions.append(stack.enter_context(isolated_session(parent,_spec(),approved=True,confirmation_reader=_confirm)))
        first,second=sessions;runtime=first['runtime'];attempt=runtime._issued(first['lease'])
        row=runtime.sources._issued(attempt['source']);other=second['runtime']._issued(second['lease'])
        fds=dict(row['fds']);otherrow=second['runtime'].sources._issued(other['source'])
        otherfds=dict(otherrow['fds']);row['runtime']=other
        with pytest.raises(PermissionError,match='same original configured CPU source'):
            runtime._stop_original_participant(first['lease'])
        assert row['fds']==fds and otherrow['fds']==otherfds
        assert runtime.pool.snapshot()['occupied']==second['runtime'].pool.snapshot()['occupied']==1
        row['runtime']=attempt
        original=attempt['source'];attempt['source']=None;claim=row['claim'];row['claim']=other['claim']
        with pytest.raises(PermissionError,match='same original configured CPU source'):
            runtime._stop_original_participant(first['lease'])
        assert row['fds']==fds and otherrow['fds']==otherfds
        row['claim']=claim
        source_owner=runtime.sources;runtime.sources=copy.copy(source_owner)
        with pytest.raises(PermissionError,match='exact original configured CPU source owner'):
            runtime._stop_original_participant(first['lease'])
        assert row['fds']==fds and otherrow['fds']==otherfds
        runtime.sources=source_owner;attempt['source']=original
        runtime.stop_to_terminal(first['lease'])
        assert otherrow['fds']==otherfds and second['runtime'].pool.snapshot()['occupied']==1


@pytest.mark.parametrize('fault',['control','report','manager_close'])
def test_actual_bound_manager_stop_survives_other_participant_failure(tmp_path,monkeypatch,fault):
    import time
    from rlflow.jobs import identity
    tmp_path.chmod(0o700);spec=_spec()
    spec['code']="import os,time; child=os.fork(); print(os.getpid(),flush=True); time.sleep(9)"
    if fault=='control':
        spec['code']="import signal;signal.signal(signal.SIGTERM,signal.SIG_IGN);"+spec['code']
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);runtime.start(lease)
        keeper=row['ready']['keeper'];manager=row['manager'];process=row['producer']
        pipe=process.stdin;read_protocol=runtime.sources._read_protocol;close_manager=manager.close
        stop_calls=[]
        if fault=='report':
            original_call=manager._call
            def counted_call(method,*args,**kwargs):
                if method=='StopUnit':stop_calls.append(method)
                return original_call(method,*args,**kwargs)
            monkeypatch.setattr(manager,'_call',counted_call)
        def failed(*args):raise OSError(5,'injected '+fault+' failure')
        if fault=='control':
            class FailedClose:
                def fileno(self):return pipe.fileno()
                @property
                def closed(self):return pipe.closed
                def close(self):failed()
            process.stdin=FailedClose()
        elif fault=='report':monkeypatch.setattr(runtime.sources,'_read_protocol',failed)
        else:monkeypatch.setattr(manager,'close',failed)
        with pytest.raises(Conflict,match='partial cleanup retained'):runtime.stop_to_terminal(lease)
        assert manager.stopped_raw is not None and json.loads(manager.stopped_raw)['job']['result']=='done'
        stopped=json.loads(manager.stopped_raw)
        assert stopped['original_manager_scope_processes']==[]
        assert stopped['unit_reference_held'] is True
        if fault=='control':
            assert (stopped['manager']['ActiveState'],stopped['manager']['SubState'])==('failed','failed')
            assert stopped['manager']['Result']=='timeout'
        else:
            assert (stopped['manager']['ActiveState'],stopped['manager']['SubState'])==('inactive','dead')
        assert identity(keeper['pid']) is None and process.poll() is not None
        assert all(fd is None for fd in row['fds'].values())
        assert runtime.pool.snapshot()['occupied']==1 and attempt['terminal'] is None
        process.stdin=pipe;monkeypatch.setattr(runtime.sources,'_read_protocol',read_protocol)
        monkeypatch.setattr(manager,'close',close_manager)
        if fault=='manager_close':
            runtime.stop_to_terminal(lease)
            assert runtime.pool.snapshot()['occupied']==0 and manager.closed
        else:
            # Lost trusted report cannot be reconstructed from manager DTOs.
            # Original safety retirement closes parent handles, NOT FREE.
            facts=runtime.shutdown_safety()
            assert not facts['pool_slots_freed'] and not facts['refund_enabled']
            assert runtime.pool.snapshot()['occupied']==1
        if fault=='report':
            assert stop_calls==['StopUnit']
            current=runtime._current(attempt)
            assert current['status']=='UNKNOWN' and current['fixture_runtime']['phase']=='STOP_REQUESTED'
            root=str(runtime.store.root);epoch=runtime.plans.workspace.store_epoch
            from rlflow.hybrid_budget_ledger import reservation_key
            reservation=reservation_key(session['reserve']);amount=session['reserve']['amount']
            version=runtime.store.version();state=runtime.store.audit()
            assert runtime.store.replay()==state and runtime.store.recover()==state
            assert runtime.store.version()==version
    if fault=='report':
        import subprocess,sys
        script="""import json,sys
from rlflow.store import Store
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
store=Store.attach_existing(sys.argv[1],project_id='isolated_local_cpu',data_mode='fixture')
version=store.version()
reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=sys.argv[2])
detail=reader.task(sys.argv[3],timeline=True)
assert reader.tasks()['items']==[detail['task']]
assert store.version()==version
assert not hasattr(reader,'start') and not hasattr(reader,'stop')
print(json.dumps(detail))
"""
        cold=subprocess.run([sys.executable,'-c',script,root,epoch,reservation],
            capture_output=True,text=True,timeout=15,check=True)
        view=json.loads(cold.stdout);task=view['task']
        assert task['recorded_phase']=='STOP_REQUESTED' and task['recorded_budget_status']=='UNKNOWN'
        assert task['recorded_reserved_amount']==amount and task['recorded_unknown_exposure']==amount
        assert task['cold_recovery_action']=='READ_ONLY_HISTORY_NO_EXECUTION_REPLAY'
        assert task['current_execution_status']=='UNKNOWN' and not task['controls_available']
        assert task['machine_acceptance_status']=='UNKNOWN' and not task['condition_evidence']
        assert view['managed_terminal_proof'] is None
        assert view['events'][-1]['recorded_phase']=='STOP_REQUESTED'
        assert len([event for event in view['events'] if event['recorded_phase']=='RELEASE_INTENT'])==1
        (tmp_path/'abnormal-cold.json').write_text(cold.stdout)


def test_actual_lost_stop_return_retires_only_parent_preserves_cold_exposure(tmp_path,monkeypatch):
    from rlflow.jobs import identity
    from rlflow.hybrid_local_cpu_manager import _originals
    original_managers=set(_originals)
    from rlflow.hybrid_budget_ledger import reservation_key
    tmp_path.chmod(0o700);spec=_spec()
    spec['code']='import os,time; child=os.fork(); print(os.getpid(),flush=True); time.sleep(9)'
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);runtime.start(lease)
        manager=row['manager'];original_call=manager._call;calls=[];actual_jobs=[]
        def lose_return(method,*args,**kwargs):
            if method!='StopUnit':return original_call(method,*args,**kwargs)
            calls.append(method)
            read=manager.lib.sd_bus_message_read
            def lose_decode(message,types,*values):
                status=read(message,types,*values)
                if types==b'o':
                    import ctypes
                    actual_jobs.append(ctypes.cast(values[0],ctypes.POINTER(ctypes.c_char_p)).contents.value.decode())
                    raise OSError(5,'injected original STOP wire decode lost before strong receipt')
                return status
            with monkeypatch.context() as wire_fault:
                wire_fault.setattr(manager.lib,'sd_bus_message_read',lose_decode)
                return original_call(method,*args,**kwargs)
        monkeypatch.setattr(manager,'_call',lose_return)
        with pytest.raises(Conflict,match='partial cleanup retained'):runtime.stop_to_terminal(lease)
        assert calls==['StopUnit'] and actual_jobs[0].startswith('/org/freedesktop/systemd1/job/')
        assert manager.stop_entered and manager.stop_job is None and manager.stopped_raw is None
        from rlflow.hybrid_local_cpu_manager import _stop_replies
        assert id(manager) not in _stop_replies
        assert manager.closed and row['producer'].poll() is not None
        assert identity(row['ready']['keeper']['pid']) is None
        assert runtime.sources._kernel_terminals[id(row)] is row
        assert all(fd is None for fd in row['fds'].values())
        assert attempt['terminal'] is None and runtime.pool.snapshot()['occupied']==1
        version=runtime.store.version()
        with pytest.raises(Conflict,match='partial cleanup retained'):runtime.stop_to_terminal(lease)
        assert calls==['StopUnit'] and runtime.store.version()==version
        # Closed descriptors cannot reconstruct a lost kernel witness from
        # DTOs, process names or a currently missing PID. Retain original owner.
        original_witness=runtime.sources._kernel_terminals.pop(id(row))
        with pytest.raises(Conflict,match='partial cleanup retained'):runtime.shutdown_safety()
        assert runtime._live and runtime.sources._live and runtime.pool.snapshot()['occupied']==1
        assert _originals[id(manager)] is manager
        runtime.sources._kernel_terminals[id(row)]=original_witness
        facts=runtime.shutdown_safety()
        assert facts['state']=='PHYSICAL_CLOSED_EXPOSURE_UNKNOWN'
        assert facts['retirement_scope']=='ORIGINAL_PARENT_HANDLES_ONLY'
        assert facts['managed_scope_status']=='UNKNOWN'
        assert not facts['pool_slots_freed'] and not facts['refund_enabled'] and not facts['runtime_stopped']
        assert not runtime._live and not runtime.sources._live and calls==['StopUnit']
        assert set(_originals)==original_managers
        with pytest.raises(PermissionError):manager.close()
        assert runtime.pool.snapshot()['occupied']==1
        current=runtime.store.audit()
        assert runtime.store.replay()==current and runtime.store.recover()==current
        assert runtime.store.version()==version
        root=str(runtime.store.root);epoch=runtime.plans.workspace.store_epoch
        reservation=reservation_key(session['reserve']);amount=session['reserve']['amount']
    import subprocess,sys
    script="""import json,sys
from rlflow.store import Store
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
store=Store.attach_existing(sys.argv[1],project_id='isolated_local_cpu',data_mode='fixture')
version=store.version()
reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=sys.argv[2])
view=reader.task(sys.argv[3],timeline=True)
assert reader.tasks()['items']==[view['task']]
assert store.version()==version
assert not hasattr(reader,'start') and not hasattr(reader,'stop')
print(json.dumps(view))
"""
    result=subprocess.run([sys.executable,'-c',script,root,epoch,reservation],
        capture_output=True,text=True,timeout=15,check=True)
    view=json.loads(result.stdout);task=view['task']
    assert task['recorded_phase']=='STOP_REQUESTED' and task['recorded_budget_status']=='UNKNOWN'
    assert task['recorded_reserved_amount']==amount and task['recorded_unknown_exposure']==amount
    assert task['current_execution_status']=='UNKNOWN' and not task['controls_available']
    assert task['machine_acceptance_status']=='UNKNOWN' and not task['condition_evidence']
    assert view['managed_terminal_proof'] is None
    assert len([event for event in view['events'] if event['recorded_phase']=='RELEASE_INTENT'])==1
    (tmp_path/'lost-stop-return-cold.json').write_text(result.stdout)


def test_actual_retained_stop_wire_reply_recovers_caller_return_and_free(tmp_path,monkeypatch):
    from rlflow.hybrid_local_cpu_manager import _stop_replies
    from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
    from rlflow.hybrid_budget_ledger import reservation_key
    original_replies=set(_stop_replies);tmp_path.chmod(0o700)
    spec=_spec();spec['code']='import os,time; child=os.fork(); print(os.getpid(),flush=True); time.sleep(9)'
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        row=runtime.sources._issued(attempt['source']);runtime.start(lease)
        manager=row['manager'];call=manager._call;calls=[]
        def lost_caller(method,*args,**kwargs):
            value=call(method,*args,**kwargs)
            if method=='StopUnit':
                calls.append(method)
                assert _stop_replies[id(manager)].job==value
                raise OSError(5,'caller return lost AFTER original wire receipt retained')
            return value
        monkeypatch.setattr(manager,'_call',lost_caller)
        runtime.stop_to_terminal(lease)
        assert calls==['StopUnit'] and manager.closed and manager.stop_job==_stop_replies[id(manager)].job
        assert runtime._current(attempt)['status']=='SETTLED' and runtime.pool.snapshot()['occupied']==0
        proof=attempt['terminal']['managed_service_proof']
        assert proof['job']['path']==manager.stop_job and proof['job']['result']=='done'
        assert proof['manager']['MainPID']==0 and proof['original_manager_scope_processes']==[]
        assert proof['keeper_kernel_terminal'] and proof['transport_reaped']
        assert proof['original_manager_connection_closed'] and proof['original_protocol_closed']
        assert all(fd is None for fd in row['fds'].values())
        version=runtime.store.version();pool_version=runtime.pool.snapshot()['version']
        runtime.stop_to_terminal(lease)
        assert calls==['StopUnit'] and runtime.store.version()==version and runtime.pool.snapshot()['version']==pool_version
        root=runtime.store.root;epoch=runtime.plans.workspace.store_epoch;key=reservation_key(session['reserve'])
        (tmp_path/'retained-stop-terminal.json').write_text(json.dumps(attempt['terminal']))
    assert set(_stop_replies)==original_replies
    reader=LocalCpuTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=epoch)
    history=reader.task(key,timeline=True)
    assert history['task']['recorded_budget_status']=='SETTLED'
    assert history['managed_terminal_proof']['managed_service_proof']==proof
    assert history['recorded_settled_usage']['experiment_starts']==1
    (tmp_path/'retained-stop-cold.json').write_text(json.dumps(history))


@pytest.mark.parametrize('expected_status',['PASS','FAIL'])
def test_actual_configured_research_metrics_budget_stop_and_cold(tmp_path,expected_status):
    from rlflow.hybrid_budget_ledger import reservation_key
    from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
    tmp_path.chmod(0o700);spec=_spec()
    spec['code']="""import json,math
data=json.loads(open(WORK+'/observations.json').read())
x=[p[0] for p in data];y=[p[1] for p in data]
mx=sum(x)/len(x);my=sum(y)/len(y)
slope=sum((a-mx)*(b-my) for a,b in data)/sum((a-mx)**2 for a in x)
intercept=my-slope*mx
mse=sum((b-(intercept+slope*a))**2 for a,b in data)/len(data)
print(json.dumps({'slope':slope,'mse':mse,'samples':len(data)},sort_keys=True))
"""
    spec['inputs']={'observations.json':'[[0,0.1],[1,1.9],[2,4.2],[3,5.8],[4,8.1]]'}
    spec['acceptance']={'method':'JSON_METRICS_RANGE','stderr_empty':True,
        'metrics':{'slope':{'min':1.8,'max':2.2},'mse':{'min':0,'max':.1 if expected_status=='PASS' else .0001},
                   'samples':{'min':5,'max':5}}}
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        reservation=reservation_key(session['reserve']);epoch=runtime.plans.workspace.store_epoch
        reader=LocalCpuTaskReader(runtime.store,project_id='isolated_local_cpu',store_epoch=epoch)
        assert reader.task(reservation)['recorded_settled_usage'] is None
        result=runtime.run_local_cpu(lease)
        assert result['machine_acceptance']['status']==expected_status
        metrics=json.loads(result['outputs']['stdout']['text'])
        assert 1.8<metrics['slope']<2.2 and .0001<metrics['mse']<.1 and metrics['samples']==5
        assert runtime.pool.snapshot()['occupied']==0 and runtime._current(attempt)['status']=='SETTLED'
        view=reader.task(reservation,timeline=True)
        assert view['recorded_settled_usage']['experiment_starts']==1
        assert view['recorded_settled_usage']['wall_seconds']==attempt['terminal']['wall_seconds']
        assert view['recorded_settled_usage']['model_sessions']==view['recorded_settled_usage']['gpu_device_seconds']==0
        version=runtime.store.version();state=runtime.store.audit()
        assert runtime.run_local_cpu(lease)==result
        assert runtime.store.replay()==state and runtime.store.recover()==state and runtime.store.version()==version
        assert reader.task(reservation,timeline=True)==view
        root=str(runtime.store.root)
        (tmp_path/'research-result.json').write_text(json.dumps(result))
        (tmp_path/'research-history.json').write_text(json.dumps(view))
    import subprocess,sys
    script="""import json,sys
from rlflow.store import Store
from rlflow.hybrid_local_cpu_reads import LocalCpuTaskReader
store=Store.attach_existing(sys.argv[1],project_id='isolated_local_cpu',data_mode='fixture')
version=store.version()
reader=LocalCpuTaskReader(store,project_id='isolated_local_cpu',store_epoch=sys.argv[2])
view=reader.task(sys.argv[3],timeline=True)
assert store.version()==version and not hasattr(reader,'start') and not hasattr(reader,'stop')
print(json.dumps(view))
"""
    cold=subprocess.run([sys.executable,'-c',script,root,epoch,reservation],
        capture_output=True,text=True,timeout=15,check=True)
    assert json.loads(cold.stdout)==view
    assert view['task']['machine_acceptance_status']==expected_status
    assert not view['task']['condition_evidence'] and view['task']['independent_review_status']=='NOT_PROVEN'
    assert view['task']['current_execution_status']=='UNKNOWN' and not view['task']['controls_available']
    (tmp_path/'research-cold.json').write_text(cold.stdout)


def test_approved_trusted_module_pins_cannot_be_replaced_during_allocation(tmp_path,monkeypatch):
    tmp_path.chmod(0o700);allocate=LocalCpuSourceOwner._runtime_allocate;captured=[]
    def changed_modules(source,owner,lease):
        original=owner.plans.registry._raw;config=json.loads(original)
        config['tools']['local_cpu']['definition']['modules']['hybrid_local_runner_keeper.py']='sha256:'+'0'*64
        object.__setattr__(owner.plans.registry,'_raw',json.dumps(config).encode())
        try:return allocate(source,owner,lease)
        finally:
            object.__setattr__(owner.plans.registry,'_raw',original);attempt=owner._issued(lease)
            captured.append((attempt['source'],attempt['spawn_entered'],attempt['release_entered'],len(source._attempts)))
    monkeypatch.setattr(LocalCpuSourceOwner,'_runtime_allocate',changed_modules)
    with pytest.raises(Conflict,match='module pins changed before allocation'):
        with isolated_session(tmp_path,_spec(),approved=True,confirmation_reader=_confirm):
            pytest.fail('unapproved trusted module pins accepted')
    assert captured==[(None,False,False,0)]


def test_actual_json_expansion_rejects_result_before_cache_but_still_stops_and_settles(tmp_path):
    tmp_path.chmod(0o700);spec=_spec();spec['purpose']='engineering'
    spec['code']="import os; os.write(1,b'\\x00'*40000)"
    spec['acceptance']={'method':'EXACT_STDOUT_UTF8','stdout':'not-the-output','stderr_empty':True}
    with isolated_session(tmp_path,spec,approved=True,confirmation_reader=_confirm) as session:
        runtime=session['runtime'];lease=session['lease'];attempt=runtime._issued(lease)
        with pytest.raises(Conflict,match='bound'):
            runtime.run_local_cpu(lease)
        assert attempt.get('local_result_raw') is None
        assert runtime._current(attempt)['status']=='SETTLED' and runtime.pool.snapshot()['occupied']==0
        proof=runtime._current(attempt)['fixture_runtime']['local_cpu_terminal_proof']
        assert proof['configured_local_result'] is None and proof['managed_service_proof']['job']['result']=='done'
        assert all(fd is None for fd in runtime.sources._issued(attempt['source'])['fds'].values())
