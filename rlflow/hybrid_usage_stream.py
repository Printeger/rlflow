"""Bounded CLI stream math only; never provenance, receipt or settlement.

The actual source owner supplies original positions and the trusted semantics.
Model text/tool stdout cannot create observations by embedding usage JSON.
"""
import hashlib
import json
import math

from .store import Conflict

MAX_LINE = 16384
MAX_NODES = 4096
MAX_EVENTS = 4096
MAX_THREADS = 64
FIELDS = ('input_tokens', 'output_tokens', 'cached_tokens')


def parse_line(raw, *, node_budget=None):
    if type(raw) is not bytes or len(raw) > MAX_LINE or not raw.endswith(b'\n'):
        raise Conflict('bounded complete original usage line required')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value: raise Conflict('duplicate usage JSON key')
            value[key] = item
        return value
    def constant(_): raise Conflict('nonfinite usage JSON')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        stack = [(value, 0)]; nodes = 0
        while stack:
            item, depth = stack.pop(); nodes += 1
            if node_budget is not None:
                node_budget[0] -= 1
                if node_budget[0] < 0: raise Conflict('finite usage poll node bound exceeded')
            if nodes > MAX_NODES or depth > 32: raise Conflict('finite usage JSON node/depth bound exceeded')
            if type(item) is float and not math.isfinite(item): constant(item)
            if type(item) is dict: stack.extend((child, depth + 1) for child in item.values())
            elif type(item) is list: stack.extend((child, depth + 1) for child in item)
        if type(value) is not dict or type(value.get('type')) is not str:
            raise Conflict('original usage event object required')
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Conflict('invalid bounded original usage JSON') from error


def _id(value):
    try: valid = type(value) is str and 1 <= len(value.encode()) <= 160
    except UnicodeError: valid = False
    if not valid:
        raise Conflict('bounded actual backend usage identity required')
    return value


class Accumulator:
    """Private in-memory finite accounting; callers cannot use it to settle."""
    def __init__(self, semantics):
        if semantics not in ('cumulative', 'per_turn'): raise Conflict('unknown protected usage semantics')
        self.semantics = semantics
        self.sources = {}; self.rows = {}; self.active = {}; self.failed = False
        self.threads = set(); self.aggregate = {}

    def accept(self, source_id, offset, raw, *, node_budget=None, _parsed=None, _allowed_threads=None):
        _id(source_id)
        if type(offset) is not int or not 0 <= offset < 2**63: raise Conflict('original usage offset required')
        event = parse_line(raw, node_budget=node_budget) if _parsed is None else _parsed
        kind = event['type']
        if source_id not in self.sources:
            if len(self.sources) >= 64: raise Conflict('finite usage source bound exceeded')
            self.sources[source_id] = {'thread': None, 'turn': 0, 'offset': -1}
        source = self.sources[source_id]
        if offset <= source['offset']: raise Conflict('original usage source position regressed/replayed')
        source['offset'] = offset
        if kind == 'thread.started':
            thread = _id(event.get('thread_id'))
            if _allowed_threads is None:
                if source['thread'] not in (None, thread): raise Conflict('original usage source thread changed')
            elif thread not in _allowed_threads:
                raise Conflict('usage thread outside original protected fixture topology')
            if thread not in self.threads and len(self.threads) >= MAX_THREADS:
                raise Conflict('finite usage thread bound exceeded')
            source['thread'] = thread; self.threads.add(thread)
            if thread not in self.aggregate:
                self.aggregate[thread] = {'known': dict.fromkeys(FIELDS), 'latest': None,
                                          'incomplete': False, 'observations': 0}
            return
        thread = source['thread']
        if kind == 'turn.started':
            if thread is None or thread in self.active: raise Conflict('usage turn start lineage differs')
            source['turn'] += 1; self.active[thread] = (source_id, source['turn'])
            return
        if kind in ('turn.failed', 'error'):
            self.failed = True
            return
        if kind != 'turn.completed': return  # Never extract JSON from model/tool text.
        if thread is None or source['turn'] == 0: raise Conflict('usage completion lacks original turn start')
        backend_id = event.get('turn_id') if event.get('turn_id') is not None else event.get('event_id')
        event_id = (thread, _id(backend_id)) if backend_id is not None else (thread, source_id, source['turn'])
        usage = event.get('usage')
        if usage is None: usage = {}
        if type(usage) is not dict: raise Conflict('invalid usage counter object')
        counts = {'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
                  'cached_tokens': usage.get('cached_input_tokens', usage.get('cached_tokens'))}
        if any(value is not None and (type(value) is not int or not 0 <= value < 2**63) for value in counts.values()):
            raise Conflict('bounded nonnegative usage counters required')
        if counts['cached_tokens'] is not None and counts['input_tokens'] is not None and counts['cached_tokens'] > counts['input_tokens']:
            raise Conflict('cached usage exceeds input; not a zero observation')
        previous = self.rows.get(event_id)
        if previous is not None:
            if previous['counts'] != counts: raise Conflict('stable usage event identity changed')
            if self.active.get(thread) == previous['turn_lineage']: del self.active[thread]
            return
        if self.active.get(thread) != (source_id, source['turn']):
            raise Conflict('usage completion is not original active turn')
        if len(self.rows) >= MAX_EVENTS: raise Conflict('finite usage observation bound exceeded')
        aggregate = self.aggregate[thread]
        if self.semantics == 'cumulative' and any(counts[k] is not None and aggregate['known'][k] is not None and
                counts[k] < aggregate['known'][k] for k in FIELDS):
            raise Conflict('cumulative usage regressed')
        known = dict(aggregate['known'])
        for field in FIELDS:
            if counts[field] is None: continue
            known[field] = counts[field] if self.semantics == 'cumulative' else (known[field] or 0) + counts[field]
            if known[field] >= 2**63: raise Conflict('finite aggregate usage counter bound exceeded')
        self.rows[event_id] = {'thread': thread, 'counts': counts, 'source_id': source_id,
            'offset': offset, 'line_sha256': hashlib.sha256(raw).hexdigest(),
            'turn_lineage': (source_id, source['turn'])}
        aggregate.update(known=known, latest=counts, observations=aggregate['observations'] + 1,
                         incomplete=aggregate['incomplete'] or any(value is None for value in counts.values()))
        del self.active[thread]

    def totals(self, *, inclusive_parent=None):
        if inclusive_parent is not None: _id(inclusive_parent)
        groups = [value for thread, value in self.aggregate.items()
                  if value['observations'] and (inclusive_parent is None or thread == inclusive_parent)]
        result = {}
        for field in FIELDS:
            values = [group['known'][field] for group in groups if group['known'][field] is not None]
            total = sum(values) if values else None
            if total is not None and total >= 2**63: raise Conflict('finite aggregate usage counter bound exceeded')
            result[field] = total
        result['complete'] = bool(groups) and not self.failed and not self.active and all(
            all(value is not None for value in group['latest'].values()) if self.semantics == 'cumulative'
            else not group['incomplete'] for group in groups)
        result.update(actual_cost_status='UNKNOWN', actual_cost=None, semantics=self.semantics,
                      settlement_enabled=False)
        return result
