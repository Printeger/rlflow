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
| T05 | 启动释放、CORE_STATUS与private工具返回事实基础已验证，完整观测未完成 | CLI_RELEASE_ACK/固定日志同事务一次性；bound private return不授予authority或证明STARTED；public工具collector/资源/vendor活动待验证 |
| T06 | 只读基础切片实现，未完整验收 | 同源登录/project scope/短期 Bearer、snapshot/page、bounded durable SSE、loopback CLI；无写命令/任意 artifact；见 LOCAL_WEB.md |
| T07–T08 | 初始只读 UI、事件虚拟化与公共日志已实现，未完整验收 | 真实 snapshot/SSE reducer、卡片/预算/分页/详情、虚拟窗口/阅读锚点/键盘、日志筛选/lazy正文、离线/身份隔离；Fixture Chrome QA 通过；资源、真实运行与完整 M1 验收待完成 |
| T09–T17 | 未开始 | 合同、策略、受控 Runtime、单写、独立评审、预算、skill、控制与恢复 |
| T18–T20 | 未开始 | 本地与 fixture 实验 adapter、科研状态、证据页面 |
| T21–T22 | 未开始 | 资源隔离、故障/性能/24h 与 8h soak |
| T23–T25 | 未开始 | 安装/迁移、可信远程、历史回放 |

后续恢复应先读取本文件、Git、验收记录与实际测试输出。没有记录为已完成的条目不得推定完成。

最新进展：新增协议/观测回归、旧版本兼容修复及 High 独立审查的 MUST_FIX 已关闭。冻结最终代码后的全回归 **349 passed / 32 外部依赖 skipped / 109.97s**。报告与命令见 IMPLEMENTATION_VALIDATION.md，原始精简输出已纳入 `evidence/checkpoint-01-final-pytest.txt`。

本轮新增：认证与只读 API/SSE 基础候选已落盘；首轮全回归 366 passed / 32 skipped，追加 heartbeat 闭合合同检查后冻结回归发现既有 guardian teardown race（365 passed / 32 skipped / 1 failed）。未忽略失败：High 诊断同时揭示默认 command guard 落入角色可写 scratch 的控制隔离缺陷，现改 trusted 父进程外部私有目录、额外 scope 禁止覆盖控制目录、基于完整真实身份确认写入者 quiescence 后清理，并强化死亡测试。最终冻结 r3 **368 passed / 32 skipped / 115.80s**，编译/补丁/依赖检查通过；High 相关 MUST_FIX 全部关闭。证据见 CHECKPOINT_02.md 与 IMPLEMENTATION_VALIDATION.md。

High 独立 Web 复核的项目读源 TOCTOU、健康 backlog 误判/过量预取均已关闭；见 SECURITY_REVIEW_WEB_FOUNDATION.md。真实 loopback HTTP 事件提交与重连测试已通过。源码没有 scheduler/model/GPU 启动副作用。

最新 checkpoint 03：68 项 startup/protocol/observation 回归及独立 High 审查通过；冻结全回归 **399 passed / 32 skipped / 135.90s**。新启动观测不改 source status/phase/预算/批准，明确 CLI_RELEASE_ACK 不是模型 RUNNING。证据见 CHECKPOINT_03.md。

下一项：补T05工具metadata/资源、首次历史/error、动效/连接恢复与真实来源端到端，执行M1验收。虚拟窗口/公共日志不代表真实模型运行或8h soak。M1–M5与完整Goal仍未完成。

最新 checkpoint 04：冻结全回归 **402 passed / 32 skipped / 139.90s**，browser+reducer **9 passed / 0 skipped**，High 初始 UI 三项 MUST_FIX 全部关闭。实际登录/snapshot/SSE/详情/离线恢复/手机/身份隔离证明见 CHECKPOINT_04.md，未覆盖完整 M1。

Checkpoint05：geometry/reducer/browser **11 passed**，Web/CLI Python回归 **11 passed**。本轮未修改Python，不虚称全量重跑；见CHECKPOINT_05.md。下一项公共日志安全方案High复核中。

Checkpoint06：CORE_STATUS后端/API，目标80passed，独立High日志27passed，三项MUST_FIX关闭；r3最终冻结 **430 passed/32 skipped/143.61s**，浏览器回归11passed。详见CHECKPOINT_06.md与evidence/checkpoint-06-final-tests.txt。下一项日志UI，未声称完整T05/M1验收。

Checkpoint07：公共日志UI筛选/固定high-water分页/按需正文/虚拟窗口/覆盖说明已接入；最终Chrome/reducer/geometry/log-validator **13 passed/0 skipped/5.85s**，相关Python **39 passed/1 warning/5.21s**。High发现的详情残留与ref类型隐式转换已修复并独立复验，刷新失败保留同项目页及迟到响应隔离通过。见CHECKPOINT_07.md；后端未改，未虚称重跑430全量。下一项工具metadata/资源，完整Goal保持活跃。

Checkpoint08：worker新MCP config含closed request/generation指针，bound intent补scratch/memory与private fixed return fact，回放/崩溃不重复执行。目标68passed/1skipped，独立High31passed/1deselected范围无MUST_FIX；最终全回归 **455 passed/32 skipped/1 warning/145.80s**。见CHECKPOINT_08.md与evidence/checkpoint-08-final-tests.txt。公开工具collector尚未实现，UI保持未接入；下一项bounded发现/可信release核验/事务公共事实，然后资源。完整Goal仍活跃。

Checkpoint09：执行前durable REGISTER与closed bounded fd reader已实现，杜绝只依赖返回通知的漏发现窗口；登记时缺launch witness不事后升级。High父目录fsync MUST_FIX关闭，target56passed，独立54passed/1deselected；冻结全回归 **478 passed/32 skipped/1 warning/146.63s**。见CHECKPOINT_09.md/TOOL_DISCOVERY_PROTOCOL.md及evidence。下一项core indexed pending/事务cursor与receipt语义digest、完整release/permission核验及公共工具事实接入，然后资源；M1–M5/完整Goal仍未完成。
