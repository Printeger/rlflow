// Local UI consistency checks, not authority, schema validation or execution grants.
const id = v => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const hash = v => typeof v === 'string' && /^sha256:[0-9a-f]{64}$/.test(v);
const count = v => Number.isSafeInteger(v) && v >= 0;
const time = v => typeof v==='string' && v.endsWith('Z') && Number.isFinite(Date.parse(v));
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const closed = (v, keys) => object(v) && Object.keys(v).sort().join() === [...keys].sort().join();
const fail = () => {throw new Error('Hybrid response inconsistent; no action enabled');};
function safeNumbers(value) {
  const stack=[value];let visited=0;
  while(stack.length){
    if(++visited>2*1024*1024)fail();
    const v=stack.pop();
    if(typeof v==='number' && (!Number.isFinite(v) || Number.isInteger(v) && !Number.isSafeInteger(v)))fail();
    if(v!==null && typeof v==='object')stack.push(...Object.values(v));
  }
}
export function parseProposalJSON(raw) {
  if(typeof raw!=='string' || new TextEncoder().encode(raw).length>256*1024)throw new Error('proposal超出256KiB');
  const parsed=JSON.parse(raw);let at=0;
  const whitespace=()=>{while(/[ \t\r\n]/.test(raw[at] || '\u0000'))at++;};
  const string=()=>{const start=at++;while(at<raw.length){if(raw[at]==='\\'){at+=2;continue;}if(raw[at++]==='"')return JSON.parse(raw.slice(start,at));}throw new Error('JSON string invalid');};
  function walk(depth) {
    if(depth>48)throw new Error('proposal nesting exceeds bound');
    whitespace();const first=raw[at];
    if(first==='"'){string();return;}
    if(first==='{' || first==='['){
      at++;whitespace();const end=first==='{'?'}':']',keys=new Set();
      if(raw[at]===end){at++;return;}
      for(;;){
        whitespace();
        if(first==='{'){const key=string();if(keys.has(key))throw new Error('duplicate JSON key');keys.add(key);whitespace();at++;}
        walk(depth+1);whitespace();if(raw[at++]===end)break;
      }
      return;
    }
    const start=at;while(at<raw.length && !/[ \t\r\n,}\]]/.test(raw[at]))at++;
    const token=raw.slice(start,at);
    if(token==='true' || token==='false' || token==='null')return;
    const number=Number(token);
    if(!Number.isFinite(number) || Number.isInteger(number) && !Number.isSafeInteger(number))throw new Error('nonfinite or unsafe JSON number');
  }
  walk(0);return parsed;
}
const meta = ['schema_version','project_id','data_mode','store_epoch','as_of_state_version','execution_enabled'];
function scopeCheck(v, scope) {
  if (!object(v) || v.schema_version !== '1.1' || v.project_id !== scope.project || v.data_mode !== scope.mode ||
      v.store_epoch !== scope.epoch || !count(v.as_of_state_version) || v.execution_enabled !== false) fail();
}
const states = ['LEASE_VALIDATION_PENDING','REVOKED'];
export function checkGoalPage(v, scope, after='') {
  scopeCheck(v,scope);
  if (!closed(v,[...meta,'items','next_after']) || !Array.isArray(v.items) || v.items.length>50 ||
      v.next_after !== null && !id(v.next_after)) fail();
  let previous=after;
  for (const item of v.items) {
    if (!closed(item,['goal_ref','contract_revision','contract_hash','source_coverage','execution_enabled','authority']) ||
        !id(item.goal_ref) || item.goal_ref <= previous || !count(item.contract_revision) || item.contract_revision<1 ||
        !hash(item.contract_hash) || item.source_coverage !== 'HEAD_ONLY' || item.execution_enabled !== false) fail();
    previous=item.goal_ref;
    if (item.authority !== null && (!closed(item.authority,['recorded_state','authority_revision','source_coverage']) ||
        !states.includes(item.authority.recorded_state) || !count(item.authority.authority_revision) ||
        item.authority.authority_revision<1 || item.authority.source_coverage !== 'HEAD_ONLY')) fail();
  }
  if (v.next_after !== null && (v.items.length===0 || v.next_after !== previous)) fail();
  return v;
}
export function checkGoalReview(v, scope, selected) {
  scopeCheck(v,scope);
  safeNumbers(v.contract?.proposal);safeNumbers(v.changes);
  if (!closed(v,[...meta,'goal_ref','contract','changes','submitted_by','submitted_at','previous_hash','source_coverage','submitted_state_version','authority']) ||
      v.goal_ref !== selected.goal_ref || !closed(v.contract,['id','version','hash','proposal','state','approval_id','outcome']) || v.contract.state !== 'DRAFT' ||
      v.contract.hash !== selected.contract_hash || v.contract.version !== selected.contract_revision ||
      v.contract.approval_id !== null || v.contract.outcome !== null || !object(v.contract.proposal) ||
      v.contract.proposal.project_id !== scope.project || v.contract.proposal.data_mode !== scope.mode ||
      v.contract.proposal.goal_id !== v.contract.id || v.contract.proposal.contract_version !== v.contract.version ||
      !Array.isArray(v.changes) || v.changes.length>400 || v.changes.some(row=>!closed(row,['path','before','after']) || typeof row.path!=='string' || row.path.length>4000) ||
      !time(v.submitted_at) || v.previous_hash!==null && !hash(v.previous_hash) || !closed(v.submitted_by,['id','kind']) ||
      !id(v.submitted_by.id) || !['human','agent'].includes(v.submitted_by.kind) ||
      !['ORIGINAL_EVENT_VERIFIED','PARTIAL_NO_SOURCE_POINTER'].includes(v.source_coverage) ||
      (v.source_coverage === 'PARTIAL_NO_SOURCE_POINTER' ? v.submitted_state_version !== null :
        !count(v.submitted_state_version) || v.submitted_state_version<1 || v.submitted_state_version>v.as_of_state_version)) fail();
  if (v.authority !== null) {
    const a=v.authority;
    if (!closed(a,['recorded_state','authority_revision','fact_key','source_coverage','approved_contract_revision',
      'approved_proposal_hash','applies_to_current_contract','approved_at','expires_at','lifetime_status','revoked_at','evaluated_at','execution_enabled']) ||
      !states.includes(a.recorded_state) || !count(a.authority_revision) || a.authority_revision<1 || !id(a.fact_key) ||
      a.source_coverage !== 'ORIGINAL_EVENT_VERIFIED' || a.execution_enabled !== false ||
      !count(a.approved_contract_revision) || a.approved_contract_revision<1 || !hash(a.approved_proposal_hash) ||
      a.applies_to_current_contract !== (a.approved_contract_revision===v.contract.version && a.approved_proposal_hash===v.contract.hash) ||
      !time(a.approved_at) || !time(a.expires_at) || !time(a.evaluated_at) ||
      (a.recorded_state==='REVOKED' ? !time(a.revoked_at) : a.revoked_at!==null) || !['EXPIRED','UNEXPIRED'].includes(a.lifetime_status)) fail();
  }
  return v;
}
// A semantic JSON comparison only. Python canonical hashes (notably numbers)
// remain server-defined; do not pretend JSON.stringify reproduces them.
export function sameJSON(a,b) {
  if (a===b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length===b.length && a.every((v,i)=>sameJSON(v,b[i]));
  if (object(a) && object(b)) {
    const keys=Object.keys(a);
    return keys.length===Object.keys(b).length && keys.every(k=>Object.hasOwn(b,k) && sameJSON(a[k],b[k]));
  }
  return false;
}
export function checkConfirmation(v, review, scope) {
  const c=v?.confirmation,b=v?.binding;
  safeNumbers(v?.proposal);safeNumbers(v?.changes);
  if (!closed(v,['proposal','changes','binding','confirmation','execution_status','execution_enabled','limitations']) ||
      v.execution_status !== 'LEASE_VALIDATION_PENDING' || v.execution_enabled !== false ||
      !sameJSON(v.proposal,review.contract.proposal) || !sameJSON(v.changes,review.changes) ||
      !closed(c,['id','goal_id','store_epoch','expected_version','expected_revision','expected_authority_revision','proposal_hash','scope_hash','config_hash','ttl_seconds','view_hash']) ||
      !id(c.id) || c.goal_id !== review.contract.id || c.store_epoch !== scope.epoch ||
      !count(c.expected_version) || c.expected_version<review.as_of_state_version ||
      c.expected_revision !== review.contract.version || c.proposal_hash !== review.contract.hash ||
      c.expected_authority_revision !== (review.authority?.authority_revision || 0) ||
      !count(c.ttl_seconds) || c.ttl_seconds<1 || c.ttl_seconds>86400 || !hash(c.view_hash) ||
      !closed(b,['state','project_id','data_mode','proposal_hash','config_hash','scope_hash','registry_bindings']) ||
      b.state !== 'NOT_EXECUTABLE' || b.project_id !== scope.project || b.data_mode !== scope.mode ||
      b.proposal_hash !== c.proposal_hash || b.scope_hash !== c.scope_hash || b.config_hash !== c.config_hash ||
      !hash(c.scope_hash) || !hash(c.config_hash) || !sameJSON(b.registry_bindings,v.proposal.registry_bindings) ||
      !sameJSON(v.limitations,['ACTUAL_DATA_BYTES_NOT_VERIFIED','ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED'])) fail();
  return v;
}
export function approvalPayload(view) {
  return {schema_version:'1.1',action:'approve',target:{kind:'goal',id:view.confirmation.goal_id},
    expected_version:view.confirmation.expected_version,parameters:{confirmation:structuredClone(view.confirmation)}};
}
export function checkCommand(v,payload) {
  const r=v?.result, action=payload.action,goal=action==='submit_goal' ? payload.parameters.goal.goal_id :
    action==='approve' ? payload.parameters.confirmation.goal_id : payload.parameters.goal_id;
  if (!closed(v,['schema_version','command_id','action','status','accepted_state_version','duplicate','result']) ||
      v.schema_version!=='1.1' || !id(v.command_id) || v.action!==action || v.status!=='SUCCEEDED' ||
      typeof v.duplicate!=='boolean' || !count(v.accepted_state_version) || v.accepted_state_version!==payload.expected_version+1 ||
      !object(r) || r.goal_id!==goal || r.execution_enabled!==false || r.as_of_state_version!==v.accepted_state_version ||
      !closed(r,action==='submit_goal' ? ['goal_id','state','proposal_hash','contract_version','execution_enabled','as_of_state_version'] :
        ['goal_id','fact_key','state','execution_enabled','as_of_state_version']) ||
      r.state!==({submit_goal:'DRAFT',approve:'LEASE_VALIDATION_PENDING',revoke:'REVOKED'}[action]) ||
      (action==='submit_goal' ? r.contract_version!==payload.parameters.goal.contract_version || !hash(r.proposal_hash) : !id(r.fact_key))) fail();
  return v;
}
export class PendingCommand {
  constructor(scope, payload, key, rawBody=null) {
    if (!id(key)) fail();
    if(rawBody!==null && (typeof rawBody!=='string' || !sameJSON(JSON.parse(rawBody),payload)))fail();
    Object.defineProperties(this,{scope:{value:Object.freeze({...scope}),enumerable:true},
      key:{value:key,enumerable:true},body:{value:rawBody ?? JSON.stringify(payload),enumerable:true}});
    this.status='READY';
  }
  matches(scope) {return sameJSON(this.scope,scope);}
  begin(scope) {
    if (!this.matches(scope) || !['READY','UNKNOWN'].includes(this.status)) fail();
    this.status='IN_FLIGHT';return {key:this.key,body:this.body};
  }
  unknown() {if (this.status!=='IN_FLIGHT') fail();this.status='UNKNOWN';}
  finish() {if (this.status!=='IN_FLIGHT') fail();this.status='FINISHED';}
  invalidate() {this.status='INVALIDATED';}
}
