"""Explicit disposable installed fixture; never a live project launcher.

Run as python -m rlflow.isolated_finite_example outside checkout with installed dependencies, native CLI/version and
real model metadata already present. --approve-isolated-fixed-fixture consents
ONLY to existing model-free CPU profiles. No test imports, fake clocks or probes.
"""
import argparse,hashlib,json,os,secrets,socket,subprocess,threading,time
from contextlib import contextmanager
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request,build_opener,ProxyHandler,HTTPCookieProcessor
import uvicorn
import rlflow
from rlflow.agent_client import _NoRedirect
from rlflow import isolation
from rlflow.execution_adapter import CodexExecAdapter
from rlflow.hybrid_authority import ApprovalService
from rlflow.hybrid_budget import zero
from rlflow.hybrid_budget_ledger import reservation_key
from rlflow.hybrid_budget_service import BudgetService
from rlflow.hybrid_controller_service import ControllerService
from rlflow.hybrid_drafts import DraftService
from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService
from rlflow.hybrid_goals import digest,head_key
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_preparation import intent_key
from rlflow.hybrid_preparation_service import PreparationService
from rlflow.hybrid_snapshot import SnapshotBuilder
from rlflow.hybrid_working_copy import WorkingCopyOwner
from rlflow.hybrid_workspace_service import WorkspaceService
from rlflow.hybrid_working_plan_service import WorkingPlanService
from rlflow.hybrid_fixture_runtime import FixtureRuntimeOwner
from rlflow.hybrid_host_pool import HostPoolOwner
from rlflow.hybrid_host_execution import HostExecutionService
from rlflow.hybrid_cpu_trial import registration as cpu_registration
from rlflow.hybrid_engineering_patch import registration as patch_registration,BEFORE,AFTER
from rlflow.hybrid_cpu_execution_unit import CpuTrialExecutionUnit
from rlflow.hybrid_engineering_execution_unit import EngineeringExecutionUnit
from rlflow.hybrid_cpu_assessment_service import CpuAssessmentService
from rlflow.hybrid_candidate_output_service import CandidateOutputService
from rlflow.hybrid_cpu_unit_control import CpuUnitControlService
from rlflow.hybrid_engineering_unit_control import EngineeringUnitControlService
from rlflow.hybrid_finite_host_app import create_finite_host_app
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
from rlflow.web_auth import AuthStore,Credential,Principal

@contextmanager
def _replace_methods(rows):
 originals=[]
 try:
  for owner,name,method in rows:
   originals.append((owner,name,getattr(owner,name)));setattr(owner,name,method)
  yield
 finally:
  for owner,name,method in reversed(originals):setattr(owner,name,method)

def profile(project,kind):
 package=Path(rlflow.__file__).resolve().parent
 names=('hybrid_runtime_fixture.py','hybrid_cpu_trial.py') if kind=='cpu_trial' else ('hybrid_engineering_fixture.py','hybrid_engineering_patch.py')
 pins=['sha256:'+hashlib.sha256((package/name).read_bytes()).hexdigest() for name in names]
 registered=(cpu_registration if kind=='cpu_trial' else patch_registration)(*pins)
 config={'schema_version':'1.0','project_id':project,'data_mode':'fixture',
  'tools':{kind:registered['tool']},'commands':{kind:registered['command']},
  'runtime_profile':{'adapter':'codex-exec','model':'gpt-6.1-sol','effort':'medium',
   'codex_version':isolation.PINNED_VERSION,'native_subagents':False,'cpu_network':'none',
   'memory_bytes':128*1024**2,'command_seconds':10},
  'resource_profile':registered['resources'],'datasets':{},
  'evaluation_rules':{kind+'_rule':registered['rule']},
  'project_policy':{'network_access':'none','allowed_hosts':[],
   'configuration':{'protected_control':'external','execution_enabled':False}}}
 registry=Registry(config)
 proposal={'schema_version':'1.1','project_id':project,'data_mode':'fixture','goal_id':'isolated_goal',
  'contract_version':1,'objective':'Fixed seeded PI measurement' if kind=='cpu_trial' else 'Fixed add subtraction repair',
  'goal_kind':'research' if kind=='cpu_trial' else 'engineering',
  'global_conditions':[{'id':'C1','description':'Registered fixed verification passes','required':True,
   'verification':{'method':'deterministic','rule':'Exact registered result','evidence_required':['test_result']}},
   {'id':'C2','description':'Independent product review passes','required':True,
   'verification':{'method':'independent_review','rule':'Separate read-only reviewer same candidate','evidence_required':['review_result']}}],
  'scope':{'writable_paths':['module/'],'protected_paths':['.rlflow/','fixtures/acceptance/'],
   'allowed_command_templates':[kind],'network_access':'none','allowed_hosts':[]},
  'budget':{'model_sessions':0,'model_input_tokens':0,'model_output_tokens':0,
   'model_token_enforcement':'hard_required','gpu_device_seconds':0,'experiment_starts':3 if kind=='cpu_trial' else 0,
   'experiment_retries':0,'wall_seconds':300,'finalization_reserve_fraction':0.2},
  'stop_rules':['Reject every model and GPU invocation','Only original fixed fixture profiles'],
  'risk':'low','approval_status':'UNAPPROVED','allowed_tools':[kind],'registry_bindings':registry.bindings,
  'evaluation_data':{'mode':'EXPLICIT_NONE','datasets':[],
   'evaluation_rule':{'id':kind+'_rule','version_hash':digest(registered['rule'])}}}
 return registry,proposal

