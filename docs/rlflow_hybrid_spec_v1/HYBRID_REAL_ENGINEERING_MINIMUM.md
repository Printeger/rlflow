# 首个真实工程自主闭环：最小交付清单

2026-10-11 A 自动 CPU 执行桥：exact handoff Owner.execute_workflow_cpu(token) 从原 Engineer parent/同 envelope 自动创建新 reserve→Workspace→WorkingPlan→Pool claim→grant/lease→managed CPU checks/full STOP，不接 caller candidate/checks/额度。首reserve前核原唯一stage/window/累计余额。并发不等序列锁；准备异常锁存不另开任务；completed 强绑定原sequence/lease/冻结结果，重复只读不信可变缓存。独立发现安全freeze后仍新增准备、重复结果cache污染两MUST，已修为STOP先freeze、每个准备短admission段核exact-live/freeze并强留句柄，RUN不持锁；独立差量确认两项源码关闭。首自动实际CPU/丢reserve COMMIT 2pass110.02s，前移head门受影响正例1pass79.81s，旧nohandoff1pass9.85s、修STOP后旧实际fullSTOP1pass15.78s；末原34081自然终态2pass/6deselected/1既有warning110.89s，actualCPU PASS/SETTLED/Pool0/replay、cache/lease/complete污染及并发拒、reserve后SafetySTOP与起始freeze零新增准备均通过。见 HYBRID_A_CPU_EXECUTION_BRIDGE.md / evidence/a-workflow-cpu-bridge-20261011.txt。模型父显式synthetic/G截断，只CPU实际运行，不计首真实task/A完成。下一不同Reviewer原parent/角色plan/新会话及配额→机器+Review条件CAS→一次需求接续。小额A实际调用待既有合同批准仅阻运行，不阻本地代码；GPU/B/C/instinctRL HOLD不变，Goal ACTIVE。

2026-10-11 同 A 原 Budget 的 Engineer→CPU 执行接线：受保护顺序 handoff 先核完整 SETTLED/FREE/FD 退休、原 Workspace close 回执，再原子安装唯一 CPU Owner，不清 Budget 指针、不复用旧 reservation/WorkingPlan。新 CPU workflow binding 持久原 parent/modules，cold replay 重算同批准 envelope；唯一 CPU stage 保守累计 task_seconds+10 且重核原窗口。显式合成模型父的实际 managed CPU 检查 PASS、完整 STOP/SETTLED/Pool0/audit=replay，四种 lost-return/no-COMMIT 故障原26166终态4pass/1warning322.47s；原预算/旧CPU/native兼容回归24367终态42pass/1warning55.97s。最后不可变退休凭据门原1388终态2pass/3deselected/1warning100.26s，含Safety退休标记不能伪造handoff及normal shutdown丢返回的实际CPU正例，独立窄审两项 MUST 已关闭。非真实模型/产品独立Review/首任务验收；下一自动派生新reservation/Workspace/plan/claim的执行桥，再不同Reviewer父接线→条件CAS→一次需求接续。实际小额A未批准不调用，GPU/B/C/instinctRL HOLD不变；本地开发无权限阻塞，Goal ACTIVE。证据 evidence/a-workflow-cpu-runtime-20261011.txt。

2026-10-11 原父证明与同envelope CPU材料已接NativeModelOwner，重核原Source、Budget whole-event/history/current、实际PoolFREE/STOP、批准/window，封存同cap；不授CPU grant。验收19pass（含actual LIVE no-handoff父拒绝），synthetic正例不资格化真实来源。下一直接落地同原Budget顺序Owner handoff+新CPUreservation/Workspace/plan/grant+唯一stage累计预算；再原managed CPU结果→新独立Evaluator→条件CAS/一次未完成需求接续。不可另建Budget或清pointer、不可复用已settled Engineer计划/fixture条件。首次真实任务仍NOT_EXECUTED；模型小额A未批准不调用，GPU/B/C/HOLD保持；其他恢复增强后置。

