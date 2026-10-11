# A 原接纳事实到明确后续任务

范围：本地原生运行接线，不授真实模型运行额度，不改变 GPU/B/C/instinctRL HOLD。

## 交付行为

批准的 A spec 可以包含 `continuation_task: {task_id, objective}`。该字段完整进入 Registry、规则、资源与批准哈希；旧批准不能自动升级。只有一次接续配额、没有明确需求时拒绝生成后续任务。任务文本最多 4000 UTF-8 bytes，候选路径、模型/账户、工具与总额度不变。

原 Reviewer Owner 的 `prepare_workflow_continuation_input(lease, token)` 不接 caller evidence 或候选：原 Source 完整结果与已 SETTLED/STOP/FREE 的 Reviewer、条件接纳 whole-event、三父证据、当前批准/token、原 A 窗口和未变的已结算 Reviewer Budget head 都必须成立。历史接纳 Controller 不冒充当前 Controller；续期不会重写原接纳。

同 lease/Owner 强留 `NativeContinuationInput`，复制 bytes/cap 不能消费。`handoff_workflow_continuation` 关闭原全部 Workspace、正常退役原 Source/Owner，使用强留 root、正常退休 tuple 和完整关闭回执摘要，在同 Budget 原绑定安装唯一新 Native Owner。旧 run/completion/deadline 不重置。失 close、正常 retirement 或安装返回，只续办原请求/返回同 child；Safety/未知责任不晋升。

新 Owner 的 `prepare_workflow_continuation_plan(token)` 自动准备原 Engineer plan、新 reservation/Workspace，并明确 WorkingCopy 仍是 baseline、受管 stdin 是已接纳候选。`issue_workflow_continuation_grant` 要求原新准备链；预留前当前 head 必须等于原接纳 Reviewer head，预留后必须等于该唯一原 reservation 的派生 head，不能因计数相同就通过。准备失返或 STOP 后不另建任务。

REGISTER CAS 和历史重放核原接纳事件/三父/新 plan 与批准：`CONTINUATION` 唯一，medium +1、完整 seconds+10 累计，原 started_at/high/历史费用保留。`run_workflow_native` 可运行该原 accounted stage，但仍要求单独批准下的原 launch，并沿原期限、Source、STOP、结算与归档门。此 API 不替调用方创造运行许可。

## 验收边界

本片本地验收要求：原实际受管 CPU PASS、显式 synthetic 不同模型会话/Reviewer ACCEPT/条件 CAS → 原接纳消费 → 新 Owner/新任务/CONTINUATION REGISTER → Python gate 实际启动但截获模型 G → 完整原 STOP、Pool 空闲、UNKNOWN 阻止重派、cold recover=audit=replay。原请求关闭/正常退役/安装失返也必须返回同 child。

这些是本地接线与安全证据。测试中的 parser 候选、合成 usage/review 或开发期独立审查均不算首个非预设真实模型工程任务，也不算产品独立 Reviewer 资格。

最终复验 `tests/test_hybrid_a_condition_acceptance.py -k next_task`：1 passed / 17 deselected / 1 既有 warning，382.45s；含三处原关闭、正常退休、安装返回丢失恢复及完整 STOP/UNKNOWN/冷重放。实际原准备 fixture 的出处损坏拒绝与证明 harness 共 8 passed / 5.85s；最后旧实际 Gate 启动/STOP/槽位复用回归 1 passed / 17.55s。其余纯数据/准备/ACK 24 passed / 0.24s；不把这些数字累加为互不重叠的运行资格。

原 30s 协作材料期限未改变。重复失败后只读剖析定位同条件三父闭包重复展开：仅原 active writer 的同 db/ReadBudget 可复用历史证明，必须保留 factory、完整 context 和原事件+完整 links 成功之后的完成 tuple 精确身份。Store 的 current projection lookup 保留 exact Guard 以进入此认证路径，但当前 heads、Controller、批准、物理材料和最终期限继续新鲜校验。新 Owner 使用相同认证闭包，PREPARATION intent/result 仍核完整原事件，intent.sources 的历史 Goal/Approval 也必须同预算认证；缓存登记或投影相同不能替代出处证明。普通、冷重放及 foreign 路径仍完整验证。

原始分轮结果、诊断与独立审查见 [接续证据](evidence/a-workflow-continuation-20261011.txt)。这不是全库回归、新安装、GPU、长跑或整个 A 阶段完成声明。

## 首个真实任务闭环剩余最小项

1. 有限 A 总入口已本地接通，见 [总入口](HYBRID_A_ENGINEERING_SEQUENCE.md)；真实模型正向端到端资格仍待证明。
2. 冻结真实仓库来源和非预设工程任务、外部配置的机器验收与明确后续需求；产出原任务修改、实际测试、不同会话 Reviewer、接纳与接续事实的统一交付包。不能用固定加法/π/parser 代替。
3. CPU FAIL/Reviewer REVISE 已有明确未接纳终态；声明的 repair quota 不是已实现的修复派发。UNKNOWN/STOP 不得靠修复重开会话。
4. 原小额 A 合同批准后才做真实 Engineer/Reviewer/接续调用和上述证据验收；本地代码开发不以前置运行批准为条件。

真实运行保持当前 ChatGPT 工作区、不换账户/API 付费、不购额度；最多 8 会话（6 Medium/2 High）、每会话 300s、输入 400k/输出 32k soft、总 wall 90min/受管 CPU+模型 60min。缺可信 usage 或未解决 STOP 不开新会话。不把 soft token 或本地会话数宣称为供应商硬收费/重试上限。该合同当前仍未批准。

全目标保持 ACTIVE；通用实验、GPU、instinctRL 独立评审/实机准入、科研/恢复/长跑仍未完成，后置非直接阻断的恢复增强。
