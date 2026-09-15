"""Classify trusted transport events, never role prose, as infrastructure failures."""
import json
import re
from pathlib import Path


def _role_request_error(message):
    """Return true for deterministic tool-argument rejection by the role.

    These errors say nothing about transport health.  The role can correct the
    request in the same turn, so a later successful audited command remains
    usable evidence.
    """
    detail = message.rsplit('Mcp error: -32000: ', 1)[-1].strip()
    return (re.fullmatch(r'Tool timeout must be within \(0, [1-9][0-9]*\] seconds', detail) is not None
            or detail == 'Command ID content mismatch')


def infrastructure_failure(directory):
    audit=Path(directory)/'result.json.commands.jsonl'
    if audit.exists():
        try:
            for line in audit.read_text().splitlines():
                row=json.loads(line)
                if row.get('infrastructure_error')=='CPU_SANDBOX_SETUP_FAILED':return 'CPU_SANDBOX_SETUP_FAILED'
        except (OSError,ValueError,TypeError,AttributeError):return 'TRANSPORT_EVIDENCE_INVALID'
    path = Path(directory) / 'events.jsonl'
    if not path.exists():
        return None
    try:
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            item = event.get('item')
            if (event.get('type') == 'item.completed' and isinstance(item, dict)
                    and item.get('type') == 'mcp_tool_call'
                    and item.get('server') == 'rlflow_cpu' and item.get('tool') == 'cpu_exec'
                    and item.get('status') == 'failed'):
                error = item.get('error')
                message = error.get('message', '') if isinstance(error, dict) else ''
                if message == 'MCP tool call requires approval, but approval policy is never':
                    return 'CPU_EXEC_APPROVAL_REQUIRED'
                if _role_request_error(message):
                    continue
                if message:
                    return 'CPU_EXEC_TRANSPORT_ERROR'
            if event.get('type') == 'turn.failed':
                error = event.get('error')
                message = error.get('message', '') if isinstance(error, dict) else ''
                try:
                    detail = json.loads(message)
                except (ValueError, TypeError):
                    detail = {}
                inner = detail.get('error') if isinstance(detail, dict) else None
                if isinstance(inner, dict) and inner.get('code') == 'invalid_json_schema':
                    return 'OUTPUT_SCHEMA_REJECTED'
                return 'ROLE_TRANSPORT_ERROR'
    except (OSError, ValueError, UnicodeError):
        return 'TRANSPORT_EVIDENCE_INVALID'
    return None
