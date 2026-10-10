"""Local condition CAS with EXPLICIT synthetic model caps; NOT real qualification."""
import copy
import hashlib
import json
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

from rlflow.hybrid_a_condition_acceptance import SECTION,EVENT,original_event,validate_complete
from rlflow.hybrid_a_condition_service import ConditionAcceptanceService
from rlflow.hybrid_a_condition_rules import validate_bindings,VERIFIERS,derive
from rlflow.hybrid_a_workflow_profile import registration,validate_approval
from rlflow.hybrid_usage_source import _RuntimeStartedObservation
from rlflow.hybrid_goals import digest
from rlflow.hybrid_native_model_source import NativeModelResult
from rlflow.hybrid_reads import ReadBudget
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_protocol import ProtocolError
from rlflow.store import Store,Conflict,canonical
from tests.test_hybrid_a_workflow_cpu_runtime import cpu_bound,synthetic_engineer_parent,ACTUAL_POPEN
from tests.test_hybrid_a_workflow_derivation import original,native_setup
from tests.test_hybrid_a_workflow_profile import workflow
from tests.test_hybrid_native_model_usage import publication


def bindings(proposal):
    return {c['id']:{'condition_sha256':digest(c),'verifier':VERIFIERS[c['verification']['method']]}
        for c in proposal['global_conditions'] if c['required']}


def condition_bound(config):
    registry,proposal=cpu_bound(config);row=json.loads(registry._raw)
    spec=row['tools']['native_model']['definition']['spec'];spec['condition_bindings']=bindings(proposal)
    rows=registration(spec)
    row.update(tools=rows['tools'],commands=rows['commands'],
        evaluation_rules={'workflow_rule':rows['rule']},resource_profile=rows['resources'])
    registry=Registry(row);proposal['registry_bindings']=registry.bindings
    proposal['evaluation_data']['evaluation_rule']['version_hash']=digest(rows['rule'])
    return registry,proposal


@pytest.mark.parametrize('damage',['none','missing','extra','hash','method','optional'])
def test_exact_condition_mapping_no_historical_upgrade(damage):
    registry,proposal=workflow();config=json.loads(registry._raw)
    spec=config['tools']['native_model']['definition']['spec']
    assert validate_bindings(proposal,spec) is None
    spec['condition_bindings']=bindings(proposal);key=next(iter(spec['condition_bindings']))
    if damage=='none':
        assert validate_bindings(proposal,spec)==bindings(proposal)
        return
    if damage=='missing':del spec['condition_bindings'][key]
    elif damage=='extra':spec['condition_bindings']['foreign']=copy.deepcopy(spec['condition_bindings'][key])
    elif damage=='hash':spec['condition_bindings'][key]['condition_sha256']=digest('wrong')
    elif damage=='method':spec['condition_bindings'][key]['verifier']='ORIGINAL_INDEPENDENT_REVIEW_V1'
    else:proposal['global_conditions'][0]['required']=False
    with pytest.raises((Conflict,ProtocolError)):validate_bindings(proposal,spec)


def test_marker_without_original_event_is_not_a_condition_domain():
    with pytest.raises(Conflict,match='domain differs'):
        validate_complete({'version':1,SECTION:{}},None,lambda key:None,0)


def test_historical_acceptance_checks_window_before_recognizing_fact(monkeypatch):
    # Isolate the historical window gate; original-source authentication is NOT supplied here.
    import rlflow.hybrid_a_condition_acceptance as domain
    from rlflow.hybrid_budget import balances,zero,account_key
    from rlflow.hybrid_budget_ledger import SECTIONS as BUDGET,scope
    from rlflow.hybrid_goals import SECTIONS as GOALS
    from rlflow.hybrid_authority import SECTIONS as AUTHORITY
    now=datetime(2026,10,11,tzinfo=timezone.utc)
    request=dict(project_id='project',data_mode='live',store_epoch='epoch',goal_ref='goal')
    hashes={k:digest(k) for k in ('proposal_hash','approval_hash','config_hash','scope_hash')}
    head=dict(workflow=dict(envelope_sha256=digest('envelope'),approval_sha256=hashes['approval_hash'],
        first_engineer_entry='first',medium_sessions=1,high_sessions=1,controlled_seconds_charged=660,
        started_at=now.isoformat().replace('+00:00','Z')),balance=balances(zero(),zero(),zero(),zero()))
    workflow=dict(envelope_sha256=head['workflow']['envelope_sha256'],
        limits=dict(medium_sessions=6,high_sessions=2,controlled_seconds=3600,wall_seconds=5400))
    parent=dict(request={**request,'fixture_runtime':{'origin':{'native_model':{'workflow':workflow}}}},
        accepted_state_version=1,recorded_at=now.isoformat().replace('+00:00','Z'),policy_source=hashes)
    refs={name:{'key':name,'hash':digest(parent)} for name in ('engineer','cpu','reviewer')}
    value=dict(parents=refs,sources=dict(contract_key='contract',approval_key='approval',**hashes),
        request=request,recorded_at=(now+timedelta(seconds=5400)).isoformat().replace('+00:00','Z'),
        accepted_state_version=2,budget_head_sha256=digest(head))
    objects={(BUDGET[0],name):parent for name in refs}
    objects.update({(GOALS[0],'contract'):{'contract':{'proposal':{}}},
        (AUTHORITY[0],'approval'):{'registry_witness':{}}})
    monkeypatch.setattr(domain,'budget_record',lambda *args:None)
    monkeypatch.setattr(domain,'budget_links',lambda *args:None)
    monkeypatch.setattr(domain,'derive',lambda *args:{})
    monkeypatch.setattr(domain,'derived_heads',lambda row:{BUDGET[1]:{account_key(scope(request)):head}})
    with pytest.raises(Conflict,match='window or quota exhausted'):
        domain.validate_links(value,lambda section,key:objects.get((section,key)))


