# 首个真实工程自主闭环：最小交付清单

2026-10-11审批表达已本地接通：新A_ENGINEERING_WORKFLOW_V2原Registry/ApprovalService可冻结一次model+CPU契约，历史回放验证同envelope，明确Engineer PATCH与独立Evaluator REVIEW输出、可信验收、双向protected边界、配额/修复/接续限制；仍execution_qualified=false。下一直接实现原受保护事实派生逐次packet/grant（含parent key/hash/version和原新reservation/Controller/CAS/STOP），而非继续仅增加准备组件。原账户/生成来源、结算、产品独立Review、条件CAS/接续和首个真实任务仍全部必需，当前NOT_EXECUTED；小额A运行合同未经批准不调用，GPU/B/C/instinctRL HOLD不变。

2026-10-11首要纠正：须先建立versioned workflow批准envelope与原持久事实派生每次packet/grant的接线。当前V1单一role/候选hash审批无法对未知产出发Evaluator或续作grant，现CPU验收合同又要求模型预算全零；已原调用链实证拒绝并独立确认。不能用多个人类批准的单packet试跑充自主闭环，也不能删原hash/审批门。新workflow需同一原批准/Registry不变下完成Engineer未知candidate→受管CPU检查→不同原session Evaluator→受保护条件接纳→有界下一packet，并保留父facts key/hash/version、新reservation/Controller/CAS/STOP。已有V1维持旧语义不升级；账户/source/结算仍缺，本地继续、实际A合同未批不运行。完整目标与其他验收不变。

最新实现边界：新fixed native gate已真实在Linux内核限制下no-G退出，不执行Codex；原source/controller事务可冻结ELF/config/helper/ready和empty私有会话目录并独立清理正常/partial分配。实际输入会经sealed memfd防等待G期间篡改，G不作模型上下文。第1项剩原账户/credential-owner、原生产者与ready/G接通和完整stdout/EOF；第2–5项仍缺原用量publisher结算、独立Evaluator、条件CAS接纳/接续及真实任务结果。start/spawn/release仍deny，不能用no-G证据计真实任务或A闭环完成。

2026-10-10最新：原Goal当前工具核对ACTIVE；历史blocked不再是现状态。本地exact生成owner/source已实现原登记、冻结packet/schema与独立物理绑定、部分分配FD闭包；held原stdout有限数据读取/全prefix审计已接线，但source/account/usage qualification仍false，实际start/spawn/release和source poll/seal拒绝。下面第1项仅完成登记/材料与读取部分，不能标完成；第2–5项仍缺真实publisher/独立Evaluator/条件CAS接续/非预设实任务。其他恢复后置，未以运行许可暂停这些本地实现。

2026-10-10 A阶段续作（WIP，尚未完成新checkpoint）：用户明确本地生成来源、结算、Reviewer、条件证据和接续实现不等待运行批准。当前新增生成型独立合同/预算分支及有限CLI packet解码：旧零模型授权不升级；handoff后缺原用量，物理STOP仍UNKNOWN/全预留；原BudgetService拒所有caller JSON runtime动作。单thread/单turn/无tools的结构化Engineer输出可进入96任意候选变换；Evaluator输出校验同candidate hash与无未解MUST。decoder为数据，source_authenticated/settlement/condition均false，不是原来源或独立Review。

当前最小剩余实现按交付行为排序：

1. 新exact生成owner/source接原controller、WorkingPlan、Pool、Budget和原账户/冻结packet/schema，不借diagnostic零模型grant；同PID原ELF/ready/原stdout/参与者STOP需本地接通并验证。验收：未授权不产生模型调用；原批准生成attempt只运行所绑定packet，变更或STOP后不放行。
2. 原CLI成功或失败结果与可信usage持久化、原guard结算。验收：完整原计数按语义记账，缺失/失败未知保留预留，不把stdout JSON或物理STOP当退款依据；完整scope停止后的硬件与财务责任分别处理。
3. 全新独立Evaluator会话只读冻结candidate/原测试/契约；必要有界修复。验收：不同原生产者/会话、同候选版本和原审批来源可核，不接受caller PASS或开发期High结论替代产品Review。
4. 受保护条件证据+Core版本CAS接纳+一次预算内自主接续。验收：原机器结果及原Review同时满足所绑定条件；拒迟到/STOP/候选改版，接续按未完成真实需求而非固定成功分支。
5. 首个非预设真实工程任务。验收报告必须列实际需求/修改/测试/独立Review/条件接纳/接续和用量；当前仍NOT_EXECUTED，合成normalizer输入不算任务完成。

首次A小额运行合同已单独提出，待用户回答：仅当前ChatGPT工作区既有额度/积分，不切换账户/不开API计费/不充值；gpt-6.1-sol最多8个产品CLI会话（6 Medium、2 High），单会话300秒，累计输入40万/输出3.2万token为软停止阈值，墙钟90分钟/受管模型与CPU累计60分钟。缺用量或未解STOP停止新会话。CLI会话数不等于后端请求数，内部重试/费用没有硬封顶承诺。限定一个CPU真实工程任务、独立评审、有界修复及一次接续。GPU=0；B/C与instinctRL HOLD不变。此合同只阻止未批准的实际运行，不阻止上述本地代码开发；不再要求旧整包模型/GPU合同先获答。

