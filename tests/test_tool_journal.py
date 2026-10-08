"""No model: durable discovery before execution and bounded anchored reads."""
import json
import os
from pathlib import Path
import pytest
from concurrent.futures import ThreadPoolExecutor
from rlflow import isolation, tool_journal
from rlflow.store import sha
from test_tool_return_facts import bound_config


def read(config,cursor=None,limit=32):
    directory = os.open(Path(config['audit']).parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:return tool_journal.read_page(directory,config['tool_context'],cursor,limit=limit)
    finally:os.close(directory)


def register(config,number=0):
    intent = {'tool_context':config['tool_context'],'private_command':'NEVER_COPY','number':number}
    return tool_journal.register(config,intent,sha({'command':number}))


def journal(config):
    return Path(config['audit']).parent/tool_journal.NAME


def test_registration_is_durable_before_any_cpu_invocation(tmp_path,monkeypatch):
    config = bound_config(tmp_path);calls = []
    def execute(*args,**kwargs):
        page = read(config)
        assert len(page['items'])==1 and page['items'][0]['launch_witness'] is None
        calls.append(1)
        return {'exit_code':0,'timed_out':False,'wall_seconds':0.1,'infrastructure_error':None}
    monkeypatch.setattr(isolation,'cpu_exec',execute)
    result = isolation.persistent_cpu_exec(config,{'command_id':'once','command':'SECRET'})
    assert isolation.persistent_cpu_exec(config,{'command_id':'once','command':'SECRET'})==result
    assert calls==[1] and len(read(config)['items'])==1
    row = read(config)['items'][0]
    intent = json.loads((Path(result['checkpoint'])/'intent.json').read_text())
    assert row['command_digest']==Path(result['checkpoint']).name and row['intent_sha256']==sha(intent)
    assert 'SECRET' not in journal(config).read_text() and str(tmp_path) not in journal(config).read_text()


def test_register_failure_never_invokes_cpu_and_retains_unknown_intent(tmp_path,monkeypatch):
    config = bound_config(tmp_path)
    def fail(*args,**kwargs):raise OSError('injected fsync failure')
    monkeypatch.setattr(tool_journal,'register',fail)
    monkeypatch.setattr(isolation,'cpu_exec',lambda *a,**k:pytest.fail('side effect before registration'))
    with pytest.raises(OSError):isolation.persistent_cpu_exec(config,{'command_id':'unknown','command':'true'})
    with pytest.raises(isolation.IsolationError,match='outcome unknown'):
        isolation.persistent_cpu_exec(config,{'command_id':'unknown','command':'true'})


def test_command_path_parent_durability_precedes_register_and_cpu(tmp_path,monkeypatch):
    config = bound_config(tmp_path);synced = [];original = os.fsync;original_register = tool_journal.register
    def fsync(fd):
        synced.append(os.readlink(f'/proc/self/fd/{fd}'))
        return original(fd)
    def registering(*args):
        parent = Path(config['audit']).parent
        assert str(parent/'commands') in synced and str(parent) in synced
        return original_register(*args)
    monkeypatch.setattr(os,'fsync',fsync)
    monkeypatch.setattr(tool_journal,'register',registering)
    def execute(*a,**kw):
        assert journal(config).read_bytes().endswith(b'\n')
        return {'exit_code':0,'timed_out':False,'wall_seconds':0.1,'infrastructure_error':None}
    monkeypatch.setattr(isolation,'cpu_exec',execute)
    isolation.persistent_cpu_exec(config,{'command':'true'})


def test_parent_fsync_failure_prevents_registration_and_execution(tmp_path,monkeypatch):
    config = bound_config(tmp_path);original = os.fsync
    def fsync(fd):
        if os.readlink(f'/proc/self/fd/{fd}').endswith('/commands'):raise OSError('parent durability failure')
        return original(fd)
    monkeypatch.setattr(os,'fsync',fsync)
    monkeypatch.setattr(isolation,'cpu_exec',lambda *a,**k:pytest.fail('side effect before parent durability'))
    with pytest.raises(OSError,match='durability failure'):
        isolation.persistent_cpu_exec(config,{'command':'true'})
    assert not journal(config).exists()


def test_crash_after_register_still_discovers_known_path_without_result(tmp_path,monkeypatch):
    config = bound_config(tmp_path)
    def fail(*args,**kwargs):raise OSError('injected command crash')
    monkeypatch.setattr(isolation,'cpu_exec',fail)
    with pytest.raises(OSError):isolation.persistent_cpu_exec(config,{'command':'true'})
    row = read(config)['items'][0]
    path = Path(config['audit']).parent/'commands'/row['command_digest']
    assert (path/'intent.json').exists() and not (path/'result.json').exists()
    assert not (path/'return-observation.json').exists()


def test_result_before_fact_crash_is_discoverable_without_return_notification(tmp_path,monkeypatch):
    config = bound_config(tmp_path)
    result = isolation.persistent_cpu_exec(config,{'command':'true','timeout':5})
    path = Path(result['checkpoint']);(path/'return-observation.json').unlink()
    row = read(config)['items'][0]
    assert row['command_digest']==path.name and (path/'result.json').exists()
    fact = isolation.tool_return_observation(json.loads((path/'intent.json').read_text()),json.loads((path/'result.json').read_text()))
    assert fact['result_sha256']==sha(result) and fact['state']=='RETURNED'


def test_pages_are_bounded_chain_continuous_and_cursor_survives_append(tmp_path):
    config = bound_config(tmp_path)
    rows = [register(config,n) for n in range(70)]
    first = read(config,limit=32)
    assert first['items']==rows[:32] and first['has_more'] and not first['incomplete_tail']
    second = read(config,first['cursor'],limit=32)
    last = read(config,second['cursor'])
    assert second['items']==rows[32:64] and last['items']==rows[64:] and not last['has_more']
    register(config,70)
    extra = read(config,last['cursor'])
    assert [row['ordinal'] for row in extra['items']]==[71]
    assert read(config,extra['cursor'])['items']==[]
    assert 'NEVER_COPY' not in journal(config).read_text()


def test_concurrent_registration_serializes_one_hash_chain(tmp_path):
    config = bound_config(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda number:register(config,number),range(32)))
    actual = read(config)['items']
    assert sorted(row['ordinal'] for row in rows)==list(range(1,33))
    assert len({row['command_digest'] for row in actual})==32
    assert [row['ordinal'] for row in actual]==list(range(1,33))


