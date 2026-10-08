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
| T05–T08 | 未完成 | 完善实际 worker 启动观测、认证 API/SSE、前端与只读 Live 验收 |
| T09–T17 | 未开始 | 合同、策略、受控 Runtime、单写、独立评审、预算、skill、控制与恢复 |
| T18–T20 | 未开始 | 本地与 fixture 实验 adapter、科研状态、证据页面 |
| T21–T22 | 未开始 | 资源隔离、故障/性能/24h 与 8h soak |
| T23–T25 | 未开始 | 安装/迁移、可信远程、历史回放 |

后续恢复应先读取本文件、Git、验收记录与实际测试输出。没有记录为已完成的条目不得推定完成。

最新进展：新增协议/观测回归、旧版本兼容修复及 High 独立审查的 MUST_FIX 已关闭。冻结最终代码后的全回归 **349 passed / 32 外部依赖 skipped / 109.97s**。报告与命令见 IMPLEMENTATION_VALIDATION.md，原始精简输出已纳入 `evidence/checkpoint-01-final-pytest.txt`。

下一项：完成本 checkpoint 的验收记录与提交，然后沿 T04→T05→T06 实现认证只读 API/SSE。M1–M5 和完整 Goal 仍未完成；不得以本 checkpoint 代替里程碑退出或最终交付。
