import test from 'node:test';
import assert from 'node:assert/strict';
import {CandidateOutputPanel,checkOutput} from '../rlflow/static/candidate-output-panel.mjs';
const hash=c=>'sha256:'+c.repeat(64);
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false};
const row={id:'output_a',task_id:'task_a',attempt_id:'attempt_a',goal_ref:'goal_a',contract_revision:1,recorded_at:'2026-10-09T00:00:00Z',recorded_at_state_version:4,state:'OUTPUT_CAPTURED_AUDIT_ONLY',source_coverage:'ORIGINAL_DEPENDENCIES_VERIFIED',current_activation:'HISTORICAL_AUDIT_ONLY',current_execution_status:'UNKNOWN',resource_release_status:'NOT_OBSERVED',actual_cost_status:'UNKNOWN',model_enabled:false,gpu_enabled:false,controls_available:false,goal_completed:false,dispatch_enabled:false,independent_review_status:'NOT_PERFORMED',target:'module/source.py',before_sha256:hash('a'),after_sha256:hash('b'),base_tree_sha256:hash('c'),output_tree_sha256:hash('d'),baseline_failed_cases:2,actual_passed_cases:3};
const evidence={actual_tests:[[2,3],[-4,2],[0,0]].map(([left,right])=>({left,right,expected:left+right,actual:left+right})),candidate_write_performed:true,candidate_write_fd_closed:true,historical_runtime_phase:'FIXTURE_SCOPE_STOPPED',historical_pool_release:'FIXTURE_FREE',result_sha256:hash('e'),intent_sha256:hash('f'),source_sha256:hash('a'),program_sha256:hash('b'),resource_enforcement:'partial'};
const page={...meta,items:[row],next_after:null},detail={...meta,candidate:{...row,evidence}};
const machine={id:'acceptance_a',recorded_at:'2026-10-09T00:00:01Z',recorded_at_state_version:5,
  verifier_version:'FIXED_ADD_RAW_AST_CHECK_V1',verifier_sha256:hash('a'),status:'MACHINE_ACCEPTED_PENDING_REVIEW',
  derived:{source_sha256:row.after_sha256,spec_sha256:hash('b'),syntax_sha256:hash('c'),passed_cases:21,
    actual_tests:Array.from({length:21},(_,i)=>{const left=Math.floor(i/3)-3,right=[-2,0,2][i%3];return {left,right,expected:left+right,actual:left+right};})},
  interpretation_scope:'FIXED_ADD_FUNCTION_ONLY',candidate_read_only:true,condition_coverage:[],independent_review_status:'NOT_PERFORMED',goal_completed:false,dispatch_enabled:false};
