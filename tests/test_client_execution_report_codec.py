"""Synthetic transport negatives; not physical execution evidence."""
from copy import deepcopy
from email.message import Message
import json
import pytest
from rlflow.agent_client import AgentClient,ClientError
from tests.test_agent_client import config
from tests.test_hybrid_control_api import ORIGIN


def summary():
    hashed='sha256:'+'a'*64
    return {'schema_version':'1.0','profile':'ORIGINAL_DELIVERY_CLIENT_REPORT',
        'project_id':'project_fixture','data_mode':'fixture','store_epoch':'store_'+'a'*32,
        'authority':'NOT_AUTHORITY','execution_enabled':False,'as_of_state_version':10,
        'goal_ref':'goal_fixture','contract_revision':1,'proposal_sha256':hashed,
        'source_coverage':'ORIGINAL_RESULT_AND_CURRENT_CONTRACT_VERIFIED','result_activation':'HISTORICAL_ONLY',
        'consent_status':'UNAVAILABLE_AS_OF','checked_at':'2026-10-10T00:00:00Z',
        'source':{'kind':'ENGINEERING','id':'candidate_output_result_fixture','sha256':hashed,'result_sha256':hashed,
            'configuration_sha256':hashed,'original_proposal_sha256':hashed,'recorded_state_version':9,
            'raw_item_count':21,'machine_case_count':21,'machine_status':'MACHINE_ACCEPTED_PENDING_REVIEW',
            'evidence_role':'UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE'},
        'conditions':[{'id':'condition_fixture','required':True,'verification_sha256':hashed,'status':'UNASSESSED'}],
        'required_count':1,'required_satisfied_count':0,'finalization_status':'BLOCKED_MISSING_EVIDENCE',
        'blockers':['MISSING_CONDITION_EVIDENCE','MISSING_INDEPENDENT_REVIEW',
            'CURRENT_CONSENT_UNAVAILABLE','RESULT_HISTORICAL_ONLY'],
        'independent_review_status':'NOT_PERFORMED','goal_completed':False,'dispatch_enabled':False,
        'model_call_enabled':False,'condition_evidence_write_enabled':False,
        'current_execution_status':'UNKNOWN','resource_release_status':'NOT_OBSERVED'}


def test_original_max_conditions_and_CPU_nullable_result_preserved():
    from rlflow.hybrid_client_execution_report import validate_public
    from rlflow.hybrid_protocol import ProtocolError
    value=summary()
    value['conditions']=[{**value['conditions'][0],'id':'condition_'+str(i)} for i in range(200)]
    value['required_count']=200
    validate_public(value,'project_fixture','ENGINEERING','candidate_output_result_fixture')
    value['source'].update(kind='CPU_TRIAL',id='cpu_assessment_fixture',result_sha256=None,raw_item_count=0,
        machine_case_count=0,machine_status='NOT_RECORDED')
    validate_public(value,'project_fixture','CPU_TRIAL','cpu_assessment_fixture')
    value['conditions'].append({**value['conditions'][0],'id':'over_limit'});value['required_count']=201
    with pytest.raises(ProtocolError):validate_public(value,'project_fixture','CPU_TRIAL','cpu_assessment_fixture')


@pytest.mark.parametrize('change',['extra','project','kind','source','hash','epoch','version','denominator',
    'satisfied','review','goal','dispatch','resource','execution','blocker','duplicate_condition','verification',
    'machine','cases','activation','consent','contract'])
def test_client_refuses_unbound_or_escalated_report(tmp_path,change):
    target=config(tmp_path,ORIGIN)
    client=AgentClient(cwd=target,environ={'RLFLOW_CONTROL_ORIGIN':ORIGIN,
        'RLFLOW_REQUEST_TOKEN':'unused_fixture_report_token_123'})
    value=summary()
    if change=='extra':value['opaque_private']=True
    elif change=='project':value['project_id']='foreign_project'
    elif change=='kind':value['source']['kind']='CPU_TRIAL'
    elif change=='source':value['source']['id']='candidate_output_result_other'
    elif change=='hash':value['source']['sha256']='unverified'
    elif change=='epoch':value['store_epoch']='store_unbound'
    elif change=='version':value['source']['recorded_state_version']=11
    elif change=='denominator':value['required_count']=0
    elif change=='satisfied':value['required_satisfied_count']=1
    elif change=='review':value['independent_review_status']='PASS'
    elif change=='goal':value['goal_completed']=True
    elif change=='dispatch':value['dispatch_enabled']=True
    elif change=='resource':value['resource_release_status']='FREE'
    elif change=='execution':value['current_execution_status']='STOPPED'
    elif change=='blocker':value['blockers'].remove('MISSING_INDEPENDENT_REVIEW')
    elif change=='duplicate_condition':value['conditions'].append(deepcopy(value['conditions'][0]));value['required_count']=2
    elif change=='verification':value['conditions'][0]['verification_sha256']='claimed'
    elif change=='machine':value['source']['machine_status']='PASS'
    elif change=='cases':value['source']['machine_case_count']=22
    elif change=='activation':value['result_activation']='CURRENT_SOURCE_AS_OF'
    elif change=='consent':value['consent_status']='CURRENT_AS_OF'
    elif change=='contract':value['source']['original_proposal_sha256']='sha256:'+'b'*64
    class Response:
        headers=Message();headers['Content-Type']='application/json'
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return json.dumps(value).encode()
    class Opener:
        def open(self,request,timeout):return Response()
    client._opener=Opener()
    with pytest.raises(ClientError):client.execution_report('ENGINEERING','candidate_output_result_fixture')
