"""Isolated model-free core ingestion; fixture launch ACK is NOT vendor proof."""
import json
import os
from pathlib import Path
import pytest
from concurrent.futures import ThreadPoolExecutor
from rlflow import isolation, tool_collector as collector, tool_journal
from rlflow.observation import ObservationReader
from rlflow.store import Store, sha
from test_engine import harness  # noqa: F401
from test_startup_observation import startup  # noqa: F401


@pytest.fixture
def tools(startup):
    store,sid,directory,facts = startup
    request = json.loads((directory/'request.json').read_text())
    runtime = request.get('cpu_runtime')
    reads = [str(directory/'evidence')] if (directory/'evidence').is_dir() else []
    if runtime:reads.append(runtime['root'])
    config = {'role':request['role'],'candidate':str(Path(request['repo']).resolve()),'scratch':str(Path(request['scratch']).resolve()),
              'read_extra':reads,'write_roots':request.get('write_roots'),'execute_extra':[runtime['root']] if runtime else [],
              'memory_bytes':runtime['address_space_bytes'] if runtime else 2*1024**3,'command_seconds':request.get('command_seconds',120),
              'audit':str(directory/'result.json.commands.jsonl'),'tool_launch_directory':str(directory),
              'tool_context':{'schema_version':'1.0','session':sid,'generation':request['generation'],
                              'request_sha256':sha(request),'candidate_sha256':sha(request['before'])}}
    return store,sid,directory,config


def execute(config,ident='once'):
    return isolation.persistent_cpu_exec(config,{'command_id':ident,'command':'printf PRIVATE_TOOL_OUTPUT','timeout':5})


def rows(store,section):
    return store.replay().get(section,{})


def test_actual_return_ingested_once_without_budget_authority_or_public_raw_text(tools):
    store,sid,directory,config = tools
    result = execute(config);before = store.replay();reader = ObservationReader(store.root);cursor = reader.snapshot()['cursor']
    assert collector.collect(store,sid)
    receipts = rows(store,'tool_receipts');assert len(receipts)==1
    receipt = next(iter(receipts.values()))
    assert receipt['status']=='COLLECTED' and receipt['verification']=='VERIFIED'
    assert receipt['fact']['state']=='RETURNED' and receipt['fact']['result_sha256']==sha(result)
    assert receipt['validation_digest'] is not None
    assert receipt['task_id']==store.get('sessions',sid)['task_id']
    after = store.replay()
    for section in ('stages','tasks','sessions','approvals','authorizations','usage'):
        assert after.get(section)==before.get(section)
    public = json.dumps(reader.events(cursor))
    assert 'PRIVATE_TOOL_OUTPUT' not in public and str(directory) not in public
    assert 'CPU_EXEC_RETURN' not in public  # Private collector, no premature public tool schema.
    version = store.version();assert not collector.collect(store,sid);assert store.version()==version
    restarted = Store(store.root)
    assert restarted.replay()['tool_receipts']==receipts and not collector.collect(restarted,sid)


def test_null_registration_witness_never_upgrades_after_release(tools):
    store,sid,directory,config = tools
    ack = (directory/'launch-start_ack.json').read_bytes();(directory/'launch-start_ack.json').unlink()
    execute(config)
    (directory/'launch-start_ack.json').write_bytes(ack)
    assert collector.collect(store,sid)
    value = next(iter(rows(store,'tool_receipts').values()))
    assert value['status']=='COLLECTED' and value['verification']=='UNVERIFIED'
    assert value['reason']=='REGISTER_UNVERIFIED' and value['validation_digest'] is None
    assert 'task_id' not in value


