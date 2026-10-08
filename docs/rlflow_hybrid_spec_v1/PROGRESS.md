# Hybrid v1 开发进度

2026-10-08。完整目标保持 M0–M5 / T00–T25，不以首个切片作为完成。

当前分支 `hybrid-v1`，基线 `d25cf02`。开发由 Codex Goal 负责，未启动 rlflow 来调度本次开发，未调用业务模型或训练。

需求包原位保留；`docs/hybrid-v1` 是指向本目录的 Git 跟踪相对符号链接，保证路径可用且不复制两份需求。原 `VALIDATION_REPORT.md` 是需求包静态校验报告，系统验收记录见本文件关联的 `IMPLEMENTATION_VALIDATION.md`。

| 任务 | 当前状态 | 证据 / 下一动作 |
|---|---|---|
| T00 | 基线已记录 | Python 3.12.3；原 307 passed / 32 skipped / 2 failed；两项版本不兼容已修复 |
| T01 | 本切片回归已通过 | Store / accounting / process recovery / startup 原测试保留，doctor 全部通过；后续 fencing/STOP 仍须新验收 |
| T02 | 无生成探测与隔离兼容完成 | 315 schema；version+protocol SHA pin；initialize-only 独立握手成功；真实 usage/interrupt/子代理未证实，禁用不支持能力 |
| T03 | 初始闭合合同已实现，后续扩展中 | GoalContract/Task/Lease/Attempt/Approval/Evidence/Experiment/Usage/Budget/CommandReceipt、公共快照与已注册 payload；完整 API 实际接口尚待 T06/T16 |
| T04 | 初始事务观测桥已验证，性能验收未完成 | 只读 bounded snapshot/page、增量 counters、同事务 outbox、epoch、真实进程故障测试；B1 100k 与备份恢复集成待验证 |
| T05 | 启动释放事实切片已验证，完整观测未完成 | trusted core 校验完整绑定链并持久化一次 CLI_RELEASE_ACK；短命/换代/文件安全覆盖；仍 STARTING，vendor 活动/日志/资源另待验证 |
| T06 | 只读基础切片实现，未完整验收 | 同源登录/project scope/短期 Bearer、snapshot/page、bounded durable SSE、loopback CLI；无写命令/任意 artifact；见 LOCAL_WEB.md |
| T07–T08 | 初始只读 UI 已实现，未完整验收 | 真实 snapshot/SSE reducer、卡片/预算/事件/分页/详情、离线/身份隔离；Fixture Chrome QA 通过；日志/资源、虚拟化、真实运行与完整 M1 验收待完成 |
| T09–T17 | 未开始 | 合同、策略、受控 Runtime、单写、独立评审、预算、skill、控制与恢复 |
| T18–T20 | 未开始 | 本地与 fixture 实验 adapter、科研状态、证据页面 |
| T21–T22 | 未开始 | 资源隔离、故障/性能/24h 与 8h soak |
| T23–T25 | 未开始 | 安装/迁移、可信远程、历史回放 |

后续恢复应先读取本文件、Git、验收记录与实际测试输出。没有记录为已完成的条目不得推定完成。

最新进展：新增协议/观测回归、旧版本兼容修复及 High 独立审查的 MUST_FIX 已关闭。冻结最终代码后的全回归 **349 passed / 32 外部依赖 skipped / 109.97s**。报告与命令见 IMPLEMENTATION_VALIDATION.md，原始精简输出已纳入 `evidence/checkpoint-01-final-pytest.txt`。

本轮新增：认证与只读 API/SSE 基础候选已落盘；首轮全回归 366 passed / 32 skipped，追加 heartbeat 闭合合同检查后冻结回归发现既有 guardian teardown race（365 passed / 32 skipped / 1 failed）。未忽略失败：High 诊断同时揭示默认 command guard 落入角色可写 scratch 的控制隔离缺陷，现改 trusted 父进程外部私有目录、额外 scope 禁止覆盖控制目录、基于完整真实身份确认写入者 quiescence 后清理，并强化死亡测试。最终冻结 r3 **368 passed / 32 skipped / 115.80s**，编译/补丁/依赖检查通过；High 相关 MUST_FIX 全部关闭。证据见 CHECKPOINT_02.md 与 IMPLEMENTATION_VALIDATION.md。

High 独立 Web 复核的项目读源 TOCTOU、健康 backlog 误判/过量预取均已关闭；见 SECURITY_REVIEW_WEB_FOUNDATION.md。真实 loopback HTTP 事件提交与重连测试已通过。源码没有 scheduler/model/GPU 启动副作用。

最新 checkpoint 03：68 项 startup/protocol/observation 回归及独立 High 审查通过；冻结全回归 **399 passed / 32 skipped / 135.90s**。新启动观测不改 source status/phase/预算/批准，明确 CLI_RELEASE_ACK 不是模型 RUNNING。证据见 CHECKPOINT_03.md。

下一项：完成 T07/T08 列表虚拟化和完整动效/连接恢复检查，补齐 T05 日志/资源及真实来源端到端，再进行 M1 验收。初始 UI 的真实 Chrome sandbox Fixture 测试已通过，不代表真实模型运行或 8h soak。M1–M5 和完整 Goal 仍未完成。

最新 checkpoint 04：冻结全回归 **402 passed / 32 skipped / 139.90s**，browser+reducer **9 passed / 0 skipped**，High 初始 UI 三项 MUST_FIX 全部关闭。实际登录/snapshot/SSE/详情/离线恢复/手机/身份隔离证明见 CHECKPOINT_04.md，未覆盖完整 M1。