2026-10-11 同workflow CPU接线定位：已补原candidate helper不能表达已批准 JSON_METRICS_RANGE 的缺口，实际managed CPU按原指标范围分别PASS/FAIL，原stdout回归通过；不是A自主任务。接下来不能另批零模型CPU或复用已结算Engineer计划：需原持久Engineer terminal（live/SETTLED/完整usage/result/原事件与history links）→原envelope checks/acceptance/candidate/pins派生CPU binding→原新reservation/Workspace/plan/claim/lease→前Owner全部STOP/FREE/FD退休后的受保护顺序交接→唯一CPUparent/stage+预算/窗口→原managed结果持久化，供不同Evaluator父证明。旧CPU/profile/live限制不宽泛放开；UNKNOWN/过期/改candidate/checks/pins/重复stage均拒。后续Reviewer/条件CAS/一次接续与首次非预设实任务仍必需，task NOT_EXECUTED；A模型调用待原合同批准，GPU/B/C/HOLD保持。

2026-10-11 原result/candidate持久化已本地接进完整STOP的原usage同terminal event，原canonical消息/候选变换可重放，历史旧facts不晋升；cap前和finalframe归档门超界走UNKNOWN清理。下一最小清单收敛为：同A workflow未知candidate受管CPU验收→原parents派生不同Evaluator真实会话/Review→机器与Review条件CAS接纳→基于未完成需求一次接续。正向真实归档待实机；最终交付依然必须有非预设实际需求/修改/测试/产品独立Review/条件接纳/接续/用量，目前 task NOT_EXECUTED。小额 A 未批准不调用，GPU/B/C/HOLD不变，其他恢复后置。

2026-10-11 显式 fresh live 域已本地打通原登记/不放行 STOP/冷回放，旧 fixture action 与非 native 执行器不晋升；新 create_live 仅创建隔离原件，无迁移。必要回归74pass、新 live1pass，开发期独立审查无确证 MUST。下一最小实装清单仍是：原 result/candidate 持久事实（不是内存 cap）→同 workflow 受管 CPU 候选验收→新不同 Evaluator 原执行/评审→机器条件+Review 的 CAS 接纳→一次未完成需求接续。最终验收报告须有非预设真实任务、实际修改/测试、产品独立 Review、条件接纳/接续与用量；当前 task NOT_EXECUTED。小额 A 合同未批准不调用，GPU/B/C/instinctRL HOLD 保持，其他恢复增强后置。

2026-10-11 第2项原后验issuer条件接线已补，不再恒None：原release witness+Source独立kernel origin→原ACK/STARTED→自然exit0/full audit/完整usage/candidate exactcap→scope STOP原Budget消费。当前仅真Python拦G负例/纯数学，正向真实Source与known settlement待授权实证。最小剩余新增已确认直接阻断：BaseOwner仍硬fixture域、result候选仅内存；先显式REAL域与持久原result/candidate事实，不升级fixture历史。再同workflow未知candidate CPU、新不同Evaluator派生/原Review、条件CAS及未完成需求一次接续。首非预设task NOT_EXECUTED；固定加法/π/合成输入不计闭环，小额A模型运行待既有合同批准，GPU/B/C/HOLD保持。

2026-10-11 第1项原批准启动接线已本地实现（原samelease launch cap→HANDOFF/Pool/gate/ready/原最后G门），不依赖先假定后验account资格；原V1/无cap仍拒。当前只拦截G的实际Python测试，真实调用未获批、首task NOT_EXECUTED。最小剩余优先：执行后原source+账户/完整stdout/EOF与可信usage cap发行及原结算→同workflow未知candidate CPUgrant→新不同Evaluator派生/原Review→条件CAS接纳→未完成需求一次接续。实际auth refresh清理只能在确证阻断首次运行时前移，不扩大其他恢复；小额A合同待批，GPU/B/C/HOLD不变。

2026-10-11 第1项原同PID ELF/stdio观测已本地接线，但仅数据；实际批准启动/G、账户后验资格/完整stdout/真实EOF仍缺。优先剩余最小纵向实现：原批准启动→原成功/失败来源及usage cap→同workflow未知candidate受管CPU→新独立Evaluator→条件CAS接纳→依据未完成需求一次接续。须区分启动权限与后验资格，不能借缓存/JSON预授来源，也不能把A运行授权作为这些本地代码的前提。首真实非预设任务NOT_EXECUTED；当前仅Python noG与内核数据测试，小额A合同未经批准不调用，GPU/B/C/HOLD不变。

