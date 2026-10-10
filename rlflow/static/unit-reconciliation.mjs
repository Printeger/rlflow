// Fixed ASCII original command binding, not a generic Python JSON codec.
const closed=(v,keys)=>v!==null && typeof v==='object' && !Array.isArray(v) && Object.keys(v).sort().join()===keys.slice().sort().join();
const id=v=>typeof v==='string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
const count=v=>Number.isSafeInteger(v) && v>=0;
const hash=v=>typeof v==='string' && /^sha256:[0-9a-f]{64}$/.test(v);
const fail=()=>{throw new Error('原恢复来源或命令绑定不一致；未启用恢复。');};
const digest=async raw=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))),x=>x.toString(16).padStart(2,'0')).join('');

export async function bindOriginalRun(scope,intent,receipt,profile){
  const body=JSON.parse(intent.body);
  if(!closed(body,['action','task_id','expected_state_version']) || body.action!==profile.start || !id(body.task_id) ||
      !count(body.expected_state_version) || !id(intent.key) || scope.mode!=='fixture' ||
      ![scope.project,scope.epoch,scope.identity].every(id))fail();
  profile.receipt(receipt,body,scope.identity);
  const [command,request]=await Promise.all([
    digest(JSON.stringify([scope.project,'fixture',scope.epoch,scope.identity,intent.key])),
    digest(JSON.stringify({action:body.action,expected_state_version:body.expected_state_version,task_id:body.task_id}))]);
  if(receipt.command_id!=='fixture_command_'+command || receipt.request_hash!=='sha256:'+request)fail();
  const unit=await digest(JSON.stringify({expected_state_version:body.expected_state_version,idempotency_key:receipt.command_id}));
  const phase=key=>digest(JSON.stringify([scope.project,'fixture',scope.epoch,key]));
  let facts;
  if(profile.path==='cpu-unit'){
    const [assessment,decision]=await Promise.all([phase('cpu_unit_assessment_'+unit),phase('cpu_unit_decision_'+unit)]);
    facts={assessment:'cpu_assessment_'+assessment,decision:'cpu_assessment_'+decision};
  }else{
    const original='candidate_output_'+await phase('unit_apply_'+unit);
    const output='candidate_output_result_'+await digest(JSON.stringify(original));
    facts={output,acceptance:'candidate_output_acceptance_'+await digest(JSON.stringify(output))};
  }
  return Object.freeze({scope:Object.freeze({...scope}),body:intent.body,key:intent.key,receipt:Object.freeze({...receipt}),facts:Object.freeze(facts)});
}

export function checkUnitReconciliation(v,witness,profile){
  if(!closed(v,['schema_version','profile','original_acceptance','result','result_fact','new_dispatch_enabled','automatic_effect_retry_enabled']) ||
      v.schema_version!=='1.0' || v.profile!=='ORIGINAL_UNIT_RECONCILIATION' ||
      v.new_dispatch_enabled!==false || v.automatic_effect_retry_enabled!==false)fail();
  profile.receipt(v.original_acceptance,JSON.parse(witness.body),witness.scope.identity);
  if(Object.keys(witness.receipt).some(k=>k!=='duplicate' && v.original_acceptance[k]!==witness.receipt[k]))fail();
  const r=v.result,cpu=profile.path==='cpu-unit';
  const withFact=cpu?['EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW','EXPERIMENT_MACHINE_UNAVAILABLE','EXPERIMENT_ASSESSED_CANCELLED']:
    ['MACHINE_ACCEPTED_PENDING_REVIEW','OUTPUT_CAPTURED_CANCELLED'];
  const withoutFact=['CANCELLED_SCOPE_STOPPED','UNKNOWN_CLEANUP_REQUIRED','UNKNOWN_RESULT_UNAVAILABLE',...(cpu?[]:['UNKNOWN_NO_AUTOMATIC_EFFECT_RETRY'])];
  if(!closed(r,['status','lease_id','cancel_requested','goal_completed','independent_review_status','dispatch_enabled','execution_scope','cleanup_error']) ||
      ![...withFact,...withoutFact].includes(r.status) || !id(r.lease_id) || typeof r.cancel_requested!=='boolean' ||
      r.goal_completed!==false || r.independent_review_status!=='NOT_PERFORMED' || r.dispatch_enabled!==false ||
      r.execution_scope!==(cpu?'FIXED_CPU_PI_TRIAL_V1':'FIXED_ADD_PATCH_ONLY') ||
      !(r.cleanup_error===null || typeof r.cleanup_error==='string' && new TextEncoder().encode(r.cleanup_error).length<=4096))fail();
  if((r.status.endsWith('CANCELLED') || r.status==='CANCELLED_SCOPE_STOPPED') && !r.cancel_requested)fail();
  if(r.status==='CANCELLED_SCOPE_STOPPED' && r.cleanup_error!==null ||
      r.status==='UNKNOWN_CLEANUP_REQUIRED' && !(typeof r.cleanup_error==='string' && r.cleanup_error.length>0))fail();
  const fact=v.result_fact;
  if(withoutFact.includes(r.status)){if(fact!==null)fail();}
  else{
    if(!closed(fact,['id','source_id','sha256','recorded_state_version']) || !hash(fact.sha256) ||
        !count(fact.recorded_state_version) || fact.recorded_state_version<=witness.receipt.accepted_state_version)fail();
    if(cpu){if(fact.id!==witness.facts[r.status==='EXPERIMENT_ASSESSED_CANCELLED'?'assessment':'decision'] || fact.source_id!==fact.id)fail();}
    else if(r.status==='MACHINE_ACCEPTED_PENDING_REVIEW'){
      if(fact.id!==witness.facts.acceptance || fact.source_id!==witness.facts.output)fail();
    }else if(fact.id!==witness.facts.output || fact.source_id!==fact.id)fail();
  }
  return v;
}
