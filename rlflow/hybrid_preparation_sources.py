"""Private current source closure for non-executing preparation transactions.

Use the caller's actual read/write transaction, not a UI DTO or a separate
preflight snapshot. This does not grant a lease, budget, worker or release.
"""
from datetime import datetime, timezone
import json

from .hybrid_authority import (SECTIONS as AUTHORITY, command_key, timestamp,
                               _validate_approval)
from .hybrid_goals import (SECTIONS as GOALS, digest, draft_head, validate_record,
                          validate_source)
from .hybrid_protocol import ID, validate_schema
from .hybrid_reads import HybridReader, ReadBudget
from .hybrid_registry import Registry
from .observation import ObservationReader
from .store import Conflict, canonical


def load_sources(store, db, registry, *, project_id, data_mode, store_epoch, goal_ref, now, _budget=None):
    """Return detached raw original records and refs in this exact transaction.

    Protected startup fixes Store/Registry/scope/epoch. Caller JSON cannot create
    this protection: the future Store writer must also require actual service
    ownership and a service-issued live guard at both intent and completion.
    """
    if type(registry) is not Registry: raise TypeError('protected immutable Registry required')
    if type(now) is not datetime or now.tzinfo != timezone.utc:
        raise Conflict('preparation clock must be UTC')
    if not db.in_transaction: raise Conflict('preparation source requires actual transaction')
    validate_schema(ID, goal_ref)
    try:
        meta = ObservationReader._meta(db)
        scope = (project_id, data_mode, store_epoch)
        if (meta['project_id'], meta['data_mode'], meta['store_epoch']) != scope:
            raise Conflict('preparation registration changed')
        version = meta['source_version']
        projection_version = db.execute('SELECT version FROM projection_meta WHERE singleton=1').fetchone()[0]
        if (type(version) is not int or not 0 <= version <= 2**63-1 or version != projection_version or
                version != db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]):
            raise Conflict('preparation source version invalid')
        config = json.loads(registry._raw)
        if (config['project_id'], config['data_mode']) != scope[:2]: raise Conflict('preparation Registry scope changed')
        budget = _budget if _budget is not None else ReadBudget(db)
        if type(budget) is not ReadBudget or budget.db is not db:raise Conflict('actual transaction read budget required')
        head = budget.object(GOALS[1], goal_ref)
        if head is None: raise Conflict('preparation draft not found')
        validate_record(GOALS[1], goal_ref, head)
        if (head['project_id'], head['data_mode']) != scope[:2]: raise Conflict('preparation goal scope differs')
        record_key = head['contract_key']; record = budget.object(GOALS[0], record_key)
        if record is None: raise Conflict('preparation original draft missing')
        validate_record(GOALS[0], record_key, record)
        proposal = record['contract']['proposal']
        if head != draft_head(proposal): raise Conflict('preparation current contract differs')
        if 'source_command_key' not in record: raise Conflict('preparation requires original draft source pointer')
        draft_command = record['source_command_key']; receipt = budget.object(GOALS[2], draft_command)
        if receipt is None: raise Conflict('preparation original draft receipt missing')
        draft_source = store._goal_source(db, draft_command, max_bytes=budget.remaining,
                                         _parse=budget.parse, _decode=budget.decode)
        validate_source(record_key, record, draft_command, receipt, draft_source)
        if receipt['accepted_state_version'] > version: raise Conflict('preparation draft source from future')
        authority_head = budget.object(AUTHORITY[2], goal_ref)
        reader = HybridReader(store, project_id=project_id, data_mode=data_mode, store_epoch=store_epoch,
                              clock=lambda: now)
        authority = reader._authority(db, budget, authority_head, proposal, version)
        if (authority is None or authority['recorded_state'] != 'LEASE_VALIDATION_PENDING' or
                not authority['applies_to_current_contract'] or authority['lifetime_status'] != 'UNEXPIRED'):
            raise Conflict('preparation current consent unavailable')
        approval_key = authority_head['approval_key']; fact = budget.object(AUTHORITY[0], approval_key)
        if fact is None: raise Conflict('preparation original approval missing')
        binding = registry.resolve(proposal)
        # Reconstruct the exact original displayed confirmation view; shape or
        # source hash alone cannot substitute for its complete proposal binding.
        _validate_approval(fact, lambda section, key: record if section == GOALS[0] and key == record_key else None)
        confirm = fact['request']['confirmation']
        if (fact['registry_witness'] != config or confirm['store_epoch'] != store_epoch or
                any(confirm[name] != binding[name] for name in ('proposal_hash', 'scope_hash', 'config_hash')) or
                not timestamp(fact['approved_at']) <= now < timestamp(fact['expires_at'])):
            raise Conflict('preparation approval configuration or lifetime changed')
        approval_command = command_key(fact['request'])
        approval_receipt = budget.object(AUTHORITY[3], approval_command)
        if approval_receipt is None: raise Conflict('preparation approval receipt missing')
        result = {'schema_version': '1.0', 'project_id': project_id, 'data_mode': data_mode,
            'store_epoch': store_epoch, 'source_version': version, 'goal_ref': goal_ref,
            'contract_key': record_key, 'contract_revision': proposal['contract_version'],
            'proposal_hash': digest(proposal), 'record_hash': digest(record),
            'draft_command_key': draft_command, 'draft_source_version': receipt['accepted_state_version'],
            'approval_key': approval_key, 'approval_hash': digest(fact),
            'authority_revision': authority_head['authority_revision'], 'approval_command_key': approval_command,
            'approval_source_version': approval_receipt['accepted_state_version'],
            'config_hash': binding['config_hash'], 'scope_hash': binding['scope_hash'],
            'evaluated_at': now.isoformat().replace('+00:00', 'Z'), 'expires_at': fact['expires_at'],
            'record': record, 'approval_fact': fact, 'execution_enabled': False}
        encoded = canonical(result)
        if len(encoded) > 3*1024**2: raise Conflict('preparation source output exceeds bound')
        return json.loads(encoded)
    except Conflict: raise
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        raise Conflict('preparation source invalid') from None