2026-10-11 账户输入本地transfer已接原REGISTER/Controller最终效果门：当前host文件cache只读私有复制到原冻结session目录，敏感内容不入证据，原STOP先reap再精确删副本；仅合成cache验证。第1项仍需实际账户server/同ELF exec与G及完整stdout/真实EOF，cache_staged不是account_qualified。第2项可信usage cap发行，第3项同workflow未知candidate CPU与新独立Evaluator会话，第4项条件CAS/接续仍未完成；首非预设任务NOT_EXECUTED。A调用待既有小额合同批准，本地继续，GPU/B/C/HOLD不变。

2026-10-11 Reviewer输出消费接线已补：原held FD全prefix审计后，只按冻结Evaluator packet角色/schema/原grant候选版本返回闭review数据；ACCEPT与REVISE保留，错版本、ACCEPT+MUST、失败和追加/替换拒绝锁存，不信mutable transcript角色。数据copy不能发行独立性凭证/条件/新session。第3项仍需同workflow自动派生不同原Evaluator会话及真实source资格；第1–2项原账户/生成/EOF/usage发行与第4项条件CAS接续仍未完成，首实任务NOT_EXECUTED。

2026-10-11 原 fixed Python producer 已经原 HANDOFF→PROCESS→STOP接通，ready绑定原 PID/nonce/内核/冻结材料，STOP Pool0但账务UNKNOWN全额；Source/Owner独立deny保证不发G/exec模型/读账户。第1项剩余收敛为原账户+same ELF/G/完整stdout/EOF资格，第2项原opaque usage cap发行，第3–5项仍须同workflow CPU/不同Evaluator/条件CAS/接续及首个非预设实任务。当前实际任务 NOT_EXECUTED，不以本地生产者或开发期High复核计闭环。A合同待批仅阻调用，GPU/B/C/HOLD不变。

2026-10-11 财务处理部分缩减：原Budget/phase builder/Native Guard已有完整usage publication消费与缺账保全分支，计CLI session1+全input/output/wall/overrun，不借零模型/旧历史；Source真实issuer仍缺且hook恒None，因此不是原用量发行或实际结算完成。下一须实装原账户/producer/G/EOF/audit→opaque cap，并接未知candidate同workflowCPU、不同Evaluator、条件CAS及接续；现首次真实task NOT_EXECUTED。小额A调用待批仅限runtime，GPU/B/C/HOLD不变。

2026-10-11 失败来源数据补齐：成功之外原turn.failed/error可完整审计保存失败hash/未知usage，失败即使携合法PATCH/ACCEPT也不得候选或Review；错误观察不是实际CLI exit/EOF。下一仍须原账户+producer/EOF资格+usage publisher/原结算接线，并扩原workflowCPU/Evaluator/条件CAS/接续，不能仅凭此数据结果派发角色。首次真实任务NOT_EXECUTED，A合同待批只限制调用，GPU/B/C/HOLD不变。

2026-10-11 接线缩减：原held stdout全prefix审计与原workflow grant快照/schema/路径到Candidate数据现可实际调用，拒caller换reader/越界/追加；仅合成数据验证、不具来源资格。下一最小实现为原账户/实际生产者+EOF/usage可信publisher及原结算，再同workflowCPUgrant、不同Evaluator、原条件CAS与一次接续；既有counter/STOP必须贯穿。首次真实task仍NOT_EXECUTED；A额度待批不阻本地实现，GPU/B/C/HOLD不变。

2026-10-11 next：原first Engineer计数/保守reservation累计时间/窗口/唯一首登记已持久入Budget，projection来源与最终sample门实装，过期STOP仍独立；其他阶段未启用。最小剩余继续原实际账户+producer-ready-G+output/usage可信publisher及settlement→未知candidate workflowCPU→不同原Evaluator→条件CAS接纳→一次未完成需求接续。各阶段须扩展同原counter和受管时间、不得从fixture/Develop High审查伪造parents。实际first task NOT_EXECUTED；A合同未批准不调用、GPU/B/C/HOLD不变。

2026-10-11推进：首workflow Engineer原manifest→冻结packet/schema→原grant/登记与fresh/historical重算已可实际STOP并coldreplay，不再仅审批数据。下一先补原stage/角色quota/controlled累计时长与唯一首stage消耗，再完成真实原账户/生成source/settlement及后续candidateCPU/Evaluator/条件CAS/接续。所有release仍拒，FIRST_ENGINEER不代表once-only证明；首次真实任务NOT_EXECUTED。现有小额A合同待批只限制实际调用，不阻本地实现，GPU/B/C/HOLD不变。

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
