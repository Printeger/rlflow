import test from 'node:test';
import assert from 'node:assert/strict';
import {TelemetryView,checkTelemetry} from '../rlflow/static/telemetry-view.mjs';
const scope={project:'project_test',mode:'fixture',epoch:'store_test'};
const execution='ref_'+'a'.repeat(64);
function sample(seq=1) {
  return {schema_version:'1.0',sample_id:`sampler_test:${seq}`,sampler_epoch:'sampler_test',sample_seq:seq,
    observed_at:'2026-10-08T00:00:00Z',project_id:scope.project,store_epoch:scope.epoch,data_mode:scope.mode,
    source:'CORE_OS_SAMPLE',observability:'PARTIAL',sample_age_seconds:2,source_state_version:1,
    host:{cpu:{scope:'HOST',status:'UNKNOWN',utilization_percent:null},memory:{scope:'HOST',status:'KNOWN',total_bytes:4096,available_bytes:2048},disk:{scope:'STATE_FILESYSTEM',status:'UNKNOWN',total_bytes:null,available_bytes:null}},
    gpu:{scope:'GPU',status:'UNKNOWN',utilization_percent:null,memory_used_bytes:null},
    workers:[{execution_id:execution,process:{scope:'SUPERVISOR_PROCESS',status:'UNKNOWN',cpu_seconds:null,rss_bytes:null},heartbeat:{status:'FRESH',counter:2,age_seconds:3}}],workers_truncated:true};
}
test('duplicate and late samples never renew age; heartbeat is independent of sample freshness',()=>{
  const view=new TelemetryView(scope);assert.ok(view.accept(sample(2),100));
  assert.equal(view.accept(sample(2),14000),false);assert.equal(view.accept(sample(1),14000),false);
  const current=view.current(14100);assert.equal(current.freshness,'STALE');assert.equal(current.workers[0].heartbeat.status,'STALE');
  assert.equal(current.sample_age_seconds,16);assert.equal(current.workers[0].heartbeat.age_seconds,17);
  assert.equal(view.value.workers[0].heartbeat.age_seconds,3);
});
test('retired sampler cannot replace current epoch; execution updates invalidate old worker not HOST',()=>{
  const view=new TelemetryView(scope);view.accept(sample(),0);
  const next=sample();Object.assign(next,{sampler_epoch:'sampler_new',sample_id:'sampler_new:1',observed_at:'2026-10-08T00:00:01Z'});
  assert.ok(view.accept(next,10));assert.equal(view.accept(sample(100),20),false);
  view.invalidateWorkers([execution],2);assert.equal(view.current(20).workers[0].heartbeat.status,'UNKNOWN');
  assert.equal(view.current(20).host.memory.status,'KNOWN');
  const newer=structuredClone(next);newer.sample_seq=2;newer.sample_id='sampler_new:2';newer.source_state_version=2;assert.ok(view.accept(newer,30));
  assert.equal(view.current(30).workers[0].heartbeat.status,'FRESH');
});
test('a newer sample from an older source version cannot undo domain generation barrier',()=>{
  const view=new TelemetryView(scope);view.invalidateWorkers([execution],5);
  assert.ok(view.accept(sample(3),10));assert.equal(view.current(10).workers[0].heartbeat.status,'UNKNOWN');
  const next=sample(4);next.source_state_version=5;assert.ok(view.accept(next,20));assert.equal(view.current(20).workers[0].heartbeat.status,'FRESH');
});
test('initial snapshot floor and unbound legacy slot suppress worker freshness',()=>{
  const view=new TelemetryView({...scope,sourceVersion:5});view.accept(sample(),0);
  assert.equal(view.current(0).workers[0].heartbeat.status,'UNKNOWN');
  const legacy=sample(2);legacy.source_state_version=null;view.accept(legacy,10);
  assert.equal(view.current(10).workers[0].heartbeat.status,'UNKNOWN');
  assert.equal(view.current(10).host.memory.status,'KNOWN');
});
test('closed scope/status/bounds and malformed data are rejected without private extras',()=>{
  for (const mutate of [v=>v.project_id='other',v=>v.store_epoch='other',v=>v.data_mode='live',v=>v.command='PRIVATE',
    v=>v.host.memory.available_bytes=5000,v=>v.host.cpu.utilization_percent=0,v=>v.gpu.status='KNOWN',
    v=>v.workers[0].process.pid=1,v=>v.workers[0].heartbeat.age_seconds=20,v=>v.workers.push(structuredClone(v.workers[0])),
    v=>v.sample_age_seconds=NaN,v=>v.sample_id='wrong',v=>v.sample_seq=Number.MAX_SAFE_INTEGER+1]) {
    const value=sample();mutate(value);assert.throws(()=>checkTelemetry(value,scope));
  }
  const view=new TelemetryView(scope);view.accept(sample(),10);assert.throws(()=>view.current(9));
  const value=sample();value.host.memory.status='UNKNOWN';value.host.memory.total_bytes=null;value.host.memory.available_bytes=null;
  assert.equal(checkTelemetry(value,scope).host.memory.available_bytes,null);
});