@pytest.mark.parametrize('fault',['late_window','stop','physical_stop','valid'])
def test_final_sample_enforces_original_window_and_stop(fault):
    # Pure transaction harness, not Controller or Source authority.
    now=datetime(2026,10,11,tzinfo=timezone.utc);lease=object();effects=[]
    limits=dict(medium_sessions=6,high_sessions=2,controlled_seconds=3600,wall_seconds=5400)
    head=dict(envelope_sha256=digest('envelope'),approval_sha256=digest('approval'),
        first_engineer_entry='first',medium_sessions=1,high_sessions=1,
        controlled_seconds_charged=660,started_at=now.isoformat().replace('+00:00','Z'))
    workflow=dict(envelope_sha256=head['envelope_sha256'],limits=limits)
    attempt=dict(origin={'native_model':{'workflow':workflow}})
    runtime=SimpleNamespace(_leases={id(lease):attempt},_safety_freeze=False,_control_service=None,
        _unit_effect_check=lambda a:effects.append(a))
    @contextmanager
    def transaction(token,**callbacks):
        yield None,None,None
        callbacks['_before_commit']()
        final=now+timedelta(seconds=5400 if fault=='late_window' else 1)
        if fault=='stop':runtime._safety_freeze=True
        if fault=='physical_stop':attempt['physical_safety_freeze']=True
        callbacks['_after_final_sample'](final,1)
    service=object.__new__(ConditionAcceptanceService);service._active=None
    service._runtime=lambda:runtime;service.budget=SimpleNamespace(_fixture_runtime=runtime)
    service.controller=SimpleNamespace(token_transaction=transaction)
    value={'recorded_at':now.isoformat().replace('+00:00','Z'),
        'sources':{'expires_at':(now+timedelta(hours=2)).isoformat().replace('+00:00','Z')}}
    def run():
        with service._transaction(object()):
            service._active=SimpleNamespace(raw=canonical(value),workflow_raw=canonical(head),lease=lease,check=lambda:None)
    if fault=='valid':run();assert effects==[attempt]
    else:
        with pytest.raises(Conflict):run()
        assert not effects
    assert service._active is None


def test_condition_domain_cannot_be_written_by_generic_store(tmp_path):
    store=Store(tmp_path/'guarded');before=store.version()
    for event in (EVENT,'GENERIC'):
        with pytest.raises(PermissionError):
            store.transact_objects(event,'forged',[(SECTION,'')],lambda state:None)
    with pytest.raises(PermissionError):store.transact(EVENT,'legacy',lambda state:None)
    assert store.version()==before and not store.objects(SECTION)


@pytest.mark.parametrize('damage',['payload','producer','number'])
def test_original_event_sql_rejects_unbounded_or_noninteger_header(damage):
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE events(idempotency_key TEXT,seq,previous_state_version,new_state_version,object_version,event_type,producer,object_id,payload_sha256,input_versions,payload)')
    values=['key',1,0,1,1,EVENT,'hybrid-core','hash','hash','{}','{}']
    if damage=='payload':values[-1]='x'*4097
    elif damage=='producer':values[6]='x'*65
    else:values[1]='1'
    db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)',values)
    read=ReadBudget(db,4096)
    with pytest.raises(Conflict,match='bounded original header'):original_event(None,db,'key',read)
    assert read.remaining==4096  # Rejected in SQLite, not after fetching/JSON decoding.


