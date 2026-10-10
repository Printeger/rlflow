"""Installed consumer of immutable checkpoint76 business history; never RUN."""
import hashlib,json,os,secrets,socket,sqlite3,subprocess,sys,threading,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
import uvicorn
import rlflow
from rlflow.isolated_finite_example import profile
from rlflow.hybrid_cold_result_host import ColdResultRegistration,create_cold_result_host
from rlflow.hybrid_cpu_assessment_reads import CpuAssessmentReader
from rlflow.hybrid_candidate_output_reads import CandidateOutputReader
from rlflow.web_auth import AuthStore,Principal
from rlflow.store import Store,canonical

ROOTS=[Path('/tmp/rlflow-cp76-accepted-IwQiuo/rlflow-host-fixture-l9mb_5dg/projects/isolated_cpu/rlflow-guarded-fixture-5327uli7/store'),
 Path('/tmp/rlflow-cp76-accepted-IwQiuo/rlflow-host-fixture-l9mb_5dg/projects/isolated_engineering/rlflow-guarded-fixture-mbvmkqer/store')]
EPOCHS=['store_e4be72b76cef4dc699c8fe49575b7046','store_b27645d1126446489bd0a546e0dc320d']
PROJECTS=['isolated_cpu','isolated_engineering'];KINDS=['CPU_TRIAL','ENGINEERING']

def registrations():
 return [ColdResultRegistration(root,project,epoch,profile(project,scenario)[0],kind)
  for root,project,epoch,scenario,kind in zip(ROOTS,PROJECTS,EPOCHS,['cpu_trial','engineering_patch'],KINDS)]

def business(root):
 with sqlite3.connect((root/'runtime/research.db').as_uri()+'?mode=ro',uri=True) as db:
  # Complete current bounded fixture business tables, excluding SQLite sidecars.
  rows={table:db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
   for table in ('events','projection','projection_meta','observation_meta','observation_events','observation_projection','observation_counters','snapshot_due')}
 return hashlib.sha256(canonical(rows)).hexdigest()

def serve():
 # Read-only server must not start any child process, even accidentally.
 def audit(event,args):
  if event in ('subprocess.Popen','os.system','os.posix_spawn'):raise RuntimeError('cold host attempted subprocess')
 sys.addaudithook(audit)
 sock=socket.socket();sock.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(sock.getsockname()[1])
 auth=AuthStore([])
 token,_=auth.issue_request_token(Principal('cold_reader','agent',{'viewer'},set(PROJECTS)))
 limited,_=auth.issue_request_token(Principal('limited_reader','agent',{'viewer'},{PROJECTS[0]}))
 app=create_cold_result_host(registrations(),auth,origin=origin)
 server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,lifespan='on'))
 thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
 deadline=time.monotonic()+5
 while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
 assert server.started
 # Parent consumes this pipe privately. Never forwarded to tool stdout/log.
 print(json.dumps({'origin':origin,'token':token,'limited':limited}),flush=True)
 try:assert sys.stdin.readline().strip()=='CLOSE'
 finally:
  server.should_exit=True;thread.join(10);sock.close();assert not thread.is_alive()
  assert not any(name=='tests' or name.startswith('tests.') for name in sys.modules)

