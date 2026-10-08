# 当前实现到需求的差距矩阵

基线：`d25cf02`，2026-10-08；必须按当前工作树继续核验。

| 领域 / 任务 | 可复用实现 | 缺口与新增工作 | 验收 |
|---|---|---|---|
| 状态与事件 T03–T06 | `store.py` 增量 projection、事务、blob、快照，`contracts.py` 校验 | v1 typed 对象、epoch envelope、同事务只读桥、有界快照、SSE | A11–A16、A32 |
| 合同授权 T09、T16 | `policy.py`、`authorizations.py`、`packages.py` | 不可变 GoalContract、可信 principal、审批精确版本、CSRF、幂等命令回执 | A01、A02、A20、A21、A29、A30 |
| Runtime T02、T11–T13 | `worker.py`、`isolation.py`、`startup.py`、`lifeguard.py` | 0.161.0 compatibility、protocol pin、adapter、controller fencing、候选 writer lease、只读固定评审 | A03–A05、A09、A10、A23、A36 |
| 策略 T10 | `decomposition.py`、`progress.py`、`failures.py`、`escalations.py` | 事件风险激活、DAG 与全局条件、冷却与预算收尾策略 | A02、A06–A08 |
| 预算 T14 | `accounting.py`、`usage.py`、`model_policy.py` | scope 避免父子重算、跨项目资源池、unknown exposure、硬/软边界显示 | A11–A13、A31 |
| STOP/恢复 T17 | `jobs.py`、`lifeguard.py`、`startup.py` | 命令异步终态、epoch fence、UNKNOWN reconcile 与 UI 一致性 | A20–A23 |
| 研究 T18–T20 | `experiments.py`、`research.py`、`evidence.py` | 通用本地/fixture adapter，执行/有效性/结论正交，科研闭环，安全产物接口 | A22、A27、A28、A30 |
| Dashboard T06–T08、T20 | 认证只读 API/SSE 基础已新增；无前端 | 真实 Live、拓扑、原因、预算、任务/条件、事件/日志、实验、移动/减少动画、无伪计数；完整 M1 未验收 | A10、A14–A19、A30、A35 |
| 资源可靠性 T21–T22 | `resources.py`、`resource_service.py`、`files.py` | 主机共享准入、控制资源隔离、磁盘保全、完整 B1、24h/8h soak | A24–A26、A31、A32 |
| 安装迁移 T23–T25 | `releases.py`、`migration.py`、`bootstrap.py` | wheel 包含 roles/schema/static、新安装、唯一切换、可信远程、历史纯 reducer | A19、A33–A35 |
| 单入口 T15 | 管理 CLI | 包含并可安装 `$rlflow` skill，与 API 相同业务核心，Agent 无人类批准权限 | A01、A02、A29 |

已有测试不能自动当作新语义验收。每项必须增加匹配当前候选的证据，未验证项保持未完成。
