import json
import pytest
from rlflow.failures import infrastructure_failure


@pytest.mark.parametrize('event', [
    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'MCP tool call requires approval, but approval policy is never'}},
    {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'other', 'tool': 'cpu_exec', 'status': 'failed', 'error': {'message': 'denied'}}},
    {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'rlflow_cpu', 'tool': 'cpu_exec', 'status': 'completed', 'result': {'exit_code': 1}}},
    {'type': 'item.started', 'item': {'type': 'mcp_tool_call', 'server': 'rlflow_cpu', 'tool': 'cpu_exec', 'status': 'in_progress'}},
    None,
])
def test_role_prose_and_command_failures_are_not_infrastructure(tmp_path, event):
    (tmp_path / 'events.jsonl').write_text(json.dumps(event) + '\n')
    assert infrastructure_failure(tmp_path) is None


def test_bad_transport_evidence_fails_closed(tmp_path):
    assert infrastructure_failure(tmp_path) is None
    (tmp_path / 'events.jsonl').write_text('{broken')
    assert infrastructure_failure(tmp_path) == 'TRANSPORT_EVIDENCE_INVALID'


def test_cpu_transport_error(tmp_path):
    event = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'rlflow_cpu',
             'tool': 'cpu_exec', 'status': 'failed', 'error': {'message': 'connection closed'}}}
    (tmp_path / 'events.jsonl').write_text(json.dumps(event))
    assert infrastructure_failure(tmp_path) == 'CPU_EXEC_TRANSPORT_ERROR'


@pytest.mark.parametrize('limit', [1, 120, 600, 1800])
def test_invalid_cpu_tool_timeout_is_a_role_request_error(tmp_path, limit):
    event = {'type': 'item.completed', 'item': {'type': 'mcp_tool_call', 'server': 'rlflow_cpu',
             'tool': 'cpu_exec', 'status': 'failed', 'error': {'message':
             f'tool call error: Mcp error: -32000: Tool timeout must be within (0, {limit}] seconds'}}}
    (tmp_path / 'events.jsonl').write_text(json.dumps(event))
    assert infrastructure_failure(tmp_path) is None


def test_trusted_cpu_setup_failure_is_infrastructure_even_when_role_action_is_invalid(tmp_path):
    import json
    from rlflow.failures import infrastructure_failure
    (tmp_path/'result.json.commands.jsonl').write_text(json.dumps({'infrastructure_error':'CPU_SANDBOX_SETUP_FAILED','exit_code':1})+'\n')
    assert infrastructure_failure(tmp_path)=='CPU_SANDBOX_SETUP_FAILED'


@pytest.mark.parametrize('message, expected', [
    ('Mcp error: -32000: Command ID content mismatch', None),
    ('Mcp error: -32000: Command outcome unknown; inspect checkpoint, do not re-execute', 'CPU_EXEC_TRANSPORT_ERROR'),
    ('connection closed: Tool timeout must be within (0, 600] seconds', 'CPU_EXEC_TRANSPORT_ERROR'),
])
def test_checkpoint_argument_error_does_not_mask_unknown_execution(tmp_path, message, expected):
    event = {'type':'item.completed','item':{'type':'mcp_tool_call','server':'rlflow_cpu',
             'tool':'cpu_exec','status':'failed','error':{'message':message}}}
    (tmp_path/'events.jsonl').write_text(json.dumps(event))
    assert infrastructure_failure(tmp_path) == expected
