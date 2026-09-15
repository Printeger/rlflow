"""Versioned role contracts. Classification never infers semantics from file names."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any
import jsonschema

ROOT = Path(__file__).resolve().parent.parent
ROLES = ('PI', 'Critic', 'Designer', 'Engineer', 'Evaluator', 'Scout')
CATEGORIES = frozenset(('ENGINEERING_FIX', 'AUTHORIZED_PARAMETER', 'METHOD_CHANGE', 'EVALUATION_CHANGE', 'RUNTIME_CHANGE', 'RESOURCE_CHANGE'))
TOKENIZER_VERSION = '0.9.0'

class ContractError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def role_schema(role: str) -> dict:
    if role not in ROLES:
        raise ContractError(f'Unknown role: {role}')
    return json.loads((ROOT / 'schemas' / f'{role}Result.json').read_text())


def validate_object(name: str, value: dict) -> None:
    if name not in ('Task', 'Hypothesis', 'Experiment', 'Evidence', 'Decision', 'Proposal', 'Approval', 'Event', 'RoleResult'):
        raise ContractError('Unknown object schema')
    try:
        jsonschema.Draft202012Validator(json.loads((ROOT / 'schemas' / f'{name}.json').read_text())).validate(value)
        canonical_bytes(value)
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ContractError(str(exc)) from exc


def validate_result(result: dict, expected: dict | None = None, evidence_ids=None) -> None:
    try:
        jsonschema.Draft202012Validator(role_schema(result.get('role'))).validate(result)
        canonical_bytes(result)
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ContractError(str(exc)) from exc
    for key, value in (expected or {}).items():
        if key not in result or result[key] != value:
            raise ContractError(f'Stale or mismatched result: {key}')
    if evidence_ids is not None:
        def refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('evidence_refs', 'evidence_ids', 'supporting_evidence', 'counter_evidence') and isinstance(item, list):
                        yield from (x for x in item if isinstance(x, str))
                    else:
                        yield from refs(item)
            elif isinstance(value, list):
                for item in value:
                    yield from refs(item)
        unknown = set(refs(result)) - set(evidence_ids)
        if unknown:
            raise ContractError(f'Unreachable evidence: {sorted(unknown)}')
    payload = result['payload']
    if result['role'] == 'Engineer' and result['candidate'] != payload['candidate']:
        raise ContractError('Candidate envelope/payload mismatch')
    if result['role'] == 'Evaluator' and payload['verdict'] == 'PASS':
        if payload['missing_evidence'] or not payload['evidence_coverage']:
            raise ContractError('PASS requires evidence coverage and no missing required evidence')
        if any(f['category'] in ('MUST_FIX', 'CONTRACT_DECISION') for f in payload['findings']):
            raise ContractError('PASS cannot contain blocking findings')


def classify_change(changes: list[dict], authorized_categories=(), *, module_roots=(), protected_paths=(), parameter_rules=None, candidate=None, diff_sha256=None) -> dict:
    """Classify externally verified semantic attestations, NOT Engineer self-reports.

    Each change requires path, categories, contract_ref, and matching independent
    review_categories. Callers must derive these from trusted review records. A
    numeric parameter additionally requires name/value and a frozen allowlist.
    This helper alone does not authorize dispatch; exact approvals remain required.
    """
    categories, reasons = set(), []
    parameter_rules = parameter_rules or {}
    roots = [Path(p).resolve() for p in module_roots]
    protected = [Path(p).resolve() for p in protected_paths]
    for change in changes:
        path = Path(change.get('path', '')).resolve()
        declared, reviewed = set(change.get('categories', [])), set(change.get('review_categories', []))
        if not declared or not declared <= CATEGORIES or declared != reviewed or not change.get('contract_ref'):
            reasons.append(f'{path}: semantic classification requires independent contract clarification')
        categories.update(declared & CATEGORIES)
        if not roots or not any(path == root or root in path.parents for root in roots):
            reasons.append(f'{path}: outside authorized modules')
        if any(path == root or root in path.parents for root in protected):
            reasons.append(f'{path}: protected path')
        if 'AUTHORIZED_PARAMETER' in declared:
            rule = parameter_rules.get(change.get('parameter'))
            value = change.get('value')
            if not rule or isinstance(value, bool) or not isinstance(value, (int, float)) or not rule.get('method_allows') or not rule['minimum'] <= value <= rule['maximum']:
                reasons.append(f'{path}: parameter is not within an approved method range')
    unauthorized = sorted(categories - set(authorized_categories))
    if not candidate or not isinstance(diff_sha256, str) or len(diff_sha256) != 64 or any(c not in '0123456789abcdef' for c in diff_sha256):
        reasons.append('Missing exact candidate/diff identity')
    return {'classifier_version': '0.2', 'status': 'UNRESOLVED' if reasons else ('APPROVAL_REQUIRED' if unauthorized else 'AUTHORIZED'), 'categories': sorted(categories), 'unauthorized': unauthorized, 'reasons': reasons, 'candidate': candidate, 'diff_sha256': diff_sha256}


def build_pi_packet(state: dict, target_tokens=10000, max_tokens=15000) -> dict:
    """Deterministically select a snapshot; immutable evidence remains available by ID.

    All safety/authority sections and critical counterevidence are unabridged.
    Unknown input keys are retained in current_state, preventing accidental loss.
    """
    import tiktoken
    if importlib.metadata.version('tiktoken') != TOKENIZER_VERSION:
        raise ContractError(f'Tokenizer must be tiktoken=={TOKENIZER_VERSION}')
    if not 0 < target_tokens <= max_tokens <= 15000:
        raise ContractError('Invalid packet token bounds')
    version = state.get('state_version', state.get('version'))
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ContractError('Missing committed state version')
    encoding = tiktoken.get_encoding('cl100k_base')
    selected_keys = {'charter', 'versions', 'unresolved_findings', 'hypotheses', 'evidence', 'decisions', 'budgets', 'jobs', 'approvals'}
    def ordered(items):
        if isinstance(items, dict): items = list(items.values())
        return sorted(items, key=lambda x: (x.get('event_sequence', x.get('sequence', 0)), str(x.get('id', ''))))
    evidence = ordered(state.get('evidence', []))
    decisions = ordered(state.get('decisions', []))
    packet = {'selection_rule_version': 'explicit-snapshot-sequence/0.2', 'source_state_version': version,
              'charter': state.get('charter', {}), 'current_state': {k:v for k,v in state.items() if k not in selected_keys},
              'versions': state.get('versions', {}), 'unresolved_findings': state.get('unresolved_findings', []),
              'hypotheses': state.get('hypotheses', []), 'evidence': evidence,
              'decisions': decisions[-5:], 'older_decision_counterevidence': [{'id': d.get('id'), 'counterevidence': d.get('counterevidence', [])} for d in decisions[:-5] if d.get('counterevidence')], 'budgets': state.get('budgets', {}), 'jobs': state.get('jobs', {}),
              'approvals': state.get('approvals', []), 'omitted_objects': [{'type':'Decision','id':d.get('id'),'sha256':content_hash(d)} for d in decisions[:-5]]}
    # Raw logs are never copied into the default evidence packet.
    packet['evidence'] = [{k:v for k,v in e.items() if k not in ('raw_logs', 'raw_log', 'stdout', 'stderr')} for e in evidence]
    def count(): return len(encoding.encode(canonical_bytes(packet).decode('utf-8')))
    for i, original in enumerate(evidence):
        if count() <= target_tokens: break
        # Preserve semantic summary, provenance, missing observations and ALL counterevidence.
        removable = {'body', 'details', 'raw_logs', 'raw_log', 'stdout', 'stderr'}
        packet['evidence'][i] = {k:v for k,v in original.items() if k not in removable}
        packet['omitted_objects'].append({'type':'EvidenceDetail','id':original.get('id'),'sha256':content_hash(original)})
    tokens = count()
    if tokens > max_tokens:
        raise ContractError(f'PACKET_TOO_LARGE: {tokens} > {max_tokens}; split the task')
    return {'packet': packet, 'sha256': content_hash(packet), 'token_count': tokens, 'tokenizer': f'tiktoken=={TOKENIZER_VERSION}:cl100k_base', 'source_state_version': version}


def validate_runtime_state(state: dict) -> None:
    """Validate the actual persisted CPU state model (not conceptual research objects)."""
    from referencing import Registry, Resource
    resources = []
    for path in (ROOT / 'schemas').glob('*.json'):
        schema = json.loads(path.read_text())
        if '$id' in schema: schema['$id'] = path.as_uri()
        resources.append((path.as_uri(), Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)
    schema = json.loads((ROOT / 'schemas' / 'RuntimeState.json').read_text())
    schema['$id'] = (ROOT / 'schemas' / 'RuntimeState.json').as_uri()
    try:
        jsonschema.Draft202012Validator(schema, registry=registry).validate(state)
        canonical_bytes(state)
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ContractError('Invalid persisted runtime state: ' + str(exc)) from exc


def validate_runtime_event(event: dict) -> None:
    schema = json.loads((ROOT / 'schemas' / 'RuntimeEvent.json').read_text())
    try:
        jsonschema.Draft202012Validator(schema).validate(event)
        payload = json.loads(event['payload'])
        inputs = json.loads(event['input_versions'])
        if not isinstance(inputs, dict) or not isinstance(payload, dict) or set(payload) != {'set', 'details'} or not isinstance(payload['set'], dict):
            raise ContractError('Invalid event payload/input versions')
        if content_hash(payload) != event['payload_sha256']:
            raise ContractError('Event payload hash mismatch')
        if event['new_state_version'] != event['previous_state_version'] + 1 or event['seq'] != event['new_state_version'] or event['object_version'] != event['new_state_version']:
            raise ContractError('Event version chain mismatch')
    except (jsonschema.ValidationError, ValueError) as exc:
        raise ContractError('Invalid persisted runtime event: ' + str(exc)) from exc