def test_partial_tail_is_not_consumed_or_silently_repaired(tmp_path):
    config = bound_config(tmp_path);register(config)
    first = read(config)
    with journal(config).open('ab') as stream:stream.write(b'{"partial":')
    result = read(config,first['cursor'])
    assert result['cursor']==first['cursor'] and result['items']==[] and result['incomplete_tail'] and result['has_more']
    previous = journal(config).read_bytes()
    with pytest.raises(tool_journal.JournalError,match='Incomplete'):register(config,1)
    assert journal(config).read_bytes()==previous


@pytest.mark.parametrize('damage',['replace','truncate','checkpoint','ordinal','previous','extra','oversize'])
def test_source_damage_is_rejected_without_cursor_reset(tmp_path,damage):
    config = bound_config(tmp_path);register(config);first = read(config);register(config,1)
    path = journal(config)
    if damage=='replace':
        replacement = path.with_suffix('.replacement');replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
    elif damage=='truncate':path.write_bytes(b'')
    elif damage=='checkpoint':
        rows = path.read_text().splitlines();value = json.loads(rows[0]);value['command_digest']='1'*64
        value['record_sha256']=tool_journal.digest({k:v for k,v in value.items() if k!='record_sha256'})
        rows[0]=json.dumps(value,separators=(',',':'),sort_keys=True);path.write_text('\n'.join(rows)+'\n')
    elif damage=='oversize':
        first = read(config,first['cursor'])
        with path.open('ab') as stream:stream.write(b'x'*(tool_journal.RECORD_LIMIT+1))
    else:
        rows = path.read_text().splitlines();value = json.loads(rows[1])
        value.update({'ordinal':99} if damage=='ordinal' else {'previous_sha256':'1'*64} if damage=='previous' else {'secret':'NO'})
        value['record_sha256']=tool_journal.digest({k:v for k,v in value.items() if k!='record_sha256'})
        rows[1]=json.dumps(value,separators=(',',':'),sort_keys=True);path.write_text('\n'.join(rows)+'\n')
    with pytest.raises((tool_journal.JournalError,ValueError)):
        read(config,first['cursor'])


@pytest.mark.parametrize('storage',['symlink','fifo'])
def test_journal_does_not_follow_links_or_block_on_fifo(tmp_path,storage):
    config = bound_config(tmp_path);path = journal(config)
    if storage=='symlink':
        other = tmp_path/'other';other.write_text('private');path.symlink_to(other)
    else:os.mkfifo(path)
    with pytest.raises((OSError,tool_journal.JournalError)):read(config)
    with pytest.raises((OSError,tool_journal.JournalError)):register(config)


def launch(config,tmp_path):
    directory = tmp_path/'launch';directory.mkdir();context = config['tool_context']
    identity = {'pid':123,'pgid':123,'starttime':'123','boot_id':'identity-placeholder'}
    release = {'session':context['session'],'generation':context['generation'],'request_sha256':context['request_sha256'],
               'candidate_sha256':context['candidate_sha256']}
    model = {'session':context['session'],'generation':context['generation'],'identity':identity}
    binding = dict(model)
    ack = {'phase':'START_ACK','binding':binding,'binding_sha256':sha(binding),'time':1}
    for name,value in [('release',release),('model-release.json',model),('launch-start_ack.json',ack)]:
        (directory/name).write_text(json.dumps(value))
    config['tool_launch_directory']=str(directory)
    return directory,release,model,ack


def test_registration_captures_existing_launch_witness_not_later_release(tmp_path):
    config = bound_config(tmp_path);directory,release,model,ack = launch(config,tmp_path)
    (directory/'launch-start_ack.json').unlink()
    before = register(config)
    assert before['launch_witness'] is None
    (directory/'launch-start_ack.json').write_text(json.dumps(ack))
    after = register(config,1)
    assert after['launch_witness']=={'release_sha256':sha(release),'model_release_sha256':sha(model),'ack_sha256':sha(ack)}
    assert read(config)['items'][0]['launch_witness'] is None  # Never upgrade old evidence.


@pytest.mark.parametrize('field',['generation','request_sha256','candidate_sha256'])
def test_wrong_release_is_not_captured_as_bound_witness(tmp_path,field):
    config = bound_config(tmp_path);directory,release,model,ack = launch(config,tmp_path)
    release[field]='wrong';(directory/'release').write_text(json.dumps(release))
    assert register(config)['launch_witness'] is None


def test_context_change_and_invalid_page_limit_reject(tmp_path):
    config = bound_config(tmp_path);register(config)
    for limit in (0,65,True):
        with pytest.raises(tool_journal.JournalError):read(config,limit=limit)
    config['tool_context']['generation']='generation_two'
    with pytest.raises(tool_journal.JournalError):read(config)
    with pytest.raises(tool_journal.JournalError):register(config,1)
