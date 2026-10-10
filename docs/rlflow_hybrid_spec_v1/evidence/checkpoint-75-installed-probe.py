"""Installed SDK consumer: isolated preparation, real TCP, human DRAFT, restart."""
import json,os,socket,subprocess,sys,threading,time
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.request import Request,build_opener,ProxyHandler,HTTPCookieProcessor
from urllib.error import HTTPError
import uvicorn
import rlflow.hybrid_core_host as host_module
from rlflow.hybrid_core_host import CoreRegistration,create_core_host
from rlflow.hybrid_registry import Registry
from rlflow.hybrid_goals import digest
from rlflow.store import Store
from rlflow.observation import enable
from rlflow.web_auth import AuthStore,Credential,Principal
from rlflow.agent_client import _NoRedirect
BASE=Path(sys.argv[1]).resolve();SITE=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else BASE/'site'
assert str(host_module.__file__).startswith(str(SITE)+'/')
assert not any(name=='tests' or name.startswith('tests.') for name in sys.modules)
os.umask(0o077)
state=BASE/'state';state.mkdir(mode=0o700)
# Explicit disposable preparation, not part of serve or a production migration.
store=Store(state);epoch=enable(store,'project_fixture',data_mode='fixture')
catalog={'schema_version':'1.0','project_id':'project_fixture','data_mode':'fixture',
 'tools':{'cpu_exec':{'adapter':'controlled_cpu','definition':{'version':'fixture_v1'}}},
 'commands':{'fixture_test':{'tool_id':'cpu_exec','argv':['fixture-python','-m','pytest'],
 'parameter_schema':{'type':'object','additionalProperties':False},'network':'none','allowed_hosts':[]}},
 'runtime_profile':{'adapter':'fixture','capabilities':[]},'resource_profile':{'enforcement':'UNKNOWN'},
 'datasets':{},'evaluation_rules':{'fixture_rule':{'definition':{'method':'fixed_fixture_tests'},'requires_datasets':False}},
 'project_policy':{'network_access':'none','allowed_hosts':[],
 'configuration':{'protected_control':'external','execution_enabled':False}}}
registry=Registry(catalog)
registration=CoreRegistration(state,'project_fixture','fixture',epoch,registry)
phrase='isolated-fixture-only-passphrase-never-output'
credential=Credential.create(Principal('operator','human',{'operator'},{'project_fixture'}),phrase)
agent=Principal('client_agent','agent',{'viewer'},{'project_fixture'})
target=BASE/'target';(target/'.rlflow').mkdir(parents=True,mode=0o700)
sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',0))
origin='http://127.0.0.1:'+str(sock.getsockname()[1])
(target/'.rlflow/project.yaml').write_text(json.dumps({'schema_version':'1.0','project_id':'project_fixture','control_origin':origin}))
proposal={'schema_version':'1.1','data_mode':'fixture','project_id':'project_fixture','goal_id':'goal_fixture_01',
 'contract_version':1,'objective':'Disposable non-executing DRAFT and restart proof','goal_kind':'engineering',
 'global_conditions':[{'id':'C1','description':'Fixed tests pass','required':True,
 'verification':{'method':'deterministic','rule':'Registered fixed tests exit zero','evidence_required':['test_result']}},
 {'id':'C2','description':'Independent review passes','required':True,
 'verification':{'method':'independent_review','rule':'Different reviewer and same candidate','evidence_required':['review_result']}}],
 'scope':{'writable_paths':['src/','tests/'],'protected_paths':['.rlflow/','fixtures/acceptance/'],
 'allowed_command_templates':['fixture_test'],'network_access':'none','allowed_hosts':[]},
 'budget':{'model_sessions':0,'model_input_tokens':0,'model_output_tokens':0,'model_token_enforcement':'hard_required',
 'gpu_device_seconds':0,'experiment_starts':0,'experiment_retries':0,'wall_seconds':300,'finalization_reserve_fraction':0.2},
 'stop_rules':['Reject every real model or GPU invocation','Fixture never enters live execution'],
 'risk':'low','approval_status':'UNAPPROVED','allowed_tools':['cpu_exec'],'registry_bindings':registry.bindings,
 'evaluation_data':{'mode':'EXPLICIT_NONE','datasets':[],
 'evaluation_rule':{'id':'fixture_rule','version_hash':digest(catalog['evaluation_rules']['fixture_rule'])}}}
