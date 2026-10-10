# 原产物条件分母与缺证阻断

## Checkpoint81 原生评审前置与有界验收

当前真实检查确认 `CodexExecAdapter.start` 与 `WorkingPlanService.start` 均拒绝执行；现有 fixture UsageOwner 只启动合成计数程序，不是 native producer。CLI 版本与本地模型目录匹配也不是账户、只读、interrupt 或费用资格。新增批准本身不能关闭实现缺口，原 BOUND 冷入口拒绝不得绕过。详 evidence/checkpoint-81-reviewer-readiness.txt。

下一实际验收先取一个原工程固定输出及完整原始证据，通过新独立会话取得原来源绑定的结论，再在第二个会话中验证在途 STOP；仅限此候选，不等于 CPU Review 或完整 Goal 完成。当前提议最多2个串行 gpt-6.1-sol medium 新会话，各180秒，总 input64000/output16000为软观测阈值；无自动重试、resume、额外角色或模型/账户 fallback。会话数不等于 provider 请求数，缺计数仍保留 UNKNOWN。原零模型批准不扩额，必须新 scope 与原生 Task/Attempt/Lease、预算、Pool 和 producer 来源闭合后才放行。

候选、原证据和控制对 agent tools 禁写且控制不可读；独立私有 scratch 可写，可信 harness 的输出路径单独约束，并非全进程只读。CPU command5秒和现有 MCP transport15秒分别报告；RLIMIT 不冒充整个 CLI/cgroup 硬限制。只有原 CLI/MCP/tool 完整固定 scope 的物理终态可以释放；leader exit/EOF/历史 PID 不充分。结论仅由原签发独立 receipt 驱动条件证据，不接受模型自行批准。

订阅认证不能证明零额外费，included额度、credits和overage需选定账户并核明；无法证明所要求的费用边界则不启动，实际费用仍 UNKNOWN。硬 token 或硬费用配置未有强制能力就拒绝，不把软上限伪装成保证。官方 [非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode) 支持 JSONL 与结构化输出；其 usage 示例不提供稳定 event_id，实际 source位置/turn语义仍需原生来源验证。文档不代替产品执行验收。

初始提案每会话一个 input turn、模型驱动工具调用零、request/stream retry零；原小型工程候选和完整原始证据必须能放入有界 packet，否则拒绝本次验收输入，不静默加工具或扩上下文。请求计数仍需独立强制资格，不能从两个会话推定两个 provider请求。杀本地进程不证明远端计算或计费停止。账户边界参考官方[计费](https://learn.chatgpt.com/docs/pricing)与[认证](https://learn.chatgpt.com/docs/auth)，不推断当前操作者权益。

模型权限未定前，下一82以实际本地 CLI在途诊断/STOP/原源读回闭环推进生命周期：新合法 protected owner和原 Pool/task/reservation来源、无凭据loopback接收端、实际stdout inode/PID/pidfd、物理收尾或UNKNOWN保额、安装consumer读回。正常模型/Reviewer启动仍拒，不重复既有rejecting census充当新交付，也不把本地诊断计为T13或实际模型用量证明。

Checkpoint 65 将原固定 CPU 试验和工程产物接到真实合同条件的只读缺证门。Dashboard 可手动读取实际条件、规则哈希、原机器结果和缺口；机器结果不自动成为 ConditionEvidence，独立产品 Review 未执行，Goal 不能完成。

## 交付行为与验收条件

- 原 `create_finite_host_app` 显式安装 `GET /api/v1/projects/{project_id}/delivery-evidence/{kind}/{source_id}`。`kind` 仅为 `CPU_TRIAL` 或 `ENGINEERING`，只接受原结果 ID，不接收路径、session ID、verdict 或查询参数。原 viewer 权限前后复核；默认未安装的应用没有该接口。没有 Evidence POST、运行、审批或 Goal 状态写入。
- 同一个原 readonly transaction 和累计 64 MiB source/展开预算核验原产物、原合同、当前合同、审批及机器验收。当前合同的实际 `global_conditions` 决定分母，原规则和 evidence_required 原样展示；每个条件固定 `UNASSESSED`，满足数为零。
- CPU 显示原 384 点、固定 command 哈希和机器验证；工程显示原单次写入的 output tree 哈希、3 项实际测试与 21 项 AST 机器检查。原机器上下文明确标记 `UNBOUND_MACHINE_CONTEXT_NOT_CONDITION_EVIDENCE`。合法 CPU `UNAVAILABLE` 也可展示，不能转换成 PASS。
- 当前 consent 必须通过完整 protected Registry/config 与原审批闭包，并通过最后时刻的有效期检查。合法 Registry 漂移使 consent 不可用、原结果仅作历史展示；新合同使旧机器上下文不再映射到当前条件。
- 当前 Goal/authority head 不仅须对应真实原事件，还须证明没有较晚的原 head 写入。每个 head 从已核验原 receipt 的事件起点读取最多 256 条连续主键后继事件，包括无关事件；逐行版本连续且末尾覆盖同事务 as-of。较晚的真实 draft/revoke 不能被回填旧 head 隐藏。起点、窗口缺口、原源损坏或超限均报 503，不宣称当前状态。超限需要后续有界索引方案，不能自动全历史重放或静默降级。
- Dashboard 只有手动条件 GET，没有自动条件刷新、重试或 POST。持久版本上升清除已读条件；切换项目、身份、epoch、所选产物或退出时清除私有内容，旧回复不能回填。条件回复落后于当前持久版本时显示不可用，须手动恢复。

## 缺口与权限边界

所有回复固定 `BLOCKED_MISSING_EVIDENCE`、`NOT_PERFORMED`、`goal_completed=false`，模型调用、dispatch 和 condition evidence 写入开关均为 false。不同的 implementer/reviewer 字符串即使通过通用结构 schema，也不是实际签发的独立 Review；本接口不接受它们。

原两个 fixture 的模型 sessions/input/output token 和 GPU 额度为零。本切片没有调用 native 模型、付费模型或 GPU，没有迁移生产状态。真实独立产品 Reviewer 仍需要新的隔离批准合同、预算及实际只读、interrupt、可信用量证明；开发 High 审查与 AST 机器检查不能替代它。完整 M0–M5、严格 OS/任意树、供应商账单、B1/24h fixture/8h UI 和依赖后的安装迁移验收继续保留。

实际终态、必要回归和 SHA 归档以 `evidence/checkpoint-65-final-tests.txt` 为准。
