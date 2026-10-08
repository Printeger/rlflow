// Independent latest sample: never alters business cursor, counts or activity.
const closed = (v,keys) => v && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.sort().join();
const finite = v => typeof v==='number' && Number.isFinite(v) && v>=0;
const count = v => Number.isSafeInteger(v) && v>=0;
const id = v => typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const opaque = v => typeof v==='string' && /^ref_[0-9a-f]{64}$/.test(v);
const need = v => {if (!v) throw new Error('INVALID_TELEMETRY');};
function metric(v,scope,fields) {
  need(closed(v,['scope','status',...fields]) && v.scope===scope && ['KNOWN','UNKNOWN'].includes(v.status));
  for (const k of fields) need(v.status==='UNKNOWN' ? v[k]===null : (k.endsWith('bytes') ? count(v[k]) : finite(v[k])));
  if (v.status==='KNOWN' && fields.includes('available_bytes')) need(v.available_bytes<=v.total_bytes);
}
export function checkTelemetry(v,scope) {
  need(closed(v,['schema_version','sample_id','sampler_epoch','sample_seq','source_state_version','observed_at','project_id','store_epoch','data_mode','source','observability','sample_age_seconds','host','gpu','workers','workers_truncated']));
  need(v.source_state_version===null || count(v.source_state_version));
  need(v.schema_version==='1.0' && id(v.sample_id) && id(v.sampler_epoch) && count(v.sample_seq) && v.sample_seq>0 &&
    v.sample_id===`${v.sampler_epoch}:${v.sample_seq}` && v.project_id===scope.project && v.store_epoch===scope.epoch && v.data_mode===scope.mode &&
    v.source==='CORE_OS_SAMPLE' && v.observability==='PARTIAL' && finite(v.sample_age_seconds) &&
    typeof v.observed_at==='string' && v.observed_at.endsWith('Z') && Number.isFinite(Date.parse(v.observed_at)));
  need(closed(v.host,['cpu','memory','disk']));
  metric(v.host.cpu,'HOST',['utilization_percent']);
  need(v.host.cpu.status==='UNKNOWN' || v.host.cpu.utilization_percent<=100);
  metric(v.host.memory,'HOST',['total_bytes','available_bytes']);metric(v.host.disk,'STATE_FILESYSTEM',['total_bytes','available_bytes']);
  need(closed(v.gpu,['scope','status','utilization_percent','memory_used_bytes']) && v.gpu.scope==='GPU' && v.gpu.status==='UNKNOWN' && v.gpu.utilization_percent===null && v.gpu.memory_used_bytes===null);
  need(Array.isArray(v.workers) && v.workers.length<=32 && typeof v.workers_truncated==='boolean');
  const seen = new Set();
  for (const w of v.workers) {
    need(closed(w,['execution_id','process','heartbeat']) && opaque(w.execution_id) && !seen.has(w.execution_id));seen.add(w.execution_id);
    metric(w.process,'SUPERVISOR_PROCESS',['cpu_seconds','rss_bytes']);
    const h = w.heartbeat;
    need(closed(h,['status','counter','age_seconds']) && ['FRESH','STALE','UNKNOWN'].includes(h.status));
    need(h.status==='UNKNOWN' ? h.counter===null && h.age_seconds===null : count(h.counter) && h.counter>0 && finite(h.age_seconds) && (h.status==='FRESH')===(h.age_seconds<=15));
  }
  return v;
}
export class TelemetryView {
  constructor(scope) {this.scope=scope;this.value=null;this.received=null;this.retired=new Set();this.barrier=scope.sourceVersion || 0;need(count(this.barrier));}
  accept(value,now) {
    need(finite(now));checkTelemetry(value,this.scope);
    const old = this.value;
    if (old) {
      if (value.sampler_epoch===old.sampler_epoch && value.sample_seq<=old.sample_seq) return false;
      if (this.retired.has(value.sampler_epoch)) return false;
      if (value.sampler_epoch!==old.sampler_epoch) {
        if (Date.parse(value.observed_at)<=Date.parse(old.observed_at)) return false;
        // Bound epochs without forgetting a retired identity: force reset.
        need(this.retired.size<16);this.retired.add(old.sampler_epoch);
      }
    }
    this.value=structuredClone(value);this.received=now;
    return true;
  }
  invalidateWorkers(ids,version) {
    need(count(version));
    // Keep the latest global execution barrier even before the first sample;
    // late frames may introduce workers absent from the previous batch.
    if (ids.length) this.barrier=Math.max(this.barrier,version);
  }
  current(now) {
    if (!this.value) return null;
    need(finite(now) && now>=this.received);
    const v=structuredClone(this.value), elapsed=(now-this.received)/1000;
    v.sample_age_seconds+=elapsed;v.freshness=v.sample_age_seconds<=15?'FRESH':'STALE';
    for (const w of v.workers) {
      if (v.source_state_version===null || v.source_state_version<this.barrier) {w.process.status='UNKNOWN';w.process.cpu_seconds=null;w.process.rss_bytes=null;w.heartbeat={status:'UNKNOWN',counter:null,age_seconds:null};}
      else if (w.heartbeat.status!=='UNKNOWN') {w.heartbeat.age_seconds+=elapsed;w.heartbeat.status=w.heartbeat.age_seconds<=15?'FRESH':'STALE';}
    }
    return v;
  }
}
