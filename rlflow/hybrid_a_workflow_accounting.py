"""Durable conservative workflow admission on the original Goal budget head.

Counts original registrations, not provider requests. Charges the full managed
reservation ceiling (including teardown) without claiming measured execution.
No model usage refunds or output/evidence authority are provided here.
"""
from .hybrid_protocol import ID, HASH, TIME, obj, validate_schema
from .hybrid_authority import timestamp
from .store import Conflict

COUNT={'type':'integer','minimum':0,'maximum':5400}
LIMITS=obj({'medium_sessions':{'type':'integer','minimum':1,'maximum':6},
    'high_sessions':{'type':'integer','minimum':1,'maximum':2},
    'controlled_seconds':{'type':'integer','minimum':1,'maximum':3600},
    'wall_seconds':{'type':'integer','minimum':1,'maximum':5400}})
HEAD=obj({'envelope_sha256':HASH,'approval_sha256':HASH,'first_engineer_entry':ID,
    'medium_sessions':COUNT,'high_sessions':COUNT,'controlled_seconds_charged':COUNT,
    'started_at':TIME})


def advance(value, prior):
    request=value['request']; runtime=request.get('fixture_runtime',{})
    workflow=runtime.get('origin',{}).get('native_model',{}).get('workflow')
    if prior is not None:
        validate_schema(HEAD,prior)
        if any(type(prior[field]) is not int for field in
                ('medium_sessions','high_sessions','controlled_seconds_charged')):
            raise Conflict('exact original workflow counters required')
    if (workflow is None or runtime.get('phase')!='REGISTER_NO_HANDOFF' or
            'accounting_version' not in workflow):return prior
    if workflow['accounting_version']!='A_REGISTRATION_CEILINGS_V1':
        raise Conflict('closed original workflow accounting version required')
    validate_schema(LIMITS,workflow['limits']);limits=workflow['limits']
    if any(type(n) is not int for n in limits.values()):raise Conflict('exact workflow limits required')
    if workflow['stage']!='FIRST_ENGINEER' or prior is not None:
        raise Conflict('workflow first Engineer already registered; no stage reset')
    binding=runtime['origin']['native_model']; charge=value['prior_reservation']['amount']['wall_seconds']
    if (binding['role']!='Engineer' or binding['effort']!='medium' or
            charge<binding['seconds']+10 or charge>limits['controlled_seconds']):
        raise Conflict('workflow controlled time or role quota exceeded')
    from .hybrid_budget_ledger import entry_key
    return {'envelope_sha256':workflow['envelope_sha256'],
        'approval_sha256':value['policy_source']['approval_hash'],
        'first_engineer_entry':entry_key(request),'medium_sessions':1,'high_sessions':0,
        'controlled_seconds_charged':charge,'started_at':value['recorded_at']}


def check_window(head, workflow, now):
    validate_schema(HEAD,head);validate_schema(LIMITS,workflow['limits'])
    if (head['envelope_sha256']!=workflow['envelope_sha256'] or
            not 0<=(now-timestamp(head['started_at'])).total_seconds()<workflow['limits']['wall_seconds'] or
            head['medium_sessions']>workflow['limits']['medium_sessions'] or
            head['high_sessions']>workflow['limits']['high_sessions'] or
            head['controlled_seconds_charged']>workflow['limits']['controlled_seconds']):
        raise Conflict('original workflow window or quota exhausted')