(target/'proposal.json').write_text(json.dumps(proposal))
def cli(token,*args,expected=0):
 env={**os.environ,'PYTHONPATH':str(SITE),'RLFLOW_CONTROL_ORIGIN':origin,'RLFLOW_REQUEST_TOKEN':token}
 result=subprocess.run([str(SITE/'bin/rlflow'),'client',*args],cwd=target,env=env,capture_output=True,text=True,timeout=10)
 assert token not in result.stdout+result.stderr and phrase not in result.stdout+result.stderr
 assert result.returncode==expected, 'installed console returned unexpected status'
 return json.loads(result.stdout) if expected==0 else result.stderr
def start(auth,current_sock):
 app=create_core_host([registration],auth,origin=origin)
 server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,lifespan='on'))
 thread=threading.Thread(target=server.run,kwargs={'sockets':[current_sock]},daemon=True);thread.start()
 deadline=time.monotonic()+5
 while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
 assert server.started,'original lifespan did not start'
 return server,thread
def stop(server,thread,current_sock):
 server.should_exit=True;thread.join(5);current_sock.close()
 assert not thread.is_alive(),'owned server did not finish original shutdown'
auth=AuthStore([credential]);token,_=auth.issue_request_token(agent)
server,thread=start(auth,sock)
try:
 discovery=cli(token,'describe')
 assert discovery['execution_enabled'] is False and store.version()==0
 saved=cli(token,'submit-goal','--proposal',str(target/'proposal.json'),'--key','installed_restart')
 assert saved['status']=='AWAITING_HUMAN' and store.version()==0
 opener=build_opener(ProxyHandler({}),_NoRedirect(),HTTPCookieProcessor(CookieJar()))
 def post(path,value,csrf=None):
  headers={'Origin':origin,'Content-Type':'application/json'}
  if csrf:headers['X-CSRF-Token']=csrf
  with opener.open(Request(origin+path,data=json.dumps(value).encode(),headers=headers),timeout=5) as response:
   return json.load(response)
 login=post('/api/v1/login',{'principal_id':'operator','passphrase':phrase})
 accepted=post('/api/v1/projects/project_fixture/agent-requests/'+saved['request_id']+'/forward',
  {'request_hash':saved['request_hash'],'expected_version':0},login['csrf_token'])
 assert accepted['status']=='ADOPTED' and store.version()==1
 first=cli(token,'report','--request',saved['request_id'])
 assert first['status']=='ADOPTED' and first['result']['result']['state']=='DRAFT'
finally:stop(server,thread,sock)
renewed=AuthStore([credential]);new_token,_=renewed.issue_request_token(agent)
second_sock=socket.socket();second_sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
second_sock.bind(('127.0.0.1',int(origin.rsplit(':',1)[1])))
server,thread=start(renewed,second_sock)
try:
 cli(token,'report','--request',saved['request_id'],expected=2)
 try:
  opener.open(Request(origin+'/api/v1/projects/project_fixture/agent-requests/'+saved['request_id'],
   headers={'Authorization':'Bearer '+token,'Origin':origin}),timeout=5)
 except HTTPError as error:
  assert error.code==401
  error.close()
 else:raise AssertionError('old token accepted after original Auth restart')
 final=cli(new_token,'report','--request',saved['request_id'])
 assert final==first and store.version()==1
 assert not any(store.objects(section) for section in ('sessions','jobs','tasks','approvals'))
 assert not (target/'runtime').exists()
 assert not any(name=='tests' or name.startswith('tests.') for name in sys.modules)
 print(json.dumps({'installed_only_server':True,'installed_console':True,'tests_imported':False,
 'real_TCP':True,'human_HTTP_forward':'ADOPTED','restart_report':'same_original_ADOPTED',
 'old_token_HTTP':401,'Core_version':1,'workers':0,'model_calls':0,'GPU_starts':0,
 'runtime_adoption':False,'Goal_completed':False}),flush=True)
finally:stop(server,thread,second_sock)