def test_pending_without_result_stays_discoverable_and_missing_fact_is_recovered(tools,monkeypatch):
    store,sid,directory,config = tools
    original = isolation.cpu_exec
    def crash(*a,**k):raise OSError('injected command crash')
    monkeypatch.setattr(isolation,'cpu_exec',crash)
    with pytest.raises(OSError):execute(config)
    assert collector.collect(store,sid)
    receipt = next(iter(rows(store,'tool_receipts').values()));assert receipt['status']=='PENDING'
    path = directory/'commands'/receipt['registration']['command_digest']
    # Fixture delivers the original invocation's result; collector may not run it.
    result = original('printf PRIVATE_TOOL_OUTPUT',config['candidate'],config['scratch'],config['role'],timeout=5,
                      read_extra=config['read_extra'],write_roots=config['write_roots'],execute_extra=config['execute_extra'],
                      memory_bytes=config['memory_bytes'],command_seconds=config['command_seconds'],artifact_dir=path)
    result['checkpoint']=str(path);(path/'result.json').write_text(json.dumps(result))
    monkeypatch.setattr(isolation,'cpu_exec',lambda *a,**k:pytest.fail('collector cannot reexecute'))
    assert collector.collect(store,sid)
    value = next(iter(rows(store,'tool_receipts').values()))
    assert value['status']=='COLLECTED' and value['verification']=='VERIFIED'
    assert not (path/'return-observation.json').exists() and value['fact']['result_sha256']==sha(result)
    assert value['task_id']==store.get('sessions',sid)['task_id']


def test_frozen_task_lineage_is_not_reassigned_from_later_session(tools):
    store,sid,directory,config = tools
    execute(config);assert collector.collect(store,sid)
    receipt = next(iter(rows(store,'tool_receipts').values()))
    original = receipt['task_id']
    def reassign(state):state['sessions'][sid]['task_id']='later-private-task'
    store.transact_objects('FIXTURE_TASK_REASSIGN','fixture_task_reassign',[('sessions',sid)],reassign)
    assert collector.collect(store,sid)  # Binding mismatch quarantines, not historical reassignment.
    after = store.get('tool_receipts',receipt['id'])
    assert after==receipt and after['task_id']==original
    assert store.get('tool_sources',receipt['source_id'])['status']=='QUARANTINED'


def test_old_collected_receipt_without_task_lineage_stays_unknown(tools):
    store,sid,directory,config = tools
    execute(config);assert collector.collect(store,sid)
    receipt = next(iter(rows(store,'tool_receipts').values()))
    def old_schema(state):state['tool_receipts'][receipt['id']].pop('task_id')
    store.transact_objects('FIXTURE_OLD_TOOL_RECEIPT','fixture_old_tool_receipt',
                           [('tool_receipts',receipt['id'])],old_schema)
    version = store.version()
    assert not collector.collect(store,sid) and store.version()==version
    restarted = Store(store.root)
    assert 'task_id' not in restarted.get('tool_receipts',receipt['id'])
    assert restarted.audit()==restarted.replay()


@pytest.mark.parametrize('damage',['memory','permissions','cwd','argv','checkpoint','witness'])
def test_unbound_command_metadata_never_verifies(tools,damage):
    store,sid,directory,config = tools
    if damage=='memory':config['memory_bytes']+=1
    if damage=='permissions':config['read_extra']=[] if config['read_extra'] else [config['scratch']]
    if damage=='witness':config['tool_launch_directory']=None
    result = execute(config)
    if damage in ('cwd','argv','checkpoint'):
        path = Path(result['checkpoint']);result[damage]='unbound'
        (path/'result.json').write_text(json.dumps(result))
        intent = json.loads((path/'intent.json').read_text())
        (path/'return-observation.json').write_text(json.dumps(isolation.tool_return_observation(intent,result)))
    assert collector.collect(store,sid)
    value = next(iter(rows(store,'tool_receipts').values()))
    assert value['verification']=='UNVERIFIED' and value['validation_digest'] is None


@pytest.mark.parametrize('name',['intent.json','result.json','return-observation.json'])
def test_private_artifact_symlink_is_quarantined(tools,name):
    store,sid,directory,config = tools;result = execute(config)
    path = Path(result['checkpoint'])/name
    other = directory/'private';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    assert collector.collect(store,sid)
    source = next(iter(rows(store,'tool_sources').values()))
    assert source['status']=='QUARANTINED' and source['cursor'] is None
    assert not rows(store,'tool_receipts')


