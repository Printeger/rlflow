"""Approved condition-to-verifier mapping and replayable evidence DATA, not authority."""
from .hybrid_protocol import ID,HASH,obj,enum,validate_schema
from .hybrid_goals import digest
from .store import Conflict

BINDINGS={'type':'object','minProperties':2,'maxProperties':200,'propertyNames':ID,
    'additionalProperties':obj({'condition_sha256':HASH,'verifier':enum(
        'ORIGINAL_CPU_CHECKS_V1','ORIGINAL_INDEPENDENT_REVIEW_V1')})}
VERIFIERS={'deterministic':'ORIGINAL_CPU_CHECKS_V1',
    'independent_review':'ORIGINAL_INDEPENDENT_REVIEW_V1'}


def validate_bindings(proposal,spec):
    bindings=spec.get('condition_bindings')
    if bindings is None:return None  # Historical approval is never upgraded.
    validate_schema(BINDINGS,bindings)
    conditions={c['id']:c for c in proposal['global_conditions'] if c['required']}
    if set(bindings)!=set(conditions):raise Conflict('exact approved required condition bindings required')
    for key,condition in conditions.items():
        if (bindings[key]['condition_sha256']!=digest(condition) or
                bindings[key]['verifier']!=VERIFIERS.get(condition['verification']['method'])):
            raise Conflict('approved condition hash or verification method differs')
    return bindings


def derive(proposal,config,cpu,engineer,reviewer):
    """All inputs must separately be authenticated original whole events."""
    from .hybrid_a_workflow_review import from_cpu
    from .hybrid_budget_ledger import entry_key
    from .hybrid_native_model_result import validate_publication
    material=from_cpu(proposal,config,cpu,engineer)
    spec=config['tools']['native_model']['definition']['spec']
    bindings=validate_bindings(proposal,spec)
    if bindings is None:raise Conflict('explicit original condition bindings required; no historical upgrade')
    rr=reviewer['request']['fixture_runtime'];er=engineer['request']['fixture_runtime']
    binding=rr['origin'].get('native_model',{});workflow=binding.get('workflow',{})
    if (reviewer['decision']!='SETTLED' or rr['phase']!='FIXTURE_SCOPE_STOPPED' or
            workflow.get('stage')!='INDEPENDENT_REVIEW' or binding.get('role')!='Evaluator' or
            workflow.get('parents')!=material['parents'] or
            workflow.get('machine_result_sha256')!=material['machine_result_sha256'] or
            workflow.get('files')!=material['packet']['files'] or
            binding.get('candidate_sha256')!=digest(material['packet']['files']) or
            not engineer['accepted_state_version']<cpu['accepted_state_version']<reviewer['accepted_state_version']):
        raise Conflict('original settled independent Reviewer candidate chain required')
    for parent in (cpu,engineer):
        if (any(parent['request'][k]!=reviewer['request'][k] for k in
                ('project_id','data_mode','store_epoch','goal_ref')) or
                any(parent['policy_source'][k]!=reviewer['policy_source'][k] for k in
                    ('proposal_hash','approval_hash','config_hash','scope_hash'))):
            raise Conflict('condition original parent scope or approval differs')
    ev=er.get('native_model_result');rv=rr.get('native_model_result')
    if ev is None or rv is None:raise Conflict('original complete model results required for condition evidence')
    validate_publication(ev,er,approved_paths=spec['candidate_paths']);validate_publication(rv,rr)
    implementer=er['native_model_usage'].get('model_session_id')
    reviewer_id=rr['native_model_usage'].get('model_session_id')
    if (not implementer or not reviewer_id or implementer==reviewer_id or
            er['producer']==rr['producer'] or
            any(er['origin'][k]==rr['origin'][k] for k in ('lease_id','task_id','attempt_id')) or
            er['native_model_usage']['source_id']==rr['native_model_usage']['source_id']):
        raise Conflict('distinct original model sessions and runtime sources required')
    if rv['review']['verdict']!='ACCEPT':raise Conflict('original Reviewer has not accepted candidate')
    refs={name:{'key':entry_key(parent['request']),'hash':digest(parent)}
        for name,parent in (('engineer',engineer),('cpu',cpu),('reviewer',reviewer))}
    evidence=[]
    for condition in proposal['global_conditions']:
        if not condition['required']:continue
        row=bindings[condition['id']]
        evidence.append({'condition_id':condition['id'],'condition_sha256':digest(condition),
            'candidate_sha256':binding['candidate_sha256'],'configuration_sha256':reviewer['policy_source']['config_hash'],
            'evaluation_data_sha256':digest(proposal['evaluation_data']),
            'evaluation_rule_sha256':proposal['evaluation_data']['evaluation_rule']['version_hash'],
            'verifier':row['verifier'],'verdict':'PASS','implementer_session_id':implementer,
            'reviewer_session_id':reviewer_id,'original_event_refs':refs})
    return {'evidence':evidence,'candidate_sha256':binding['candidate_sha256'],
        'required_conditions_passed':len(evidence),'parents':refs}