class Element{constructor(){this.textContent='';this.children=[];}addEventListener(){}replaceChildren(...v){this.children=v;}append(v){this.children.push(v);}}
function setup(request){const elements=new Map();globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element()};let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'viewer'}};const jobs=new Map();let next=0;const panel=new CandidateOutputPanel({context:()=>context,request,schedule:fn=>{jobs.set(++next,fn);return next;},cancel:id=>jobs.delete(id)});return {panel,jobs,context:()=>context,setContext:v=>context=v,run:async()=>{const [id,fn]=[...jobs][0];jobs.delete(id);fn();await new Promise(r=>setImmediate(r));}};}
test('closed actual-output DTO rejects invented current authority and inconsistent evidence',()=>{
  const scope={project:'p',mode:'fixture',epoch:'e'};
  assert.equal(checkOutput(page,scope).items.length,1);assert.deepEqual(checkOutput(detail,scope,row).candidate.evidence.actual_tests,evidence.actual_tests);
  for(const bad of [{...page,store_epoch:'wrong'},{...page,extra:'hostpath'},{...page,next_after:'other'},{...page,items:[{...row,goal_completed:true}]},{...page,items:[{...row,current_activation:'CURRENT'}]},{...page,items:[{...row,actual_passed_cases:2}]},{...page,items:[{...row,after_sha256:row.before_sha256}]},{...page,items:[{...row,recorded_at_state_version:2**53}]}])assert.throws(()=>checkOutput(bad,scope));
  assert.throws(()=>checkOutput(detail,scope,{...row,attempt_id:'other'}));
  const measured={...evidence,cpu_ns:42,worker_wall_ns:84,cpu_measurement_scope:'ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT'};
  assert.equal(checkOutput({...detail,candidate:{...row,evidence:measured}},scope,row).candidate.evidence.cpu_ns,42);
  for(const e of [{...evidence,cpu_ns:42},{...measured,cpu_ns:true},{...measured,cpu_ns:3e9+1},{...measured,worker_wall_ns:-1},{...measured,cpu_measurement_scope:'INVOICE'}])
    assert.throws(()=>checkOutput({...detail,candidate:{...row,evidence:e}},scope,row));
  for(const e of [{...evidence,candidate_write_fd_closed:false},{...evidence,historical_pool_release:'CURRENT_FREE'},{...evidence,actual_tests:evidence.actual_tests.map((t,i)=>i? t:{...t,actual:4})}])assert.throws(()=>checkOutput({...meta,candidate:{...row,evidence:e}},scope,row));
});
test('optional original machine disposition preserves legacy/null and rejects fake independent review or cases',()=>{
  const scope={project:'p',mode:'fixture',epoch:'e'};
  assert.equal(checkOutput({...detail,candidate:{...detail.candidate,machine_acceptance:null}},scope,row).candidate.machine_acceptance,null);
  const body={...detail,as_of_state_version:5,candidate:{...detail.candidate,machine_acceptance:machine}};
  assert.equal(checkOutput(body,scope,row).candidate.machine_acceptance.derived.passed_cases,21);
  const micro={...body,candidate:{...body.candidate,machine_acceptance:{...machine,recorded_at:'2026-10-09T00:00:00.000001Z'}}};
  assert.equal(checkOutput(micro,scope,row).candidate.machine_acceptance.derived.passed_cases,21);
  for(const recorded_at of ['2026-10-09T00:00:00.000000Z','2026-10-08T23:59:59.999999Z'])
    assert.throws(()=>checkOutput({...micro,candidate:{...micro.candidate,machine_acceptance:{...micro.candidate.machine_acceptance,recorded_at}}},scope,row));
  assert.throws(()=>checkOutput({...micro,candidate:{...micro.candidate,recorded_at:'2026-10-09T00:00:00.000002Z'}},scope,row));
  for(const m of [{...machine,status:'ACCEPTED_GOAL'},{...machine,independent_review_status:'PERFORMED'},{...machine,goal_completed:true},{...machine,recorded_at_state_version:4},{...machine,recorded_at:row.recorded_at},{...machine,derived:{...machine.derived,source_sha256:row.before_sha256}},{...machine,derived:{...machine.derived,actual_tests:machine.derived.actual_tests.map((t,i)=>i?t:{...t,actual:123})}}])assert.throws(()=>checkOutput({...body,candidate:{...body.candidate,machine_acceptance:m}},scope,row));
});
test('original selected id refreshes only on durable version; offline/heartbeat/failure do not loop',async()=>{
  let version=4,failed=false;const calls=[];const s=setup(async url=>{calls.push(url);if(failed)throw Error('source');return {...(url.includes('?')?page:detail),as_of_state_version:version};});
  await s.panel.load();await s.panel.open(row);s.panel.connection('OFFLINE');s.panel.changed(6);assert.equal(s.jobs.size,0);assert.equal(s.panel.dirty(),true);
  s.panel.connection('CATCHING UP');assert.equal(s.jobs.size,1);version=6;await s.run();assert.equal(s.panel.detail.as_of_state_version,6);assert.ok(calls[3].endsWith('/candidate-outputs/output_a'));
  s.panel.connection('LIVE');s.panel.changed(6);assert.equal(s.jobs.size,0);s.panel.changed(7);failed=true;await s.run();assert.equal(s.panel.blocked,true);s.panel.changed(8);s.panel.connection('LIVE');assert.equal(s.jobs.size,0);assert.match(s.panel.$('live').textContent,/STALE/);
  failed=false;version=8;await s.panel.load();assert.equal(s.panel.blocked,false);
});
test('late success/error across principal/project/epoch/logout cannot restore private DOM or timer',async()=>{
  for(const kind of ['identity','project','epoch','logout'])for(const error of [false,true]){
    let resolve,reject;const s=setup(()=>new Promise((a,b)=>{resolve=a;reject=b;}));const pending=s.panel.open(row);
    s.setContext(kind==='logout'?null:{...s.context(),...(kind==='identity'?{authGeneration:2,session:{principal_id:'other'}}:{[kind]:'other'})});s.panel.clear();if(error)reject(Object.assign(Error('old401'),{status:401}));else resolve(detail);await pending;
    assert.equal(s.panel.detail,null);assert.equal(s.panel.$('detail').textContent,'');assert.equal(s.panel.reading,false);assert.equal(s.jobs.size,0);
  }
});
