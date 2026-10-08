"""Real model-free CPU→core→public queries; fixture ACK is not vendor proof."""
import copy
import json
import pytest
from test_tool_collector import tools, startup, harness, execute, rows  # noqa: F401
from rlflow import tool_collector, public_logs, public_tools
from rlflow.hybrid_protocol import ProtocolError, validate
from rlflow.observation import ObservationReader, enable, public_id, rotate_epoch
from rlflow.store import Store, sha


def returned(tools):
    store,sid,directory,config = tools
    execute(config);assert tool_collector.collect(store,sid)
    return next(iter(rows(store,'tool_receipts').values()))


def test_actual_bound_return_is_public_once_without_private_content_or_authority(tools):
    store,sid,directory,config = tools
    reader = ObservationReader(store.root)
    before = store.replay();cursor = reader.head()['cursor']
    receipt = returned(tools)
    result = reader.page(kind='tool_return',include_cursor=True)
    assert result['total']==1 and len(result['items'])==1
    row = result['items'][0];validate('ToolReturn',row)
    assert row['state']=='RETURNED' and row['source_status']=='COLLECTED' and row['exit_code']==0
    assert row['execution_id']==public_id(sid) and row['task_id']==public_id(receipt['task_id'])
    assert row['observability']=='PARTIAL' and row['provenance']=='BOUND_RETURN'
    events = reader.events(cursor)
    tools_event = next(e for e in events if any(r['kind']=='tool_return' for r in e['payload']['upsert']))
    assert row['observed_at']==tools_event['recorded_at']
    assert all(r['kind']=='tool_return' for r in tools_event['payload']['upsert'])
    for section in ('stages','tasks','sessions','approvals','authorizations','usage'):
        assert store.replay().get(section)==before.get(section)
    for private in (sid,str(directory),'PRIVATE_TOOL_OUTPUT','intent_sha256','result_sha256','launch_witness','command_digest'):
        assert private not in json.dumps(events+result['items'])
    assert reader.snapshot()['projection']['tool_observations']['policy']=='LIVE_ONLY'
    version = store.version();assert not tool_collector.collect(store,sid) and store.version()==version
    restarted = Store(store.root);assert restarted.recover()==restarted.audit()
    assert ObservationReader(store.root).page(kind='tool_return')==reader.page(kind='tool_return')


def test_tool_template_lineage_filters_and_old_logs_stay_immutable(tools):
    store,sid,directory,config = tools;reader = ObservationReader(store.root)
    old = public_logs.page(reader)['items'][0];old_body = public_logs.body(reader,old['id'])
    receipt = returned(tools)
    assert public_logs.body(reader,old['id'])==old_body
    selected = public_logs.page(reader,kind='execution',object_id=public_id(sid))
    tool = next(r for r in selected['items'] if r['source']=='TOOL_METADATA')
    body = public_logs.body(reader,tool['id'])
    assert body['tool_metadata']=='BOUND_RETURN' and body['raw_logs']=='PRIVATE_ONLY'
    assert 'not model activity or task success' in body['text'] and 'bound return RETURNED' in body['text']
    assert {r['kind'] for r in body['refs']}=={'tool_return','execution','task'}
    tasks = public_logs.page(reader,kind='task',object_id=public_id(receipt['task_id']))
    assert tool in tasks['items']
    assert public_logs.page(reader,kind='task',object_id=public_id('other_task'))['items']==[]


@pytest.mark.parametrize('damage',['null_fact','null_validation','pending','unverified','witness','context','intent',
                                   'semantic','source','record','key','state','boolean_exit','nan','raw','task'])
def test_promotion_does_not_trust_verification_string_alone(tools,damage):
    receipt = copy.deepcopy(returned(tools));key = receipt['id']
    if damage=='null_fact':receipt['fact']=None
    elif damage=='null_validation':receipt['validation_digest']=None
    elif damage=='pending':receipt['status']='PENDING'
    elif damage=='unverified':receipt['verification']='UNVERIFIED'
    elif damage=='witness':receipt['registration']['launch_witness']=None
    elif damage=='context':receipt['fact']['context']['generation']='another_generation'
    elif damage=='intent':receipt['fact']['intent_sha256']='0'*64
    elif damage=='semantic':receipt['semantic_digest']='0'*64
    elif damage=='source':receipt['source_id']='0'*64
    elif damage=='record':receipt['registration']['record_sha256']='0'*64
    elif damage=='key':key='0'*64+':'+receipt['registration']['command_digest']
    elif damage=='state':
        receipt['fact']['state']='TIMED_OUT'
        receipt['validation_digest']=sha({'fact':receipt['fact'],'witness':receipt['registration']['launch_witness'],'context':receipt['registration']['context'],'task_id':receipt['task_id']})
    elif damage=='boolean_exit':receipt['fact']['exit_code']=True
    elif damage=='nan':receipt['fact']['wall_seconds']=float('nan')
    elif damage=='raw':receipt['fact']['stdout']='PRIVATE'
    elif damage=='task':receipt['task_id']='a_different_private_task'
    assert public_tools.promote(key,receipt,'2026-10-08T00:00:00Z') is None


