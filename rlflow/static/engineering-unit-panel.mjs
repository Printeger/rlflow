import {OriginalUnitPanel,checkCpuUnit,checkCpuUnitReceipt} from './cpu-unit-panel.mjs';
const fail=()=>{throw new Error('工程 Unit 来源不一致；未启用动作');};
export function checkEngineeringUnit(v,s){
  if(v?.profile!=='FIXED_ENGINEERING_PATCH_UNIT' || v.task?.kind!=='LOCAL_CPU_PATCH_PROPOSAL' ||
    v.task?.authorization!=='FIXED_PATCH_PROPOSAL_ONLY' ||
    ![null,'MACHINE_ACCEPTED_PENDING_REVIEW'].includes(v.last_sdk_status))fail();
  checkCpuUnit({...v,profile:'FIXED_CPU_PI_TRIAL_UNIT',
    last_sdk_status:v.last_sdk_status===null?null:'EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW',
    task:{...v.task,kind:'LOCAL_CPU_NUMERICAL_TRIAL',authorization:'LOCAL_CPU_TRIAL_ONLY'}},s);
  return v;
}
export function checkEngineeringUnitReceipt(v,body,actor){
  if(v?.action!==body.action || !['START_FIXED_ENGINEERING','CANCEL_FIXED_ENGINEERING'].includes(body.action))fail();
  if(body.action==='START_FIXED_ENGINEERING'){
    checkCpuUnitReceipt({...v,action:'START_FIXED_CPU'},{...body,action:'START_FIXED_CPU'},actor);
  }else checkCpuUnitReceipt(v,body,actor);
  return v;
}
export class EngineeringUnitPanel extends OriginalUnitPanel{
  constructor(options){super(options,{path:'engineering-unit',start:'START_FIXED_ENGINEERING',stop:'CANCEL_FIXED_ENGINEERING',
    check:checkEngineeringUnit,receipt:checkEngineeringUnitReceipt,notInstalled:'此项目未安装原工程 Unit 控制。',
    runNote:'提交已批准固定 add 修复：单次写入及21项机器检查；不是独立 Review，不调用模型/GPU。'});}
}
