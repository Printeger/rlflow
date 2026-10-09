# 真实有限研究状态与原始证据只读HTTP：Checkpoint51

50已提交2a43838c5c4b3721b240de7d239aa929c0a68863。51交付真实可调用读取，而非新增准备组件或虚构实验：原appraisal/384原数值样本/独立指标/验证指纹通过当前产品authenticated只读HTTP返回。无Start/Stop/dispatch/artifact路径入口；独立评审/条件决策未实现。

## 接线与行为

create_app新增可选cpu_assessment_readers；默认未启用两路由404。trusted-startup CpuAssessmentReader接既有Store.attach_existing（不DDL/recover/创建）、固定Registry、project/fixture/epoch和server时钟。它不接Runtime/Source/Pool owner，原owner全部关闭后依旧可读。

- GET /api/v1/projects/{project_id}/cpu-trial-assessments：after/limit闭合query，默认2/最多5，共用同一64MiB累积源预算，SQL有界keyset及原事件数/投影域检查。coverage仅已核各原依赖，不称全链audit。
- GET /api/v1/projects/{project_id}/cpu-trial-assessments/{assessment_id}：同事务完整原appraisal/terminal/preparation/Goal批准与Plan/install/workspace/controller/Budget依赖核验，返回真实三轴/next与有界原384点/inside/指标/SHA。NoG evidence=null，UNASSESSED/INCONCLUSIVE不伪装科学成功。缺原投影但原事件存在为503，不伪404。

当前Goal/批准/Registry重新加载后，所有源读取末UTC再核expires，才显示EXPERIMENT_CURRENT_AS_OF；过期/换版/撤销为HISTORICAL_ONLY且原immutable事实不改。snapshot同BEGIN核project/mode/epoch、projection version=observation source version=MAX(event seq)，meta损坏503不降成正常历史200。route before/after读取及freshmetadata均重新鉴权；viewer可读，跨项目404，读中撤销401，same-origin保持。

DTO为allowlist：experiment/attempt/assessment/Goal标识、有限解释范围、原三轴、next和原数值指标/指纹。host路径、producer/PID/boot、nonce、lease、Registry witness和Pool私有物料不外发，不接受任意path/FD/raw/artifact。 current_execution_status=UNKNOWN、resource_release_status=NOT_OBSERVED、controls_available=False，既有原FREE历史证明不冒称当前主机资源。condition_coverage=[]、Goalfalse、独立review未做、model/GPU/dispatchFalse保持。

GET不执行poll/collect/写/模型/原owner重建，不做生产迁移或保护目录操作；所有证据实际来源于已封闭有限CPU试验，未从前端mock或计数动画推断运行。

## 已发生的验证（FINAL）

原87162终2223b6 exit1：3fail/1warning39.80s，全部新fixture错用不存在Store.open_existing。先rg实际定义确认应使用attach_existing(project_id/data_mode)，仅修fixture，不造/放宽生产兼容接口；原CPU实际执行发生但当时HTTP未验收，失败日志保留。

另修已发现原投影缺失应503的读源差异并加入负例/实际loopback，原30148终73ec7e exit0：4pass/1warning49.71s。真实sealed原384点/96、101、104inside/0.088219误差→父核验→appraisal→HTTP，冷Store无budget/appraisal owner，读取不poll/write/collect/Popen，原execution owner+Pool shutdown后仍可读；认证/default404/closedquery/读中revoke/两页keyset/过期/坏原projection与detail503通过。实际uvicorn loopback GET原noG研究状态/evidence null、POST405、零新Popen/Storeversion不变、socket线程有限关闭通过。

High独立发现metadata projection/source版本不一致不能变历史200；仅新reader snapshot追加同txn整数等值guard，原85002终1983b1 exit0：1pass/1warning10.06s，损坏list/detail503→恢复current、错误epoch startup拒绝。原四已通过项未重复；原数值program/evaluator/runtime未变。

唯一必要五模块Web/readonly/auth/config/既有Task读取回归原36076终79d0fe exit0：129pass/2warning98.67s；264代码/测试/schema/web输入冻结且终态后全部SHA匹配，manifest7426d4fcc5fe6f19885471adf23a5f9dcc40eb3e61f849f1dee6bdc9e838435d。compileall/pipcheck/diff/最终SHA各exit0，无live测试，High窄MUST关闭，正在归档提交51。原失败/日志hash/具体原会话与终态见evidence/checkpoint-51-final-tests.txt。没有重复原rawpositive、loopback或全前端；不是最终fresh五新case套或完整Goal/native/工程科研/独立评审/严格OS/任意树/安装/长期验收。

## 下一项与缺口

下一需将真实Experiment/原始证据/三轴研究状态接现有Dashboard，并继续当前合同的独立评价、可信条件映射与有限决策闭环；不能用HTTP成功或VALID字样代替独立科研评价。真正工程candidate/native和原安装/故障/严格资源/24h及8h完整验收仍保持待办，付费/GPU/生产权限不扩大。