def main():
 before=[business(root) for root in ROOTS];sources=[]
 for row in registrations():
  store=Store.attach_existing(row.root,project_id=row.project_id,data_mode='fixture')
  reader=(CpuAssessmentReader if row.kind=='CPU_TRIAL' else CandidateOutputReader)(store,row.registry,
   project_id=row.project_id,store_epoch=row.store_epoch)
  rows=(reader.assessments() if row.kind=='CPU_TRIAL' else reader.outputs())['items']
  sources.append(max(rows,key=lambda item:item['recorded_at_state_version'])['id'])
 opener=build_opener(ProxyHandler({}));old=None;reports=[];children=[]
 def get(endpoint,token,origin):
  try:
   with opener.open(Request(origin+endpoint,headers={'Authorization':'Bearer '+token}),timeout=10) as reply:
    return reply.status,json.load(reply)
  except HTTPError as error:return error.code,None
 try:
  for phase in range(2):
   child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve'],stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
   children.append(child);ready=json.loads(child.stdout.readline());origin=ready['origin'];token=ready['token']
   for index,(project,kind,key) in enumerate(zip(PROJECTS,KINDS,sources)):
    endpoint='/api/v1/projects/'+project+'/execution-report/'+kind+'/'+key
    code,value=get(endpoint,token,origin);assert code==200
    assert value['source']['raw_item_count']==(384 if index==0 else 3)
    assert value['source']['machine_status']==('MACHINE_VERIFIED' if index==0 else 'MACHINE_ACCEPTED_PENDING_REVIEW')
    assert value['source']['machine_case_count']==(0 if index==0 else 21)
    assert value['result_activation']=='HISTORICAL_ONLY' and value['consent_status']=='UNAVAILABLE_AS_OF'
    assert value['current_execution_status']=='UNKNOWN' and value['resource_release_status']=='NOT_OBSERVED'
    assert value['required_satisfied_count']==0 and value['independent_review_status']=='NOT_PERFORMED' and not value['goal_completed']
    if phase==0:reports.append(value)
    else:assert value['source']==reports[index]['source'] and value['as_of_state_version']==reports[index]['as_of_state_version']
    if index:assert get(endpoint,ready['limited'],origin)[0]==404
    if old:assert get(endpoint,old,origin)[0]==401
    target=Path.cwd()/('client_'+str(phase)+'_'+str(index));(target/'.rlflow').mkdir(parents=True,mode=0o700)
    (target/'.rlflow/project.yaml').write_text(json.dumps({'schema_version':'1.0','project_id':project,'control_origin':origin}))
    site=Path(rlflow.__file__).resolve().parent.parent
    call=subprocess.run([str(site/'bin/rlflow'),'client','execution-report','--kind',kind,'--source',key],
     cwd=target,env={**os.environ,'RLFLOW_REQUEST_TOKEN':token,'RLFLOW_CONTROL_ORIGIN':origin},capture_output=True,text=True,timeout=10)
    assert call.returncode==0 and token not in call.stdout+call.stderr
    assert json.loads(call.stdout)['source']==value['source']
    for route in ('commands','cpu-unit/commands','engineering-unit/commands','agent-requests'):
     try:opener.open(Request(origin+'/api/v1/projects/'+project+'/'+route,data=b'{}',headers={'Authorization':'Bearer '+token,'Origin':origin,'Content-Type':'application/json'}),timeout=10)
     except HTTPError as error:assert error.code==404
     else:raise AssertionError('cold mutation route available')
   old=token
   if phase==0:
    child.kill();child.wait(timeout=10);assert child.returncode==-9
   else:
    child.stdin.write('CLOSE\n');child.stdin.flush();stdout,stderr=child.communicate(timeout=15)
    assert child.returncode==0,stderr
  assert [business(root) for root in ROOTS]==before
  assert not any(name=='tests' or name.startswith('tests.') for name in sys.modules)
  print(json.dumps({'installed_site':str(site),'cold_processes':2,'first_read_host_killed':True,'second_host_drained':True,
   'old_token_401':True,'foreign_scope_404':True,'mutation_routes_404':True,'original_business_unchanged':True,
   'sources':[value['source'] for value in reports],'worker_restarts':0,'tests_imported':False,
   'execution_status':'UNKNOWN','resource_status':'NOT_OBSERVED','Goal_completed':False,'execution_crash_recovery':'NOT_PROVEN'}),flush=True)
 finally:
  for child in children:
   if child.poll() is None:child.kill();child.wait(timeout=10)

if __name__=='__main__':
 if '--serve' in sys.argv:serve()
 else:main()