def synthetic_reviewer(reviewer,lease,home,monkeypatch):
    """Synthetic test substitutions are deliberate; real Source remains mandatory in product."""
    attempt=reviewer._issued(lease)
    auth=home/'auth.json';auth.write_bytes(b'{"synthetic":"NOT_A_TOKEN"}');auth.chmod(0o600)
    reviewer.prepare_current_account_cache(lease);launch=reviewer.prepare_native_launch(lease)
    class NoG:
        def __init__(self,pipe):self.pipe=pipe
        def fileno(self):return self.pipe.fileno()
        @property
        def closed(self):return self.pipe.closed
        def close(self):return self.pipe.close()
        def write(self,data):
            assert data==b'G';raise PermissionError('TEST Reviewer G intercepted')
        def flush(self):pytest.fail('no model G')
    def no_model(argv,*args,**kwargs):
        assert argv[1:4]==['-B','-I','-S'] and argv[7]=='native_model'
        process=ACTUAL_POPEN(argv,*args,**kwargs);process.stdin=NoG(process.stdin);return process
    with monkeypatch.context() as guarded:
        guarded.setattr(subprocess,'Popen',no_model)
        with pytest.raises(PermissionError,match='TEST Reviewer G intercepted'):reviewer.start(lease,launch=launch)
    ack=_RuntimeStartedObservation(attempt['source'],canonical({'SYNTHETIC_SOURCE_NOT_QUALIFIED':True}))
    monkeypatch.setattr(reviewer.sources,'_runtime_started',lambda *a:ack);attempt['started_ack']=ack
    reviewer._write_phase(attempt,'STARTED_AS_OBSERVED',cleanup=True)
    review={'candidate_sha256':attempt['origin']['native_model']['candidate_sha256'],
        'verdict':'ACCEPT','reason':'SYNTHETIC review for local CAS only','findings':[]}
    message=canonical(review).decode()
    def usage(*args):
        if attempt['terminal'] is None:return None
        runtime={'phase':'FIXTURE_SCOPE_STOPPED','origin':attempt['origin'],'producer':attempt['producer_identity'],
            'native_model_handoff_attempted':True,'started_ack_sha256':digest(json.loads(ack.raw)),
            'terminal_proof_sha256':digest(attempt['terminal']),'wall_seconds':attempt['terminal']['wall_seconds']}
        value=publication(runtime);value.update(source_id=attempt['source'].id,
            model_session_id='SYNTHETIC_REVIEWER_SESSION',
            output_sha256='sha256:'+hashlib.sha256(message.encode()).hexdigest());return value
    def result(*args):
        counts=usage()
        if counts is None:return None
        return {'profile':'ORIGINAL_NATIVE_RESULT_V1','role':'Evaluator',
            'usage_publication_sha256':digest(counts),'message_utf8':message,
            'review':review,'condition_evidence_enabled':False}
    monkeypatch.setattr(reviewer.sources,'_runtime_usage_publication',usage)
    monkeypatch.setattr(reviewer.sources,'_runtime_result_publication',result)
    cap=NativeModelResult(attempt['source'],canonical({'SYNTHETIC_RESULT_NOT_QUALIFIED':True}))
    reviewer.sources._model_results[id(attempt['source'])]=(reviewer,lease,cap,cap.raw)
    def issued(owner,token,value):
        assert owner is reviewer and token is lease and value is cap;return cap
    monkeypatch.setattr(reviewer.sources,'_issued_native_result',issued)
    reviewer.stop_to_terminal(lease)
    assert reviewer._current(attempt)['status']=='SETTLED' and reviewer.pool.snapshot()['occupied']==0
    return attempt


