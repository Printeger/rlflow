"""Model reservations and append-only corrections, separate from process uptime."""
import hashlib
import json
from pathlib import Path
from .store import Conflict, sha


def observe(directory, launched):
    """A CLI process/turn.started is not evidence of model use.

    Positive usage or a completed generated item is positive evidence. Missing
    evidence after launch remains unknown, including network/transport failures.
    """
    path = Path(directory) / 'events.jsonl'
    raw = path.read_bytes() if path.exists() else b''
    used = False
    for line in raw.splitlines():
        try: event = json.loads(line)
        except ValueError: continue
        if not isinstance(event, dict): continue
        usage = event.get('usage') or {}
        if isinstance(usage, dict) and any(type(v) is int and v > 0 for k, v in usage.items() if k in ('input_tokens', 'output_tokens', 'total_tokens')):
            used = True
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and isinstance(item, dict) and item.get('type') in ('agent_message', 'reasoning', 'command_execution', 'mcp_tool_call'):
            used = True
    return {'state': 'USED' if used else 'UNKNOWN' if launched else 'NOT_STARTED',
            'source': 'worker-lifecycle+cli-jsonl/1', 'events_sha256': hashlib.sha256(raw).hexdigest()}


def reserve(stage, session):
    stage['reserved_calls'] = stage.get('reserved_calls', 0) + 1
    stage['reserved_seconds'] += session['limit']
    tier = session['compute']['tier']
    counts = stage['compute'].setdefault('reserved_calls', {'sol': 0, 'astra': 0})
    counts[tier] += 1
    stage['compute']['reserved_seconds'][tier] += session['limit']
    session['accounting_version'] = 2
    session['model_accounting'] = 'RESERVED'


def settle(stage, session, receipt):
    if session.get('accounting_version') != 2:
        # Compatibility: historical intents already charged their call.
        stage['reserved_seconds'] -= session['limit']
        stage['used_seconds'] += receipt['elapsed_seconds']
        if 'compute' in session:
            tier = session['compute']['tier']
            stage['compute']['reserved_seconds'][tier] -= session['limit']
            stage['compute']['used_seconds'][tier] += receipt['elapsed_seconds']
        return
    usage = receipt.get('model_usage', {})
    outcome = usage.get('state', 'UNKNOWN')
    if outcome not in {'USED', 'NOT_STARTED', 'UNKNOWN'}: outcome = 'UNKNOWN'
    session['model_accounting'] = outcome
    stage['infrastructure_seconds'] = stage.get('infrastructure_seconds', 0) + receipt['elapsed_seconds']
    if outcome == 'UNKNOWN': return
    tier = session['compute']['tier']
    stage['reserved_calls'] -= 1
    stage['reserved_seconds'] -= session['limit']
    stage['compute']['reserved_calls'][tier] -= 1
    stage['compute']['reserved_seconds'][tier] -= session['limit']
    if outcome == 'USED':
        stage['used_calls'] += 1
        stage['compute']['used'][tier] += 1
        # Active elapsed is measured by worker, never inferred from CLI existence.
        elapsed = receipt.get('model_active_seconds', receipt['elapsed_seconds'])
        if type(elapsed) not in (int, float) or not 0 <= elapsed <= receipt['elapsed_seconds']:
            raise Conflict('invalid model active time')
        stage['used_seconds'] += elapsed
        stage['compute']['used_seconds'][tier] += elapsed


def correct_prelaunch(store, sid):
    """Only trusted, historically explicit prelaunch failures qualify; no guesses."""
    state = store.replay(); se = state['sessions'][sid]
    if sid in state.get('accounting_corrections', {}): return state
    directory = Path(se['directory'])
    if (se.get('accounting_version') == 2 or not se.get('prelaunch_failure')
            or se['status'] != 'REJECTED' or se.get('identity') is not None
            or (directory / 'request.json').exists() or (directory / 'receipt.json').exists()):
        raise Conflict('no exact historical prelaunch failure evidence')
    source = directory / 'validation.json'
    raw = source.read_bytes()
    artifact = json.loads(raw)
    if 'worker not launched' not in artifact.get('accounting', ''):
        raise Conflict('historical source does not establish no launch')
    correction = {'session_id': sid, 'source': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                  'reason': 'explicit worker-not-launched record; historical intent was incorrectly charged',
                  'calls_returned': 1, 'seconds_returned': 0}
    def change(s):
        if s['sessions'][sid] != se or source.read_bytes() != raw:
            raise Conflict('correction source drift')
        st = s['stages'][se['stage_id']]
        if st['used_calls'] < 1: raise Conflict('invalid historical usage')
        st['used_calls'] -= 1
        if 'compute' in se: st['compute']['used'][se['compute']['tier']] -= 1
        s.setdefault('accounting_corrections', {})[sid] = correction
    return store.transact('MODEL_ACCOUNTING_CORRECTED', sid + ':prelaunch-correction-v2', change,
                          expected=state['version'], object_id=sid)
