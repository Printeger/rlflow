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
HEAD['properties']['candidate_cpu_entry']=ID
HEAD['properties']['review_entries']={'type':'object','maxProperties':2,'propertyNames':ID,'additionalProperties':ID}
HEAD['properties']['continuation_entry']=ID
HEAD['properties']['continuation_acceptance']=obj({'key':ID,'hash':HASH})
HEAD['dependentRequired']={'continuation_entry':['continuation_acceptance'],
    'continuation_acceptance':['continuation_entry']}


def advance(value, prior):
    request=value['request']; runtime=request.get('fixture_runtime',{})
    origin=runtime.get('origin',{})
    workflow=origin.get('native_model',{}).get('workflow') or origin.get('local_cpu',{}).get('workflow')
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
    if workflow['stage']=='CONTINUATION':
        from .hybrid_native_model_profile import BINDING,KIND
        from .hybrid_budget_ledger import entry_key
        binding=origin['native_model'];validate_schema(BINDING,binding)
        if (origin.get('kind')!=KIND or prior is None or 'continuation_entry' in prior or
                prior['approval_sha256']!=value['policy_source']['approval_hash'] or
                binding['role']!='Engineer' or binding['effort']!='medium' or
                not prior.get('candidate_cpu_entry') or not prior.get('review_entries')):
            raise Conflict('original unique accepted continuation stage required')
        check_window(prior,workflow,timestamp(value['recorded_at']))
        charge=value['prior_reservation']['amount']['wall_seconds']
        if (charge<binding['seconds']+10 or prior['medium_sessions']+1>limits['medium_sessions'] or
                prior['controlled_seconds_charged']+charge>limits['controlled_seconds']):
            raise Conflict('workflow continuation quota exceeded')
        return {**prior,'medium_sessions':prior['medium_sessions']+1,
            'controlled_seconds_charged':prior['controlled_seconds_charged']+charge,
            'continuation_entry':entry_key(request),'continuation_acceptance':workflow['acceptance']}
    if workflow['stage']=='INDEPENDENT_REVIEW':
        from .hybrid_native_model_profile import BINDING,KIND
        from .hybrid_budget_ledger import entry_key
        binding=origin['native_model'];validate_schema(BINDING,binding)
        if (origin.get('kind')!=KIND or prior is None or
                prior['approval_sha256']!=value['policy_source']['approval_hash'] or
                binding['role']!='Evaluator' or binding['effort']!='high' or
                workflow['cpu_registration']!=prior.get('candidate_cpu_entry') or
                workflow['cpu_registration'] in prior.get('review_entries',{})):
            raise Conflict('original unique independent Reviewer CPU stage required')
        check_window(prior,workflow,timestamp(value['recorded_at']))
        charge=value['prior_reservation']['amount']['wall_seconds']
        if (charge<binding['seconds']+10 or prior['high_sessions']+1>limits['high_sessions'] or
                prior['controlled_seconds_charged']+charge>limits['controlled_seconds']):
            raise Conflict('workflow independent Reviewer quota exceeded')
        return {**prior,'high_sessions':prior['high_sessions']+1,
            'controlled_seconds_charged':prior['controlled_seconds_charged']+charge,
            'review_entries':{**prior.get('review_entries',{}),workflow['cpu_registration']:entry_key(request)}}
    if workflow['stage']=='CANDIDATE_CPU':
        from .hybrid_local_cpu_profile import KIND,WORKFLOW
        from .hybrid_budget_ledger import entry_key
        validate_schema(WORKFLOW,workflow)
        if (origin.get('kind')!=KIND or prior is None or
                prior['approval_sha256']!=value['policy_source']['approval_hash'] or
                'candidate_cpu_entry' in prior):
            raise Conflict('original CPU workflow parent or unique stage required')
        check_window(prior,workflow,timestamp(value['recorded_at']))
        charge=value['prior_reservation']['amount']['wall_seconds']
        if (origin['local_cpu']['purpose']!='engineering' or
                charge<origin['local_cpu']['task_seconds']+10 or
                prior['controlled_seconds_charged']+charge>limits['controlled_seconds']):
            raise Conflict('workflow CPU controlled time quota exceeded')
        return {**prior,'candidate_cpu_entry':entry_key(request),
            'controlled_seconds_charged':prior['controlled_seconds_charged']+charge}
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
