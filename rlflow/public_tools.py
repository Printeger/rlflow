"""Closed promotion of trusted core receipts; never reads raw tool files.

This is return provenance, not authority, model activity or complete history.
"""
from functools import lru_cache
import json
from . import tool_journal as journal
from .hybrid_protocol import ProtocolError, validate, validate_schema
from .store import sha


@lru_cache(maxsize=1)
def receipt_schema():
    from .contracts import ROOT
    value = json.loads((ROOT/'schemas'/'ToolLedger.json').read_text())
    return {**value, '$ref':'#/$defs/receipt'}


def initialize(db, seq, version):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_tool_meta'").fetchone()
    if exists:
        row = db.execute('SELECT * FROM public_tool_meta WHERE singleton=1').fetchone()
        if row is None or not 0<=row['coverage_seq']<=seq or not 0<=row['coverage_version']<=version:
            raise ProtocolError('tool coverage requires explicit recovery','RESYNC_REQUIRED')
        return
    if (db.execute("SELECT 1 FROM observation_projection WHERE kind='tool_return' LIMIT 1").fetchone()
            or db.execute("SELECT 1 FROM observation_counters WHERE kind='tool_return' LIMIT 1").fetchone()):
        raise ProtocolError('missing historical tool coverage requires explicit recovery','RESYNC_REQUIRED')
    db.execute('CREATE TABLE IF NOT EXISTS public_tool_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1),coverage_seq INTEGER NOT NULL,coverage_version INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO public_tool_meta VALUES(1,?,?)',(seq,version))


def coverage(db, meta):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_tool_meta'").fetchone():return None
    row = db.execute('SELECT * FROM public_tool_meta WHERE singleton=1').fetchone()
    if row is None or not 0<=row['coverage_seq']<=meta['seq'] or not 0<=row['coverage_version']<=meta['source_version']:
        raise ProtocolError('tool coverage requires explicit recovery','RESYNC_REQUIRED')
    # Publication coverage is not retained event history. Epoch rotation keeps
    # historical projection rows; moving this cutoff to floor would falsely
    # describe those rows as post-restore returns. Logs expose their own floor.
    value = {'status':'PARTIAL','policy':'LIVE_ONLY','coverage_after_seq':row['coverage_seq'],
             'coverage_after_source_version':row['coverage_version'],'source':'BOUND_CPU_RETURN'}
    validate('ToolCoverage',value)
    return value


def promote(key, receipt, observed_at):
    """Fail closed for malformed optional observations, not core authority."""
    from .observation import public_id
    try:
        validate_schema(receipt_schema(),receipt)
        if receipt['status']!='COLLECTED' or receipt['verification']!='VERIFIED' or receipt['reason'] is not None:return None
        fact,row = receipt['fact'],receipt['registration']
        if fact is None or row['launch_witness'] is None or receipt['validation_digest'] is None:return None
        context = row['context'];journal.validate(row,context)
        identity = sha({'session':context['session'],'generation':context['generation']})
        semantic = sha({k:row[k] for k in ('context','command_digest','intent_sha256','launch_witness')})
        binding = {'fact':fact,'witness':row['launch_witness'],'context':context}
        task = None
        if receipt.get('validation_version')==2:
            if not isinstance(receipt.get('task_id'),str):return None
            binding['task_id'] = receipt['task_id'];task = public_id(receipt['task_id'])
        if (key!=receipt['id'] or key!=identity+':'+row['command_digest'] or receipt['source_id']!=identity
                or receipt['semantic_digest']!=semantic or fact['context']!=context or fact['intent_sha256']!=row['intent_sha256']
                or receipt['validation_digest']!=sha(binding)):return None
        expected = 'SETUP_FAILED' if fact['infrastructure_error'] is not None else 'TIMED_OUT' if fact['timed_out'] else 'RETURNED'
        if fact['state']!=expected:return None
        value = {'id':public_id(key),'kind':'tool_return','version':1,'source_status':'COLLECTED','observability':'PARTIAL',
                 'state':fact['state'],'tool':'cpu_exec','provenance':'BOUND_RETURN',
                 'exit_code':fact['exit_code'],'timed_out':fact['timed_out'],'wall_seconds':fact['wall_seconds'],
                 'infrastructure_error':fact['infrastructure_error'],'execution_id':public_id(context['session']),
                 'task_id':task,'observed_at':observed_at}
        validate('ToolReturn',value)
        return value
    except (ProtocolError,ValueError,TypeError,KeyError,OverflowError):return None


def references(rows):
    """Shared builder/filter membership: only fixed public lineage."""
    refs = {}
    for row in rows:
        refs[(row['kind'],row['id'])] = dict(kind=row['kind'],id=row['id'],version=row.get('version'))
        if row.get('task_id'):
            refs.setdefault(('task',row['task_id']),dict(kind='task',id=row['task_id'],version=None))
        if row['kind']=='tool_return':
            refs.setdefault(('execution',row['execution_id']),dict(kind='execution',id=row['execution_id'],version=None))
    return list(refs.values())