def test_ledger_is_excluded_from_hot_view_but_survives_legacy_transaction_and_replay(tools,monkeypatch):
    store,sid,directory,config = tools;execute(config);collector.collect(store,sid)
    from rlflow.store import ObjectMap
    original = ObjectMap.__init__
    def init(self,store,db,section):
        assert not section.startswith('tool_')
        original(self,store,db,section)
    monkeypatch.setattr(ObjectMap,'__init__',init)
    before = rows(store,'tool_receipts')
    assert 'tool_receipts' not in store.view()
    store.transact('FIXTURE_FLAG','fixture_flag',lambda state:state.update(paused=True))
    assert rows(store,'tool_receipts')==before
    assert store.audit()==store.replay()
    store.recover();assert rows(store,'tool_receipts')==before


def test_outbox_failure_rolls_back_cursor_receipt_and_does_not_quarantine_source(tools,monkeypatch):
    store,sid,directory,config = tools;execute(config)
    from rlflow import public_logs
    original = public_logs.commit
    before = store.replay();reader = ObservationReader(store.root);cursor = reader.snapshot()['cursor']
    def fail(*a,**k):raise OSError('injected persistence failure')
    monkeypatch.setattr(public_logs,'commit',fail)
    with pytest.raises(OSError,match='persistence failure'):collector.collect(store,sid)
    assert store.replay()==before and reader.snapshot()['cursor']==cursor
    monkeypatch.setattr(public_logs,'commit',original)
    assert collector.collect(store,sid)
    assert len(rows(store,'tool_receipts'))==1
    assert len(reader.events(cursor))==1
    version = store.version();assert not collector.collect(store,sid);assert store.version()==version


def test_concurrent_collection_commits_same_receipt_once(tools):
    store,sid,directory,config = tools;execute(config);version = store.version()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:collector.collect(store,sid),range(2)))
    assert sum(results)==1 and store.version()==version+1 and len(rows(store,'tool_receipts'))==1


@pytest.mark.parametrize('damage',[{'exit_code':True},{'timed_out':1},{'wall_seconds':-1},
                                 {'infrastructure_error':'PRIVATE_REASON'},{'wall_seconds':float('nan')}])
def test_invalid_return_semantics_quarantines_only_observation_not_core(tools,damage):
    store,sid,directory,config = tools;result = execute(config)
    path = Path(result['checkpoint']);result.update(damage);(path/'result.json').write_text(json.dumps(result))
    assert collector.collect(store,sid)
    source = next(iter(rows(store,'tool_sources').values()))
    assert source['status']=='QUARANTINED' and not rows(store,'tool_receipts')
    store.transact('FIXTURE_AFTER_BAD_TOOL','after_bad_tool',lambda state:state.update(paused=True))
    assert store.view()['paused'] is True and not collector.collect(store,sid)


def test_pending_rotation_does_not_starve_later_return_or_reuse_old_round_key(tools,monkeypatch):
    store,sid,directory,config = tools;original = isolation.cpu_exec
    def crash(*a,**k):raise OSError('injected unknown')
    monkeypatch.setattr(isolation,'cpu_exec',crash)
    for number in range(6):
        with pytest.raises(OSError):execute(config,'pending_'+str(number))
    for _ in range(3):assert collector.collect(store,sid,limit=2)
    receipts = rows(store,'tool_receipts');assert len(receipts)==6 and all(r['status']=='PENDING' for r in receipts.values())
    checked = [];actual_return = collector._return
    def returning(*args):
        checked.append(args[-2]['command_digest']);return actual_return(*args)
    monkeypatch.setattr(collector,'_return',returning)
    for _ in range(9):collector.collect(store,sid,limit=2)
    assert set(checked)=={r['registration']['command_digest'] for r in receipts.values()}
    assert next(iter(rows(store,'tool_sources').values()))['revision']>=10
    chosen = receipts[max(receipts)];path = directory/'commands'/chosen['registration']['command_digest']
    result = original('printf PRIVATE_TOOL_OUTPUT',config['candidate'],config['scratch'],config['role'],timeout=5,
                      read_extra=config['read_extra'],write_roots=config['write_roots'],execute_extra=config['execute_extra'],
                      memory_bytes=config['memory_bytes'],command_seconds=config['command_seconds'],artifact_dir=path)
    result['checkpoint']=str(path);(path/'result.json').write_text(json.dumps(result))
    for _ in range(4):collector.collect(store,sid,limit=2)
    assert rows(store,'tool_receipts')[chosen['id']]['status']=='COLLECTED'