def test_optional_missing_frozen_task_does_not_query_current_session(tools):
    receipt = copy.deepcopy(returned(tools));receipt.pop('task_id');receipt.pop('validation_version')
    receipt['validation_digest']=sha({'fact':receipt['fact'],'witness':receipt['registration']['launch_witness'],'context':receipt['registration']['context']})
    row = public_tools.promote(receipt['id'],receipt,'2026-10-08T00:00:00Z')
    assert row['task_id'] is None and row['execution_id']==public_id(receipt['fact']['context']['session'])
    receipt['task_id']='unbound_old_optional_task'
    assert public_tools.promote(receipt['id'],receipt,'2026-10-08T00:00:00Z')['task_id'] is None


def test_public_tool_contract_and_producer_agree_on_states_utc_and_closed_fields(tools):
    receipt = returned(tools)
    value = public_tools.promote(receipt['id'],receipt,'2026-10-08T00:00:00Z')
    for mutation in ({'state':'TIMED_OUT'},{'state':'SUCCEEDED'},{'timed_out':True},
                     {'infrastructure_error':'CPU_SANDBOX_SETUP_FAILED'},{'exit_code':True},
                     {'wall_seconds':float('inf')},{'observed_at':'2026-10-08T00:00:00+00:00'},
                     {'stdout':'PRIVATE'},{'task_id':'private_task'}):
        with pytest.raises(ProtocolError):validate('PublicObject',{**value,**mutation})
    validate('ToolReturn',{**value,'state':'TIMED_OUT','timed_out':True})
    validate('ToolReturn',{**value,'state':'SETUP_FAILED','infrastructure_error':'CPU_SANDBOX_SETUP_FAILED'})


def test_live_only_upgrade_does_not_backfill_preexisting_collected_receipts(tools):
    store,sid,directory,config = tools;reader = ObservationReader(store.root)
    with store.connect() as db:db.execute('DROP TABLE public_tool_meta');db.commit()
    assert reader.snapshot()['projection']['tool_observations'] is None
    first = returned(tools)
    assert reader.page(kind='tool_return')['total']==0
    prior = reader.head()['cursor'];version = store.version()
    enable(store,'project_startup',data_mode='fixture')
    coverage = reader.snapshot()['projection']['tool_observations']
    assert coverage['coverage_after_source_version']==version and coverage['coverage_after_seq']==int(prior.rsplit(':',1)[1])
    assert reader.page(kind='tool_return')['total']==0 and not tool_collector.collect(store,sid)
    execute(config,'after_upgrade');assert tool_collector.collect(store,sid)
    result = reader.page(kind='tool_return');assert result['total']==1
    assert result['items'][0]['id']!=public_id(first['id'])
    assert all(row['kind']!='tool_return' for row in reader.events(prior)[0]['payload']['upsert'])


def test_tool_log_failure_rolls_back_cursor_receipt_projection_counter_and_outbox(tools,monkeypatch):
    store,sid,directory,config = tools;reader = ObservationReader(store.root)
    execute(config);before = store.replay();snapshot = reader.snapshot();logs = public_logs.page(reader)
    original = public_logs.build_tools
    def fail(event):raise ProtocolError('injected tool template failure')
    monkeypatch.setattr(public_logs,'build_tools',fail)
    with pytest.raises(ProtocolError):tool_collector.collect(store,sid)
    after = reader.snapshot()
    assert store.replay()==before and after['projection']==snapshot['projection'] and after['cursor']==snapshot['cursor'] and public_logs.page(reader)==logs
    monkeypatch.setattr(public_logs,'build_tools',original)
    assert tool_collector.collect(store,sid) and reader.page(kind='tool_return')['total']==1


def test_coverage_never_migrates_on_read_and_corruption_requires_recovery(tools):
    store,sid,directory,config = tools;reader = ObservationReader(store.root)
    with store.connect() as db:db.execute('DELETE FROM public_tool_meta');db.commit()
    with pytest.raises(ProtocolError) as error:reader.snapshot()
    assert error.value.code=='RESYNC_REQUIRED'
    with pytest.raises(ProtocolError) as error:enable(store,'project_startup',data_mode='fixture')
    assert error.value.code=='RESYNC_REQUIRED'
    with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM public_tool_meta').fetchone()[0]==0


def test_missing_tool_scope_with_historical_projection_cannot_be_silently_reenabled(tools):
    store,sid,directory,config = tools;returned(tools)
    reader = ObservationReader(store.root);before = reader.page(kind='tool_return')
    with store.connect() as db:db.execute('DROP TABLE public_tool_meta');db.commit()
    assert reader.snapshot()['projection']['tool_observations'] is None
    with pytest.raises(ProtocolError) as error:enable(store,'project_startup',data_mode='fixture')
    assert error.value.code=='RESYNC_REQUIRED' and reader.page(kind='tool_return')==before
    with store.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='public_tool_meta'").fetchone() is None


def test_epoch_rotation_excludes_old_tool_logs_and_retains_truthful_partial_coverage(tools):
    store,sid,directory,config = tools;receipt = returned(tools);reader = ObservationReader(store.root)
    coverage = reader.snapshot()['projection']['tool_observations']
    old = public_logs.page(reader)['items'][0]['id'];rotate_epoch(store)
    with pytest.raises(ProtocolError):public_logs.body(reader,old)
    snapshot = reader.snapshot()
    assert snapshot['projection']['tool_observations']==coverage
    assert reader.page(kind='tool_return')['total']==1  # Historical projection, not post-restore execution.
    assert snapshot['projection']['tool_observations']['status']=='PARTIAL'