def close_fixture(host,server,thread,sock,runtimes,working_owners,pool):
 """Latch all original units before drain; independently attempt every owner."""
 errors=[]
 def attempt(action):
  try:return action()
  except Exception as error:errors.append(error)
 if host is not None:
  rows=attempt(host.cancel_all)
  if rows is not None and any(row['error'] or row['result']['cleanup_error'] for row in rows):
   errors.append(RuntimeError('original unit cleanup remains UNKNOWN'))
 if server is not None:
  server.should_exit=True
  attempt(lambda:thread.join(10))
  if thread.is_alive():errors.append(RuntimeError('original server drain incomplete'))
 attempt(sock.close)
 for runtime in reversed(runtimes):
  if runtime._live:
   attempt(runtime.shutdown)
   if runtime._live:attempt(runtime.shutdown_safety)
 for working in reversed(working_owners):
  for slot in tuple(working._issued.values()):
   attempt(lambda slot=slot:working.close_pre_runtime(slot['observation']))
  for witness in tuple(working._closed_witnesses.values()):
   attempt(lambda witness=witness:working.retire_closed_witness(witness))
 if pool._live:attempt(pool.shutdown)
 return errors


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--parent',type=Path,required=True)
 parser.add_argument('--approve-isolated-fixed-fixture',action='store_true')
 parser.add_argument('--verify-original-reconciliation',action='store_true',
  help='Inject bounded fixture-only lost machine stage; explicitly reconcile the original HTTP command')
 args=parser.parse_args()
 if not args.approve_isolated_fixed_fixture:parser.error('explicit fixture-only consent required')
 parent=args.parent.resolve(strict=True)
 if parent.is_symlink() or parent.stat().st_mode & 0o077:parser.error('existing private isolated parent required')
 assert not any(n=='tests' or n.startswith('tests.') for n in __import__('sys').modules)
 pool=HostPoolOwner.create_fixture(parent);runtimes=[];working_owners=[];units=[];controls=[];server=None;thread=None;host=None
 sock=socket.socket();sock.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(sock.getsockname()[1])
 phrase=secrets.token_urlsafe(40)
 projects={'isolated_cpu','isolated_engineering'}
 auth=AuthStore([Credential.create(Principal('fixture_operator','human',{'operator','approver'},projects),phrase)])
 human,access=auth.login('fixture_operator',phrase);authority={'token':human,'csrf':access.csrf,'origin':origin}
 try:
  owners=[];prepared=[]
  for project,kind in [('isolated_cpu','cpu_trial'),('isolated_engineering','engineering_patch')]:
   registered_parent=pool.projects_root/project;registered_parent.mkdir(mode=0o700)
   builder=FixtureMaterialBuilder(registered_parent,project_id=project)
   installation=FixtureInstallationService(builder);material=builder.prepare()
   installation.persist_intent(material);installation.publish(material)
   store=builder.store;registry,proposal=profile(project,kind)
   draft=DraftService(store,auth,project_id=project,data_mode='fixture',origin=origin)
   approval=ApprovalService(store,auth,registry,project_id=project,data_mode='fixture',origin=origin)
   draft.submit(proposal,**authority,idempotency_key='explicit_fixture_draft',expected_revision=0,expected_state_version=store.version())
   confirmation=approval.prepare(**authority,goal_id=proposal['goal_id'],ttl_seconds=proposal['budget']['wall_seconds'])['confirmation']
   print(json.dumps({'fixture_project':project,'proposal':proposal,'approval_scope_hash':confirmation['scope_hash'],
    'consent_ttl_seconds':confirmation['ttl_seconds']}),flush=True)
   print('Type APPROVE '+confirmation['scope_hash']+' to approve ONLY this disposable fixed fixture:',flush=True)
   if __import__('sys').stdin.readline(90).strip()!='APPROVE '+confirmation['scope_hash']:
    raise PermissionError('original scope was not explicitly confirmed; no execution')
   approval.approve(confirmation,**authority,idempotency_key='explicit_fixture_approve')
   source=builder._roots['source'];(source/'module').mkdir(mode=0o700)
   (source/'module/source.py').write_bytes(BEFORE if kind=='engineering_patch' else b'print(42)\n')
   prep_root=builder._roots['bootstrap']/'preparation';prep_root.mkdir(mode=0o700)
   adapter=CodexExecAdapter(registry,prep_root)
   snapshots=SnapshotBuilder(source,['module/source.py'],builder._roots['snapshots'])
   prep=PreparationService(store,registry,snapshots,adapter,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
   goal=head_key(project,'fixture',proposal['goal_id'])
   request={'project_id':project,'data_mode':'fixture','goal_ref':goal,'idempotency_key':'prepare',
    'role':'Engineer','context':{'text':proposal['objective']}}
   prep.prepare(request)
   prepared.append((project,kind,builder,installation,material,store,registry,snapshots,prep,goal,request))
  # No short controller/workspace lease is held while another project waits
  # for human approval, installation copy or native preparation.
  for project,kind,builder,installation,material,store,registry,snapshots,prep,goal,request in prepared:
   controller=ControllerService(store,registry,project_id=project,data_mode='fixture',store_epoch=builder.store_epoch)
   token=controller.acquire('controller',expected_version=store.version(),ttl_seconds=60)['token']
   budget=BudgetService(store,registry,controller,prep)
   reserve={'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
    'idempotency_key':'reserve','expected_state_version':store.version(),'action':'RESERVE',
    'preparation_intent_key':intent_key(request),'amount':{**zero(),'wall_seconds':10,'experiment_starts':int(kind=='cpu_trial')},'purpose':'EXECUTION'}
   budget.record(reserve,token)
   working=WorkingCopyOwner(snapshots,builder._roots['working']);working_owners.append(working)
   workspace=WorkspaceService(store,registry,controller,prep,budget,working)
   observation=workspace.stage(intent_key(request),ttl_seconds=60);observed=json.loads(observation.raw)
   workspace.record({'project_id':project,'data_mode':'fixture','goal_ref':goal,'store_epoch':builder.store_epoch,
    'idempotency_key':'workspace','expected_state_version':store.version(),'expected_workspace_revision':0,
    'workspace_id':observed['workspace_id'],'reservation_id':reservation_key(reserve),'operation':'acquire','ttl_seconds':60},token,observation)
   plans=WorkingPlanService(workspace,installation,material)
   membership=pool.register_project(installation,material,expected_version=pool.snapshot()['version'])
   runtime=FixtureRuntimeOwner(pool,membership,plans);runtimes.append(runtime)
   bundle=plans.prepare_plan(token,observation,'installed_plan')
   plans.persist_intent(bundle,token,observation,expected_version=store.version())
   plans.publish(bundle,token,observation,expected_version=store.version())
   owners.append((kind,runtime,bundle,token,observation))
  host=HostExecutionService(pool)
  for kind,runtime,bundle,token,observation in owners:
   claim=pool.claim(runtime.membership,expected_version=pool.snapshot()['version'],request_key='claim',seconds=60)
   grant=(runtime.issue_cpu_trial_grant if kind=='cpu_trial' else runtime.issue_engineering_patch_grant)(bundle,token,observation)
   lease=runtime.register(bundle,token,observation,claim,request_key='lease',scenario=kind,
    **({'cpu_grant':grant} if kind=='cpu_trial' else {'engineering_grant':grant}))
   unit=(CpuTrialExecutionUnit(runtime,lease,CpuAssessmentService(runtime)) if kind=='cpu_trial'
    else EngineeringExecutionUnit(runtime,lease,CandidateOutputService(runtime)))
   host.bind_unit(unit);units.append(unit)
   controls.append((CpuUnitControlService if kind=='cpu_trial' else EngineeringUnitControlService)(host,lease,auth,origin=origin))
  app=create_finite_host_app(host,controls,auth,origin=origin,agent_requests=True)
  server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,lifespan='on'))
  thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
  deadline=time.monotonic()+5
  while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
  assert server.started
  opener=build_opener(ProxyHandler({}),_NoRedirect(),HTTPCookieProcessor(CookieJar()))
  def post(path,value,csrf=None,key=None):
   headers={'Origin':origin,'Content-Type':'application/json'}
   if csrf:headers['X-CSRF-Token']=csrf
   if key:headers['Idempotency-Key']=key
   with opener.open(Request(origin+path,data=json.dumps(value).encode(),headers=headers),timeout=60) as reply:
    return reply.status,json.load(reply)
  _,login=post('/api/v1/login',{'principal_id':'fixture_operator','passphrase':phrase})
  csrf=login['csrf_token']
  request_token,_=auth.issue_request_token(Principal('fixture_report_agent','agent',{'viewer'},projects))
  site=Path(rlflow.__file__).resolve().parent.parent
  results=[];reconciliations=[]
  for index,service in enumerate(controls):
   cpu=index==0;kind='CPU_TRIAL' if cpu else 'ENGINEERING'
   endpoint='cpu-unit' if cpu else 'engineering-unit'
   route='/api/v1/projects/'+service.project_id+'/'+endpoint+'/commands'
   start_body={'action':'START_FIXED_CPU' if cpu else 'START_FIXED_ENGINEERING','task_id':service.task_id,
    'expected_state_version':service.store.version()}
   if args.verify_original_reconciliation:
    unit=units[index];method='decide' if cpu else 'accept_machine';original=getattr(unit.output,method)
    launches=[];writes=[];spawn=subprocess.Popen;pwrite=os.pwrite;faults=[]
    def counted_spawn(*a,**kw):launches.append(a[0]);return spawn(*a,**kw)
    def counted_write(*a,**kw):writes.append((a[1],a[2]));return pwrite(*a,**kw)
    def missing_return(*a,**kw):
     if not cpu:original(*a,**kw)
     faults.append('BEFORE_DECISION_WRITE' if cpu else 'AFTER_MACHINE_COMMIT')
     raise OSError('explicit disposable fixture machine-stage return failure')
    with _replace_methods([(unit.output,method,missing_return),(subprocess,'Popen',counted_spawn),(os,'pwrite',counted_write)]):
     code,result=post(route,start_body,csrf,'actual_fixed_start')
    assert code==202 and faults and unit._last is None
    assert len(launches)==1 and len(writes)==(0 if cpu else 1)
    before=service.store.version();other=controls[1-index].store.audit()
    duplicate_code,duplicate=post(route,start_body,csrf,'actual_fixed_start')
    assert duplicate_code==202 and duplicate['duplicate'] and unit._last is None and service.store.version()==before
    def forbidden(*a,**kw):raise AssertionError('original reconciliation must never repeat execution/effect')
    with _replace_methods([(host,'run',forbidden),(unit.runtime,'start',forbidden),
      (unit.runtime.sources,'_runtime_release',forbidden),(unit,'_collect',forbidden),
      (subprocess,'Popen',forbidden),(os,'pwrite',forbidden)]):
     recovery_code,recovered=post(route+'/'+result['command_id']+'/reconcile',start_body,csrf,'actual_fixed_start')
     assert recovery_code==200 and recovered['result_fact'] is not None
     assert recovered['result']['status']==('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW' if cpu else 'MACHINE_ACCEPTED_PENDING_REVIEW')
     assert not recovered['new_dispatch_enabled'] and not recovered['automatic_effect_retry_enabled']
     assert service.store.version()==before+int(cpu)
     repeat_code,again=post(route+'/'+result['command_id']+'/reconcile',start_body,csrf,'actual_fixed_start')
     assert repeat_code==200 and again==recovered and service.store.version()==before+int(cpu)
    assert controls[1-index].store.audit()==other
    reconciliations.append({'kind':kind,'fault':faults[0],'worker_starts':len(launches),
     'pwrites':len(writes),'new_machine_events':int(cpu),'repeat_unchanged':True,'result_fact':recovered['result_fact']})
   else:
    code,result=post(route,start_body,csrf,'actual_fixed_start')
   assert code==202
   reader=(CpuAssessmentReader if cpu else CandidateOutputReader)(service.store,service.runtime.plans.registry,
    project_id=service.project_id,store_epoch=service.store_epoch)
   rows=(reader.assessments() if cpu else reader.outputs())['items'];assert rows
   source_id=max(rows,key=lambda row:row['recorded_at_state_version'])['id']
   target=pool.projects_root/('client_'+str(index));(target/'.rlflow').mkdir(parents=True,mode=0o700)
   (target/'.rlflow/project.yaml').write_text(json.dumps({'schema_version':'1.0','project_id':service.project_id,'control_origin':origin}))
   env={**os.environ,'PYTHONPATH':str(site),'RLFLOW_CONTROL_ORIGIN':origin,'RLFLOW_REQUEST_TOKEN':request_token}
   before=service.store.version()
   call=subprocess.run([str(site/'bin/rlflow'),'client','execution-report','--kind',kind,'--source',source_id],
    cwd=target,env=env,capture_output=True,text=True,timeout=10)
   assert call.returncode==0 and request_token not in call.stdout+call.stderr
   report=json.loads(call.stdout);assert service.store.version()==before
   assert report['source']['raw_item_count']==(384 if cpu else 3)
   assert report['source']['machine_case_count']==(0 if cpu else 21)
   assert report['source']['machine_status']==('MACHINE_VERIFIED' if cpu else 'MACHINE_ACCEPTED_PENDING_REVIEW')
   assert report['goal_completed'] is False and 'MISSING_INDEPENDENT_REVIEW' in report['blockers']
   results.append({'kind':kind,'raw':report['source']['raw_item_count'],'cases':report['source']['machine_case_count']})
  code,stopped=post('/api/v1/finite-host/commands',{'action':'CANCEL_ORIGINAL_FINITE_UNITS'},csrf,'original_stop')
  assert code==202 and stopped['status']=='ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'
  assert pool.snapshot()['occupied']==0 and all(unit._cancelled.is_set() for unit in units)
  for unit in units:
   attempt=unit.runtime._issued(unit.lease)
   source=unit.runtime.sources._issued(attempt['source'])
   assert source['producer'].returncode is not None and all(fd is None for fd in source['fds'].values())
   slot=pool._claim_slots[id(attempt['claim'])]
   assert slot.closed and all(fd is None for fd in slot.fds)
  material=units[1].output._rows[id(units[1].lease)]['material']
  assert material.write_entered and material.fd is None
  assert (material.root/'module/source.py').read_bytes()==AFTER
  assert (units[1].runtime.workspace.preparation.builder.source/'module/source.py').read_bytes()==BEFORE
  assert units[1].runtime._engineering_grants[id(units[1].runtime._issued(units[1].lease)['engineering_grant'])]['fd'] is None
  assert not any(n=='tests' or n.startswith('tests.') for n in __import__('sys').modules)
  print(json.dumps({'installed_package':str(site),'tests_imported':False,'real_clocks':True,
   'real_native_version_only':True,'results':results,'original_reconciliations':reconciliations,'original_STOP':True,'pool_occupied':0,
   'model_calls':0,'GPU_starts':0,'product_review':'NOT_PERFORMED','Goal_completed':False}),flush=True)
 finally:
  primary=__import__('sys').exception()
  errors=close_fixture(host,server,thread,sock,runtimes,working_owners,pool)
  if errors:
   if primary is not None:primary.add_note('independent fixture cleanup issues: '+','.join(type(e).__name__ for e in errors))
   else:raise RuntimeError('fixture cleanup incomplete; retain original owners and UNKNOWN state') from errors[0]

if __name__=='__main__':main()