工具状态注意：本轮get_goal仍返回此前blocked；接口不提供resume状态写入，本轮未新建/替换原Goal，也不据此中断本地实现。此追踪器标记不代表本地开发存在新权限阻塞。

96进展：任意补丁已能按原hash/批准路径冻结，交现原受管CPU验证（不再固定AFTER或父Core exec），实测成功PASS/匹配文本后失败FAIL及完整STOP/SETTLED/FREE。接口和严格限制见HYBRID_ARBITRARY_ENGINEERING_CANDIDATE.md；本项仅为真实模型候选可承接的执行行为，不是首个实际任务。真实source/最终Working晋升与CAS、Reviewer及条件接续仍未实现，不以数据类替ModelReceipt。

独立架构复核进一步确认最小前置：生成型exact owner/source/kind须独立批准，旧diagnostic零额度不可升级；真实provider凭据持有者/目的地/transport retry与次数边界不可由本地credential-empty receiver证明；旧Budget STOP math全部model维度为0，生成分支必须另按原CLI完整计数结算，缺计数保UNKNOWN与全预留。首次可采用完整小packet/no-model-tools入口，但仍必须真实Engineer→受管任意验收→全新只读Evaluator→原条件证据→至少一次批准范围内自主接续，不冒称通用工具或全Goal完成。

95 后的优先级由用户明确收紧：优先首个非预设工程任务和独立产品评审；只有直接阻断这条链或确证安全问题继续补边界。其他恢复增强进入后续。完整最终系统目标不缩减；固定加法、π、AST 修补演示和故障注入不计本验收。

当前源码核验：`execution_adapter.py:348` 与 `hybrid_working_plan_service.py:89` 的 start 仍无条件拒绝。82 native 只允许零模型本地诊断；`hybrid_usage_source.py` 原来源只证明 fixture 生产者，JSONL accumulator 本身不证明真实模型调用；`hybrid_delivery_evidence.py:180` 条件仍 UNASSESSED，独立 Review 仍 NOT_PERFORMED。95 解决真实父死资源退役，不使这些能力自动成立。

最小实现按一个纵向切片交付，不能用准备组件数量替代实际任务：

1. 真实模型 Engineer 的受管启动和原生结果：新的明确批准合同/预算、当前 controller/writer/Pool 资格→HANDOFF_UNKNOWN 持久→原 producer 登记→放行。限定隔离工程副本与允许工具，原生 CLI/工具参与者全部进入可停止范围；不得绕开现有 deny 或借 legacy unbound。产出任意真实 patch，不写预定答案。
2. 原任务结果与可信用量：保留原 stdout/event position/thread/turn、diff/候选 hash、实际命令与测试输出；按当前 CLI 实际 usage 语义计额，缺用量保留 UNKNOWN/预留。原结果不是模型自报成功；有界会话/重试/时间门及 STOP 对这一次 Engineer/Reviewer 都有效，不要求先扩展所有恢复场景。
3. 真正独立的产品 Reviewer：第二个真实执行，不继承 Engineer 对话；只读同一冻结候选、契约和原测试证据，独立给出通过/失败及理由。原审批与 source receipt 绑定版本、Task/Attempt/候选 hash；不是开发期 High 审查，也不能接受任意 JSON PASS。
4. 条件证据和自主接续：可信机器事实加原独立 Review 转为对应 ConditionEvidence；Core CAS 接纳仅本 attempt，拒绝迟到/STOP 后结果。Review 失败进入有界修复，成功按真实 Goal 未完成条件接续，而不是预先写死的成功分支。
5. 首个实任务验收：从隔离真实项目中已有、可复现且未解决的工程需求/问题选择输入，Engineer 自主定位、实现、运行可配置验收，Reviewer 独立评审；报告原需求、具体改动、真实测试、Reviewer 结论、条件接纳/接续结果和实际用量。任务选择不得制造已知答案；若失败报告实际诊断和缺口，不换固定演示凑通过。

可复用已有 Goal/Contract/Authority/Budget、WorkingPlan 持久物料、原来源校验、共享池、受管 scope 与只读证据消费；实际生成 native profile 仍必须逐项资格，不能宣称 CPU/诊断 profile 已替它证明全部边界。

首个任务目前 NOT_EXECUTED：实现入口和真实产品 Review/ConditionEvidence 尚缺；集中模型、GPU、时间与实验资源合同仍未获明确答复，不把“优先”推断为付费/账户/额度授权。普通本地实现继续；授权问题按已有一次集中合同处理，不重复零散索权。GPU 与 instinctRL 验证不成为首个 CPU 工程任务的额外前置条件。

后续队列：其余冷恢复增强、严格 quota/财务终态恢复、科研 GPU 闭环与长跑资格。只有真实发现其直接阻断本链或安全问题才前移。达到实机准入后才交 instinctRL 版本/证据/步骤/剩余资格和另窗 Goal prompt，当前不宣称准入。