def historical_sources(store, db, sources, budget):
    """Bounded original point proofs, NOT current heads or full-chain audit."""
    from .hybrid_authority import validate_record as authority_record, _head, EVENTS
    if type(budget) is not ReadBudget or budget.db is not db or not db.in_transaction:
        raise Conflict('actual historical transaction budget required')
    rk=sources['contract_key'];ck=sources['draft_command_key']
    record=budget.object(GOALS[0],rk);receipt=budget.object(GOALS[2],ck)
    if record is None or receipt is None:raise Conflict('historical preparation draft missing')
    validate_record(GOALS[0],rk,record);validate_record(GOALS[2],ck,receipt)
    proof=store._goal_source(db,ck,max_bytes=min(budget.remaining,16*1024**2),
                             _parse=budget.parse,_decode=budget.decode)
    validate_source(rk,record,ck,receipt,proof)
    ak=sources['approval_key'];ac=sources['approval_command_key']
    fact=budget.object(AUTHORITY[0],ak);approval=budget.object(AUTHORITY[3],ac)
    if fact is None or approval is None:raise Conflict('historical preparation approval missing')
    authority_record(AUTHORITY[0],ak,fact);authority_record(AUTHORITY[3],ac,approval)
    original_head=_head(fact['request'],AUTHORITY[0],ak,fact)
    expected=((EVENTS['approve'],'hybrid-core',approval['request_hash'],approval['accepted_state_version']),
        sorted([(AUTHORITY[0],ak,digest(fact)),(AUTHORITY[3],ac,digest(approval)),
                (AUTHORITY[2],sources['goal_ref'],digest(original_head))]))
    actual=store._authority_event(db,ac,max_bytes=min(budget.remaining,3*1024**2),
                                  _parse=budget.parse,_decode=budget.decode)
    if (actual!=expected or approval['request']!=fact['request'] or
            approval['fact_key']!=ak or approval['fact_section']!=AUTHORITY[0] or approval['fact_hash']!=digest(fact)):
        raise Conflict('historical preparation approval original proof differs')
    return {GOALS[0]:{rk:record},GOALS[2]:{ck:receipt},
            AUTHORITY[0]:{ak:fact},AUTHORITY[3]:{ac:approval}}