def test_terminal_history_and_later_revocation_do_not_invalidate_bound_return(tools):
    store,sid,directory,config = tools;execute(config)
    def terminal(state):
        state['sessions'][sid].update(status='ACCEPTED')
        state['stages'][state['sessions'][sid]['stage_id']].update(status='REVOKED')
    store.transact('FIXTURE_TERMINAL','fixture_terminal',terminal)
    assert collector.collect(store,sid)
    assert next(iter(rows(store,'tool_receipts').values()))['verification']=='VERIFIED'
    assert next(iter(rows(store,'tool_sources').values()))['status']=='DRAINED'


def test_global_scan_rounds_do_not_starve_sources_after_cursor_wrap(tools,monkeypatch):
    store,sid,directory,config = tools;values = {}
    for number in range(6):
        name = 'fixture_session_'+str(number);context = dict(config['tool_context'],session=name)
        identity = collector.source_id(name,context['generation'])
        values[identity] = collector._source(identity,context)
    def attach(state):state['tool_sources']=values
    store.transact_objects('FIXTURE_TOOL_SOURCES','fixture_tool_sources',[('tool_sources',key) for key in values],attach)
    visited = []
    monkeypatch.setattr(collector,'collect',lambda store,sid:visited.append(sid))
    for _ in range(9):assert collector.scan(store,limit=2)==2
    assert len(visited)==18 and all(visited.count('fixture_session_'+str(n))==3 for n in range(6))
    assert store.get('tool_scan','global')['round']==9


def test_cli_storage_audit_compares_complete_ledger(tools):
    import subprocess,sys
    store,sid,directory,config = tools;execute(config);collector.collect(store,sid)
    process = subprocess.run([sys.executable,'-m','rlflow.cli','--state-dir',str(store.root),'storage-audit'],capture_output=True,text=True,timeout=10)
    assert process.returncode==0 and json.loads(process.stdout)['projection_matches'] is True


def test_unicode_producer_bytes_are_supported_without_changing_cpu_permissions(tools,monkeypatch):
    store,sid,directory,config = tools
    command = '#'+('😀'*90000)
    def returned(command,candidate,scratch,role,**kwargs):
        return {'infrastructure_error':None,'command':command,'argv':['/bin/bash','--noprofile','--norc','-c',command],
                'cwd':scratch,'exit_code':0,'timed_out':False,'wall_seconds':0.1,'stdout':'😀'*100000,'stderr':''}
    monkeypatch.setattr(isolation,'cpu_exec',returned)  # Serialization fixture, not actual execution proof.
    result = isolation.persistent_cpu_exec(config,{'command_id':'unicode','command':command,'timeout':5})
    path = Path(result['checkpoint'])
    assert (path/'intent.json').stat().st_size>512*1024 and (path/'result.json').stat().st_size>2*1024*1024
    assert collector.collect(store,sid)
    receipt = next(iter(rows(store,'tool_receipts').values()))
    assert receipt['verification']=='VERIFIED' and receipt['fact']['result_sha256']==sha(result)


def test_over_capacity_fact_is_unsupported_not_claimed_source_corruption(tools):
    store,sid,directory,config = tools;result = execute(config)
    with (Path(result['checkpoint'])/'result.json').open('wb') as stream:
        stream.truncate(collector.RESULT_LIMIT+1)
    assert collector.collect(store,sid)
    source = next(iter(rows(store,'tool_sources').values()))
    assert source['status']=='UNSUPPORTED' and source['reason']=='SOURCE_CAPACITY' and source['cursor'] is None


def test_request_derived_unicode_permissions_byte_bound(tmp_path):
    from rlflow.store import canonical
    request = {'write_roots':['😀'*1000]*1000}
    assert len(canonical(request))<4*1024*1024
    intent = {'permissions':request,'command':'😀'*90000}
    raw = json.dumps(intent,sort_keys=True).encode()
    assert 6*1024*1024<len(raw)<collector.INTENT_LIMIT
    (tmp_path/'intent.json').write_bytes(raw)
    directory = os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:assert collector.read_json(directory,'intent.json',collector.INTENT_LIMIT)==intent
    finally:os.close(directory)