@pytest.mark.parametrize('original',[{'data_mode':'live','project_id':'project_live','bound':condition_bound}],indirect=True)
def test_actual_cpu_synthetic_model_chain_condition_cas_and_replay(original,native_setup,monkeypatch):
    owner,bundle,token,obs,claim=original
    import tests.test_hybrid_a_workflow_cpu_runtime as parent_helpers
    def engineer_usage(runtime):
        value=publication(runtime);value['model_session_id']='SYNTHETIC_ENGINEER_SESSION';return value
    monkeypatch.setattr(parent_helpers,'publication',engineer_usage)
    lease=synthetic_engineer_parent(owner,bundle,token,obs,claim,native_setup[4],monkeypatch)
    cap=owner.prepare_workflow_cpu_input(lease)
    token=owner.controller.renew(token,'condition_cpu',expected_version=owner.store.version(),ttl_seconds=60)['token']
    cpu=owner.handoff_workflow_cpu(lease,cap,token=token);reviewer=None
    def actual_cpu_only(argv,*args,**kwargs):
        assert argv[0]=='/usr/bin/systemd-run' and 'hybrid_local_runner_service' in argv[-1]
        return ACTUAL_POPEN(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'Popen',actual_cpu_only)
    try:
        output=cpu.execute_workflow_cpu(token);assert output['machine_acceptance']['status']=='PASS'
        task=cpu._workflow_cpu_sequence['lease'];review=cpu.prepare_workflow_reviewer_input(task)
        reviewer=cpu.handoff_workflow_reviewer(task,review,token=token)
        token=reviewer.controller.renew(token,'condition_review',expected_version=reviewer.store.version(),ttl_seconds=60)['token']
        bundle,obs=reviewer.prepare_workflow_reviewer_plan(token)
        grant=reviewer.issue_workflow_reviewer_grant(bundle,token,obs)
        claim=reviewer.pool.claim(reviewer.membership,expected_version=reviewer.pool.snapshot()['version'],request_key='condition_review_claim',seconds=60)
        lease=reviewer.register(bundle,token,obs,claim,request_key='condition_review_register',scenario='native_model',native_model_grant=grant)
        attempt=synthetic_reviewer(reviewer,lease,native_setup[4],monkeypatch)
        monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('acceptance cannot execute'))
        token=reviewer.controller.renew(token,'condition_accept',expected_version=reviewer.store.version(),ttl_seconds=60)['token']
        version=reviewer.store.version();pool_version=reviewer.pool.snapshot()['version']
        with pytest.raises(Conflict,match='stale expected'):
            reviewer.accept_workflow_conditions(lease,token,idempotency_key='accept',expected_state_version=version-1)
        assert reviewer.store.version()==version
        real_transaction=reviewer.controller.token_transaction
        @contextmanager
        def lost_commit_return(*args,**kwargs):
            with real_transaction(*args,**kwargs) as context:yield context
            raise OSError('TEST lost committed condition return')
        with monkeypatch.context() as lost:
            lost.setattr(reviewer.controller,'token_transaction',lost_commit_return)
            with pytest.raises(OSError,match='lost committed condition'):
                reviewer.accept_workflow_conditions(lease,token,idempotency_key='accept',expected_state_version=version)
        result=reviewer.accept_workflow_conditions(lease,token,idempotency_key='accept',expected_state_version=version)
        fact=result['fact'];assert result['duplicate']
        assert fact['required_conditions_passed']==2 and len(fact['evidence'])==2
        assert not fact['goal_completed'] and not fact['dispatch_enabled']
        assert all(row['verdict']=='PASS' and row['implementer_session_id']!=row['reviewer_session_id'] for row in fact['evidence'])
        assert reviewer.store.version()==version+1 and reviewer.pool.snapshot()['version']==pool_version
        repeated=reviewer.accept_workflow_conditions(lease,token,idempotency_key='accept',expected_state_version=version)
        assert repeated['duplicate'] and repeated['fact']==fact
        assert repeated['current_activation']=='NOT_RECHECKED' and reviewer.store.version()==version+1
        with pytest.raises(Conflict,match='key reused'):
            reviewer.accept_workflow_conditions(lease,token,idempotency_key='other',expected_state_version=version)
        service=reviewer.store._hybrid_a_condition_service
        with reviewer.store.read_connection() as db:
            db.execute('BEGIN');read=ReadBudget(db,64*1024**2)
            parents=service._graph(db,read,attempt['entries']['FIXTURE_SCOPE_STOPPED'])
            loaded=reviewer.budget._load(db,attempt['entries']['FIXTURE_SCOPE_STOPPED']['request']['goal_ref'],read)
            proposal=loaded['record']['contract']['proposal'];config=json.loads(reviewer.plans.registry._raw)
        for fault in ('same_session','missing_session','unknown','revise','candidate','foreign_source'):
            bad=copy.deepcopy(parents['reviewer']);runtime=bad['request']['fixture_runtime']
            if fault=='same_session':runtime['native_model_usage']['model_session_id']='SYNTHETIC_ENGINEER_SESSION'
            elif fault=='missing_session':runtime['native_model_usage'].pop('model_session_id')
            elif fault=='unknown':bad['decision']='UNKNOWN'
            elif fault=='revise':runtime['native_model_result']['review']['verdict']='REVISE'
            elif fault=='candidate':runtime['origin']['native_model']['candidate_sha256']=digest('wrong')
            else:runtime['native_model_usage']['source_id']=parents['engineer']['request']['fixture_runtime']['native_model_usage']['source_id']
            model_result=runtime['native_model_result']
            if fault=='revise':
                model_result['message_utf8']=canonical(model_result['review']).decode()
                runtime['native_model_usage']['output_sha256']='sha256:'+hashlib.sha256(model_result['message_utf8'].encode()).hexdigest()
            model_result['usage_publication_sha256']=digest(runtime['native_model_usage'])
            with pytest.raises(Conflict):derive(proposal,config,parents['cpu'],parents['engineer'],bad)
        reviewer.store.snapshot();assert reviewer.store.recover()==reviewer.store.audit()==reviewer.store.replay()
    finally:
        if reviewer is not None and reviewer._live:reviewer.shutdown()
        if cpu._live:cpu.shutdown()
