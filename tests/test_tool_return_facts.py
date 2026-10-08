"""Model-free trusted CPU return provenance; not public tool authorization."""
import json
from pathlib import Path
import pytest
from rlflow import isolation
from rlflow.store import sha
from test_command_checkpoints import config

CONTEXT = {'schema_version':'1.0','session':'session_one','generation':'generation_one',
           'request_sha256':sha({'prompt':'PRIVATE_PROMPT'}),'candidate_sha256':sha({'head':'candidate'})}


def bound_config(tmp_path):
    value = config(tmp_path)
    value['tool_context'] = dict(CONTEXT)
    return value


def read_facts(result):
    directory = Path(result['checkpoint'])
    return (json.loads((directory/'intent.json').read_text()),
            json.loads((directory/'return-observation.json').read_text()))


def test_actual_cpu_return_is_bound_private_metadata_and_replay_is_once(tmp_path):
    value = bound_config(tmp_path)
    target = tmp_path/'repo/count'
    args = {'command_id':'private_command_id','command':f'echo PRIVATE_OUTPUT; echo x >> {target}','timeout':5}
    result = isolation.persistent_cpu_exec(value,args)
    intent, fact = read_facts(result)
    assert result['exit_code'] == 0 and result['stdout'].startswith('PRIVATE_OUTPUT')
    assert fact == isolation.tool_return_observation(intent,result)
    assert fact['intent_sha256'] == sha(intent) and fact['result_sha256'] == sha(result)
    assert fact['context'] == value['tool_context'] and fact['state'] == 'RETURNED'
    assert intent['scratch'] == value['scratch'] and intent['memory_bytes'] == 2*1024**3
    encoded = json.dumps(fact)
    for private in ('PRIVATE_OUTPUT','PRIVATE_PROMPT','private_command_id',str(tmp_path),args['command']):
        assert private not in encoded
    assert set(fact) == {'schema_version','kind','tool','context','intent_sha256','result_sha256','state',
                         'exit_code','timed_out','wall_seconds','infrastructure_error'}
    assert isolation.persistent_cpu_exec(value,args) == result and target.read_text() == 'x\n'
    assert read_facts(result)[1] == fact


@pytest.mark.parametrize('field,new', [('generation','generation_two'),('session','session_two'),
                                     ('request_sha256','1'*64),('candidate_sha256','2'*64)])
def test_reused_command_id_cannot_cross_context(tmp_path,field,new):
    value = bound_config(tmp_path)
    args = {'command_id':'once','command':'true','timeout':5}
    isolation.persistent_cpu_exec(value,args)
    value['tool_context'][field] = new
    with pytest.raises(isolation.IsolationError,match='content mismatch'):
        isolation.persistent_cpu_exec(value,args)


@pytest.mark.parametrize('field,new', [('scratch','elsewhere'),('memory_bytes',1024),('command_seconds',100)])
def test_reused_bound_command_id_cannot_change_execution_permissions(tmp_path,field,new):
    value = bound_config(tmp_path)
    args = {'command_id':'once','command':'true','timeout':5}
    isolation.persistent_cpu_exec(value,args)
    value[field] = new
    with pytest.raises(isolation.IsolationError,match='content mismatch'):
        isolation.persistent_cpu_exec(value,args)


def test_result_committed_before_fact_crash_is_recovered_without_execution(tmp_path,monkeypatch):
    value = bound_config(tmp_path)
    args = {'command_id':'once','command':'true','timeout':5}
    result = isolation.persistent_cpu_exec(value,args)
    directory = Path(result['checkpoint'])
    original = (directory/'return-observation.json').read_bytes()
    (directory/'return-observation.json').unlink()  # Exact owned fixture: simulate crash gap.
    monkeypatch.setattr(isolation,'cpu_exec',lambda *a,**k: pytest.fail('must not execute twice'))
    assert isolation.persistent_cpu_exec(value,args) == result
    assert (directory/'return-observation.json').read_bytes() == original


def test_crash_after_intent_does_not_claim_tool_started_or_returned(tmp_path,monkeypatch):
    value = bound_config(tmp_path)
    def crash(*a,**kw):raise OSError('injected crash')
    monkeypatch.setattr(isolation,'cpu_exec',crash)
    args = {'command_id':'unknown','command':'true'}
    with pytest.raises(OSError):isolation.persistent_cpu_exec(value,args)
    directories = list((tmp_path/'control/commands').iterdir())
    assert len(directories) == 1 and (directories[0]/'intent.json').exists()
    assert not (directories[0]/'return-observation.json').exists()
    with pytest.raises(isolation.IsolationError,match='outcome unknown'):
        isolation.persistent_cpu_exec(value,args)


def test_return_fact_tamper_fails_without_reexecution(tmp_path,monkeypatch):
    value = bound_config(tmp_path)
    args = {'command_id':'once','command':'true','timeout':5}
    result = isolation.persistent_cpu_exec(value,args)
    directory = Path(result['checkpoint'])
    fact = read_facts(result)[1];fact['state'] = 'RUNNING'
    (directory/'return-observation.json').write_text(json.dumps(fact))
    monkeypatch.setattr(isolation,'cpu_exec',lambda *a,**k: pytest.fail('must not execute twice'))
    with pytest.raises(isolation.IsolationError,match='observation mismatch'):
        isolation.persistent_cpu_exec(value,args)


@pytest.mark.parametrize('change',[{'generation':None},{'generation':['generation_one']},
                                 {'request_sha256':'bad'},{'released':True},{'schema_version':'2.0'}])
def test_invalid_context_rejected_before_creating_command_storage(tmp_path,change):
    value = bound_config(tmp_path);value['tool_context'].update(change)
    with pytest.raises(isolation.IsolationError,match='tool context'):
        isolation.persistent_cpu_exec(value,{'command':'true'})
    assert not (tmp_path/'control/commands').exists()


def test_legacy_command_does_not_gain_unbound_tool_facts(tmp_path):
    result = isolation.persistent_cpu_exec(config(tmp_path),{'command':'true','timeout':5})
    assert not (Path(result['checkpoint'])/'return-observation.json').exists()


@pytest.mark.parametrize('change,expected',[({'exit_code':1},'RETURNED'),({'timed_out':True},'TIMED_OUT'),
                                         ({'infrastructure_error':'CPU_SANDBOX_SETUP_FAILED'},'SETUP_FAILED')])
def test_fixed_states_do_not_infer_running_or_success(change,expected):
    intent = {'tool_context':CONTEXT}
    result = {'exit_code':0,'timed_out':False,'wall_seconds':0.1,'infrastructure_error':None,**change}
    assert isolation.tool_return_observation(intent,result)['state'] == expected


@pytest.mark.parametrize('change',[{'exit_code':True},{'timed_out':1},{'wall_seconds':float('nan')},
                                 {'wall_seconds':-1},{'infrastructure_error':'PRIVATE_REASON'}])
def test_invalid_result_metadata_is_not_recorded(change):
    with pytest.raises(isolation.IsolationError,match='return metadata'):
        isolation.tool_return_observation({'tool_context':CONTEXT},{'exit_code':0,'timed_out':False,'wall_seconds':0.1,**change})
