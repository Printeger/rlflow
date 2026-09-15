import copy
import pytest
from rlflow import research,progress
from rlflow.store import Conflict,sha


def setup():
    t={'id':'t','cycle_id':'t','text':'why failure','stage_id':'s','package_id':'p','research_mode':True,'criteria':[{'id':'C1'}],'status':'QUEUED'}
    return {'research':{},'evidence':{},'jobs':{}},t


def transition(s,t,role,payload):
    return research.route(s,t,{'id':role+str(len(s['research'])),'role':role},{'payload':payload,'requested_actions':[]})


@pytest.mark.parametrize('decision,next_role',[('CONTINUE','Critic'),('PARAMETER_SEARCH','Critic'),('ENGINEERING_DIAGNOSIS','Engineer'),('METHOD_REVIEW','Critic'),('EVALUATION_REVIEW','Critic')])
def test_pi_decisions_execute_readonly_or_in_scope_routes(decision,next_role):
    s,t=setup();assert transition(s,t,'PI',{'decision':decision,'next_prediction':'discriminate H1','proposal_required':False})
    assert t['next_role']==next_role
    assert not s.get('approvals')


def test_stop_and_proposal_are_distinct():
    s,t=setup();transition(s,t,'PI',{'decision':'STOP'});assert t['status']=='STOPPED'
    s,t=setup();transition(s,t,'PI',{'decision':'CONTINUE','next_prediction':'x','proposal_required':True});assert t['status']=='CONTRACT_DECISION'


@pytest.mark.parametrize('verdict,job_status,valid,disposition',[
    ('PASS','SUCCEEDED',True,'SUPPORTED'),('FAIL','SUCCEEDED',True,'FALSIFIED'),
    ('INCONCLUSIVE','SUCCEEDED',True,'INCONCLUSIVE'),('INVALID','SUCCEEDED',False,'ACTIVE'),
    ('FAIL','FAILED',False,'ACTIVE')])
def test_research_result_keeps_negative_invalid_and_launch_failure_separate(verdict,job_status,valid,disposition):
    s,t=setup();h={'statement':'H1','supporting_evidence':[],'counter_evidence':[],'discriminating_test':'vary x'}
    transition(s,t,'Critic',{'hypotheses':[h]});c=research.record(s,t);hid=c['hypotheses'][0]['id']
    t['research_job']='j';s['jobs']['j']={'status':job_status}
    transition(s,t,'Evaluator',{'verdict':verdict,'missing_evidence':[],'evidence_coverage':[hid+':'+disposition]})
    assert c['valid_cycles']==int(valid) and c['hypotheses'][0]['status']==disposition
    assert t['next_role']=='PI'
    if verdict!='PASS':assert c['negative_results']


def test_cold_review_raw_must_precede_interpretation():
    s,t=setup();c=research.record(s,t);c['cold_due']=True
    transition(s,t,'PI',{'decision':'CONTINUE','next_prediction':'verify','proposal_required':False})
    assert t['cold_review']=='RAW'
    transition(s,t,'Evaluator',{'verdict':'PASS'})
    assert c['cold_raw'] and t['cold_review']=='INTERPRETED'
    transition(s,t,'Evaluator',{'verdict':'PASS'})
    assert not c['cold_due'] and t['next_role']=='PI'


def test_renamed_findings_and_new_candidate_do_not_make_progress():
    s,t=setup();s['evidence']['e']={'sha256':'1'*64}
    finding={'id':'original','category':'MUST_FIX','contract':'C1','affected_conclusion':'CPU','close_condition':'reject negatives','description':'negative accepted','evidence_refs':['e']}
    assert not progress.review(s,t,{'findings':[finding]})
    finding={**finding,'id':'renamed','description':'new prose'};t['candidate']='different comment commit'
    assert progress.review(s,t,{'findings':[finding]})
    assert len(s['research']['p']['findings'])==1
    s['evidence']['new']={'sha256':'2'*64,'material_observation':True,'verified_condition':'C1'}
    finding['evidence_refs']=['new']
    assert not progress.review(s,t,{'findings':[finding]})


def test_closed_problem_cannot_reopen_without_new_material_evidence():
    s,t=setup();s['evidence']['e']={'sha256':'1'*64}
    f={'id':'f','category':'MUST_FIX','contract':'C1','affected_conclusion':'CPU','close_condition':'fix','evidence_refs':['e']}
    progress.review(s,t,{'findings':[f]});progress.review(s,t,{'findings':[]})
    with pytest.raises(Conflict):progress.review(s,t,{'findings':[f]})


def test_scout_quota_and_role_authority():
    s,t=setup();action={'action':'REQUEST_REVIEW','fields':['Scout'],'purpose':'specific current question','evidence_ids':[]}
    research.requests(s,t,{'role':'PI'},{'requested_actions':[action]})
    assert t['next_role']=='Scout'
    with pytest.raises(Conflict):research.requests(s,t,{'role':'PI'},{'requested_actions':[action]})
    with pytest.raises(Conflict):research.requests(s,t,{'role':'Scout'},{'requested_actions':[{**action,'action':'REQUEST_EXPERIMENT'}]})


def test_only_raw_independently_bound_observation_can_mark_progress():
    import json
    s,t=setup();s['evidence']['job']={'job_id':'J','accepted':True,'task_id':'t','sha256':'a'*64}
    proof={'condition_id':'C1','evidence_id':'job','evidence_sha256':'a'*64,'explanation':'raw observation rules out numerical overflow'}
    payload={'evidence_coverage':['OBSERVATION:'+json.dumps(proof)]}
    progress.verify_observations(s,t,{'role':'Evaluator','id':'S-E'},payload)
    assert s['evidence']['job']['material_observation']
    with pytest.raises(Conflict):progress.verify_observations(s,t,{'role':'PI','id':'S-P'},payload)
    s['evidence']['job'].pop('job_id')
    with pytest.raises(Conflict):progress.verify_observations(s,t,{'role':'Evaluator','id':'S-E'},payload)


def test_task_rename_does_not_reset_package_problem_memory():
    s,t=setup();s['evidence']['e']={'sha256':'a'*64}
    f={'id':'f','category':'MUST_FIX','contract':'C1','affected_conclusion':'CPU','close_condition':'fix','evidence_refs':['e']}
    assert not progress.review(s,t,{'findings':[f]})
    other={**t,'id':'renamed','open_problem_keys':[],'no_progress_rounds':0}
    assert progress.review(s,other,{'findings':[{**f,'id':'also-renamed'}]})


def test_new_critic_does_not_erase_falsified_hypotheses():
    s,t=setup();hyp={'statement':'H1','supporting_evidence':[],'counter_evidence':[],'discriminating_test':'fixed probe'}
    transition(s,t,'Critic',{'hypotheses':[hyp]});c=research.record(s,t);c['hypotheses'][0]['status']='FALSIFIED'
    transition(s,t,'Critic',{'hypotheses':[{**hyp,'statement':'H2'}]})
    assert c['hypothesis_history'][0]['status']=='FALSIFIED'
