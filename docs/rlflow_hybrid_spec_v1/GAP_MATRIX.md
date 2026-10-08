# 当前实现到需求的差距矩阵

checkpoint33增量：T11内部native exec物料组件已实现与冻结root/High115/full1003回归，复用原native masking/MCP策略；全部执行门仍UNVERIFIED，不能启动。持久source-bound intent/expectedseal/completion、actual bounded snapshot、lease/budget/STOP和实际执行仍缺，见HYBRID_EXEC_PREPARATION.md。下段checkpoint32 UI结果保留；不将准备组件称为T11/M2完成，完整M1/M0–M5验收仍未通过。

checkpoint32当前增量：合同/原始receipt/条件批准与恢复闭合、保护1.1本地配置、head/private review和真实human条件事实UI已验证，见HYBRID_CONTROL_UI.md。DRAFT提交不是Registry已核验，条件批准不是lease或执行。root/High34Node+2browser+134backend及full949/32skip证据归档；T11有限adapter、T12lease、T14结算、T17可靠STOP、公开条件/实验全链、实际工程科研/B1/长期/安装与全部M0–M5验收仍缺。下表仍含初始基线，不将已交付UI写成“尚无前端”。

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
| Dashboard T06–T08、T20 | 当前已新增认证只读 API/SSE、真实Live拓扑/状态/原因/预算未知、虚拟事件与公共日志、绑定工具metadata、真实HOST/worker telemetry、手机/键盘/减少动画 | 完整条件/实验/控制页、真实闭环、B1/长期资源验收仍待完成；M1退出门槛见M1_ACCEPTANCE_REPORT.md，不把早期基线“无前端”当当前状态 | A10、A14–A19、A30、A35 |
| 资源可靠性 T21–T22 | `resources.py`、`resource_service.py`、`files.py` | 主机共享准入、控制资源隔离、磁盘保全、完整 B1、24h/8h soak | A24–A26、A31、A32 |
| 安装迁移 T23–T25 | `releases.py`、`migration.py`、`bootstrap.py` | wheel 包含 roles/schema/static、新安装、唯一切换、可信远程、历史纯 reducer | A19、A33–A35 |
| 单入口 T15 | 管理 CLI | 包含并可安装 `$rlflow` skill，与 API 相同业务核心，Agent 无人类批准权限 | A01、A02、A29 |

已有测试不能自动当作新语义验收。每项必须增加匹配当前候选的证据，未验证项保持未完成。
