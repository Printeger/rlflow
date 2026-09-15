import copy
import pytest
from rlflow.contracts import ContractError, ROLES, role_schema, validate_result, classify_change, build_pi_packet


def sample(schema):
    if 'const' in schema: return schema['const']
    if 'enum' in schema: return schema['enum'][0]
    if 'anyOf' in schema: return sample(schema['anyOf'][0])
    kind = schema.get('type')
    if kind == 'object': return {k:sample(v) for k,v in schema.get('properties',{}).items() if k in schema.get('required',[])}
    if kind == 'array': return []
    if kind == 'integer': return schema.get('minimum',0)
    if kind == 'boolean': return False
    if kind == 'null': return None
    return '0'*64 if 'pattern' in schema else 'fixture'


@pytest.mark.parametrize('role',ROLES)
def test_all_role_contracts(role):
    result=sample(role_schema(role))
    if role=='Evaluator': result['payload']['verdict']='INCONCLUSIVE'
    validate_result(result, {'role':role,'task_version':1})
    invalid=copy.deepcopy(result);invalid['payload']['unknown']=True
    with pytest.raises(ContractError): validate_result(invalid)
    with pytest.raises(ContractError): validate_result(result,{'input_state_version':99})


def test_hypothesis_and_scout_limits():
    for role,key in [('Critic','hypotheses'),('Scout','cards')]:
        result=sample(role_schema(role)); spec=role_schema(role)['properties']['payload']['properties'][key]['items']
        result['payload'][key]=[sample(spec)]*4
        with pytest.raises(ContractError): validate_result(result)


def test_pass_must_have_provenance_and_no_missing():
    result=sample(role_schema('Evaluator'))
    with pytest.raises(ContractError): validate_result(result)
    result['payload']['evidence_coverage']=['CPU parser cases']
    validate_result(result)
    result['payload']['missing_evidence']=['required test']
    with pytest.raises(ContractError): validate_result(result)


def test_classification_mixed_and_unknown(tmp_path):
    change={'path':str(tmp_path/'a.py'),'categories':['ENGINEERING_FIX','METHOD_CHANGE'],'review_categories':['ENGINEERING_FIX','METHOD_CHANGE'],'contract_ref':'stage-contract-v1'}
    kwargs={'module_roots':[str(tmp_path)],'candidate':{'commit':'abc'},'diff_sha256':'0'*64}
    assert classify_change([change],['ENGINEERING_FIX'],**kwargs)['status']=='APPROVAL_REQUIRED'
    assert classify_change([change],['ENGINEERING_FIX','METHOD_CHANGE'],**kwargs)['status']=='AUTHORIZED'
    change['review_categories']=['ENGINEERING_FIX']
    assert classify_change([change],['ENGINEERING_FIX','METHOD_CHANGE'],**kwargs)['status']=='UNRESOLVED'


def test_symlink_protected_path(tmp_path):
    allowed=tmp_path/'allowed';allowed.mkdir();protected=tmp_path/'protected';protected.mkdir()
    (allowed/'link').symlink_to(protected,target_is_directory=True)
    c={'path':str(allowed/'link'/'a'),'categories':['ENGINEERING_FIX'],'review_categories':['ENGINEERING_FIX'],'contract_ref':'v1'}
    result=classify_change([c],['ENGINEERING_FIX'],module_roots=[str(allowed)],protected_paths=[str(protected)],candidate={'commit':'abc'},diff_sha256='0'*64)
    assert result['status']=='UNRESOLVED'


def test_pi_packet_deterministic_and_preserves_constraints():
    state={'state_version':12,'STOP':True,'permissions':{'gpu':False},'budgets':{'remaining':None},'unresolved_findings':['F9'],'critical_counterevidence':['C1'],'evidence':[{'id':'E1','sequence':1,'summary':'observed','counterevidence':['negative'],'body':'large '*15000,'raw_logs':'do not include'}]}
    packet=build_pi_packet(state)
    assert packet==build_pi_packet(copy.deepcopy(state))
    assert packet['packet']['current_state']['STOP'] is True
    assert packet['packet']['budgets']['remaining'] is None
    assert packet['packet']['evidence'][0]['counterevidence']==['negative']
    assert 'raw_logs' not in packet['packet']['evidence'][0]
    assert packet['packet']['omitted_objects']
    state['unresolved_findings']=['cannot omit '*20000]
    with pytest.raises(ContractError,match='PACKET_TOO_LARGE'): build_pi_packet(state)


@pytest.mark.parametrize('role', ROLES)
def test_provider_schema_is_explicit_and_closed(role):
    def check(node):
        if isinstance(node, dict):
            if 'const' in node or 'enum' in node:
                assert 'type' in node, node
            if node.get('type') == 'object':
                assert node.get('additionalProperties') is False, node
                assert set(node.get('required', [])) == set(node.get('properties', {})), node
            if node.get('type') == 'array':
                assert 'items' in node
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    schema = role_schema(role)
    assert schema['type'] == 'object'
    check(schema)


def test_cpu_scope_limitation_does_not_require_out_of_scope_evidence():
    result = sample(role_schema('Evaluator'))
    result['payload'].update(
        verdict='PASS', conclusion_layer='CPU', findings=[], missing_evidence=[],
        evidence_coverage=['Independent CPU parser boundary tests passed.',
                           'CPU scope only; real-run, behavior and formal validation not performed.'])
    validate_result(result)
    # Report guidance clarifies placement; it does not weaken the acceptance gate
    # or silently remove conflicting fields from historical results.
    result['payload']['missing_evidence'] = ['Required CPU boundary test was not run.']
    with pytest.raises(ContractError, match='missing required evidence'):
        validate_result(result)
    result['payload']['verdict'] = 'INCONCLUSIVE'
    validate_result(result)
