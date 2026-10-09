import test from 'node:test';
import assert from 'node:assert/strict';
import {CpuAssessmentPanel,checkAssessment} from '../rlflow/static/cpu-assessment-panel.mjs';
const meta={schema_version:'1.1',project_id:'p',data_mode:'fixture',store_epoch:'e',as_of_state_version:4,execution_enabled:false};
const assessment={profile:'FIXED_CPU_PI_TRIAL_V1',execution_status:'NOT_EXECUTED',scientific_validity:'UNASSESSED',hypothesis_outcome:'INCONCLUSIVE',interpretation_scope:'PINNED_THREE_SEEDS_ONLY',next_action:'NO_AUTOMATIC_RETRY',condition_coverage:[],independent_review_status:'NOT_PERFORMED',goal_completed:false,dispatch_enabled:false};
const row={id:'assessment_a',experiment_id:'task_a',attempt_id:'attempt_a',goal_ref:'goal_a',contract_revision:1,recorded_at:'2026-10-09T00:00:00Z',recorded_at_state_version:4,assessment,source_coverage:'ORIGINAL_DEPENDENCIES_VERIFIED',model_enabled:false,gpu_enabled:false,controls_available:false,current_execution_status:'UNKNOWN',resource_release_status:'NOT_OBSERVED',actual_cost_status:'UNKNOWN',goal_completed:false,dispatch_enabled:false,current_activation:'HISTORICAL_ONLY',checked_at:'2026-10-09T00:00:01Z'};
const page={...meta,items:[row],next_after:null},detail={...meta,experiment:{...row,evidence:null}};
class Element{constructor(){this.textContent='';this.children=[];}addEventListener(){}replaceChildren(...v){this.children=v;}append(v){this.children.push(v);}}
function setup(request){const elements=new Map();globalThis.document={getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element()};let context={project:'p',mode:'fixture',epoch:'e',version:4,authGeneration:1,session:{principal_id:'viewer'}};let clock=0,next=0;const jobs=new Map();const panel=new CpuAssessmentPanel({context:()=>context,request,now:()=>clock,schedule:(fn,delay)=>{jobs.set(++next,{fn,at:clock+delay});return next;},cancel:id=>jobs.delete(id)});return {panel,jobs,setContext:v=>context=v,context:()=>context,run:async()=>{const [id,j]=[...jobs][0];jobs.delete(id);clock=j.at;j.fn();await new Promise(r=>setImmediate(r));}};}
test('closed three-axis source, scope, pagination and never-current authority claims',()=>{
  const s={project:'p',mode:'fixture',epoch:'e'};assert.equal(checkAssessment(page,s).items.length,1);assert.equal(checkAssessment(detail,s,row).experiment.evidence,null);
  for(const bad of [{...page,store_epoch:'other'},{...page,extra:'path'},{...page,next_after:'arbitrary'},{...page,items:[{...row,controls_available:true}]},{...page,items:[{...row,assessment:{...assessment,goal_completed:true}}]},{...page,items:[{...row,assessment:{...assessment,scientific_validity:'VALID'}}]}])assert.throws(()=>checkAssessment(bad,s));
  assert.throws(()=>checkAssessment(detail,s,{...row,attempt_id:'other'}));
});
test('unexecuted conclusions and contradictory raw evidence outcomes are rejected',()=>{
  const scope={project:'p',mode:'fixture',epoch:'e'};
  for(const status of ['NOT_EXECUTED','RESULT_UNAVAILABLE'])for(const outcome of ['SUPPORTED','REFUTED'])assert.throws(()=>checkAssessment({...page,items:[{...row,assessment:{...assessment,execution_status:status,hypothesis_outcome:outcome}}]},scope));
  const success={...assessment,execution_status:'SUCCEEDED',scientific_validity:'VALID',hypothesis_outcome:'SUPPORTED',next_action:'REQUEST_INDEPENDENT_REVIEW'};
  assert.throws(()=>checkAssessment({...page,items:[{...row,assessment:{...success,hypothesis_outcome:'INCONCLUSIVE'}}]},scope));
  const evidence={raw_samples:[7,11,19].map(seed=>({seed,points:Array.from({length:128},()=>[0,0])})),inside_counts:[128,128,128],estimates:[4,4,4],mean_absolute_error:1,baseline:3,baseline_absolute_error:0.1,hypothesis_supported:false,source_sha256:'sha256:'+'a'.repeat(64),input_sha256:'sha256:'+'b'.repeat(64),program_sha256:'sha256:'+'c'.repeat(64),evaluator_sha256:'sha256:'+'d'.repeat(64),cpu_ns:1,worker_wall_ns:2,cpu_measurement_scope:'ORIGINAL_FIXED_PROGRAM_KERNEL_REPORTED_AS_OF_EMIT',resource_enforcement:'partial',verification:'RAW_VALUES_VERIFIED'};
  for(const supported of [false,true])assert.throws(()=>checkAssessment({...meta,experiment:{...row,assessment:{...success,hypothesis_outcome:supported?'REFUTED':'SUPPORTED'},evidence:{...evidence,hypothesis_supported:supported}}},scope,row));
});
test('durable versions coalesce reads; heartbeat and failures never loop or POST',async()=>{
  const calls=[];let version=4,failed=false;const s=setup(async url=>{calls.push(url);if(failed)throw new Error('source failed');return {...page,as_of_state_version:version};});
  await s.panel.load();s.panel.connection('LIVE');s.panel.changed(5);s.panel.changed(6);assert.equal(s.jobs.size,1);version=6;await s.run();assert.equal(calls.length,2);assert.equal(s.panel.dirty(),false);
  s.panel.connection('LIVE');s.panel.changed(6);assert.equal(s.jobs.size,0);s.panel.changed(7);failed=true;await s.run();assert.equal(s.panel.blocked,true);assert.equal(s.jobs.size,0);s.panel.changed(8);s.panel.connection('LIVE');assert.equal(s.jobs.size,0);assert.match(s.panel.$('live').textContent,/STALE/);
  failed=false;version=8;await s.panel.load();assert.equal(s.panel.blocked,false);assert.equal(calls.length,4);
});
test('late detail after principal/project/epoch switch or logout cannot repopulate private DOM',async()=>{
  for(const kind of ['identity','project','epoch','logout']){
    let resolve;const s=setup(()=>new Promise(r=>resolve=r));const pending=s.panel.open(row);
    s.setContext(kind==='logout'?null:{...s.context(),...(kind==='identity'?{authGeneration:2,session:{principal_id:'other'}}:{[kind]:'other'})});s.panel.clear();resolve(detail);await pending;assert.equal(s.panel.detail,null);assert.equal(s.panel.$('detail').textContent,'');assert.equal(s.panel.reading,false);assert.equal(s.jobs.size,0);
  }
});
test('snapshot floor and offline durable changes stay stale; selected detail rereads only original id',async()=>{
  let version=4;const calls=[];const s=setup(async url=>{calls.push(url);return {...(url.includes('?')?page:detail),as_of_state_version:version};});
  await s.panel.load();await s.panel.open(row);s.panel.connection('OFFLINE');s.panel.changed(7);assert.equal(s.jobs.size,0);assert.equal(s.panel.dirty(),true);s.panel.connection('CATCHING UP');assert.equal(s.jobs.size,1);version=7;await s.run();assert.equal(s.panel.detail.as_of_state_version,7);assert.equal(calls.length,4);assert.ok(calls[3].endsWith('/assessment_a'));
});
