# Checkpoint 87：可配置本地实验的认证只读 Dashboard

本片交付：受批准配置的实际 CPU 实验通过原事件验证后，在 Dashboard 展示输出、批准验收条件、机器 PASS/FAIL、原历史计额与独立 Review 缺口。现有 snapshot/SSE 驱动刷新，不新增控制命令，不把统计实验当作自主科研闭环。

可信宿主启动接线：构造 `LocalCpuPublicTaskReader(original_store, project_id=..., store_epoch=...)`，通过 `create_app(..., fixture_task_readers={project_id: reader})` 注入。默认不启用，HTTP 不接受路径、epoch、源能力或执行配置。仅 exact `FixtureTaskReader` 和 exact `LocalCpuPublicTaskReader` 可注入，私有 `LocalCpuTaskReader` 或任意子类拒绝。示例宿主 `web_checks/local_cpu_server.py` 是一次性开发夹具，不是生产服务或新安装验收。

原 GET 接口保持：`/api/v1/projects/{project_id}/fixture-tasks`（after/limit 有限分页）、`.../{reservation_id}`、`.../{reservation_id}/timeline`。本地 Task 的 kind 为 `LOCAL_CONFIGURED_CPU`，authorization 为 `ORIGINAL_APPROVED_LOCAL_CPU_ONLY`。详情新增 `configured_result`（仅 outputs、approved_acceptance、machine_acceptance）与 `recorded_settled_usage`。后者是原终态预算事件 consumed 差量，不是重记账或实时计费。私有 managed_terminal_proof、原 lease/source/process/unit/句柄身份均不公开；输出是用户批准的实验原文，不对输出本身作秘密过滤。

GET 验证完整原审批、preparation、Budget 及依赖来源，并检查 as-of 版本；不 poll live source、写 Store、重建句柄、重执行或冷接管。读取独立两槽池，任务读取与 check_current 同一真实 job；HTTP 取消不释放容量，实际 worker 完成才释放。满额 429/retryable，关闭后 503，lifespan 等待实际 worker drain，不占 START/STOP 池。每个新应用生命周期使用新池，不复用已关闭应用。认证入口及返回前均重核；原同源/项目权限与关闭 query 保留。

前端闭合验证本地字段、输出 UTF-8 上界、原批准有限数值区间、历史用量及 timeline 一致性。无独立科学重算或审批权；始终 current_execution_status=UNKNOWN、controls_available=false、independent_review_status=NOT_PROVEN、condition_evidence=false。固定 START/STOP 按 PROTOCOL_CONFORMANCE kind 隔离，即使登录者为 operator 也不会对本地 Task 启用。

验收证据：[checkpoint-87-public-dashboard](evidence/checkpoint-87-public-dashboard/)。初 API 1pass/16.26s，真实 Chrome 1pass/24.13s：登录后未执行 UNKNOWN→实际 median 实验→机器 PASS/原 starts1/完整 STOP/Pool0→SSE 展示与原 Reader 完全一致→logout 清除，无固定控制 POST。容量修复前运行的 Chrome 明确保留版本边界，未冒称修复后新浏览器全绿。UI 模块其后不变。新容量与旧读取回归首轮 8pass/1fail/1setup error/81.92s，失败根因均为测试生命周期接线，原日志保留。仅修正项及新容量/实际实验 API 最终 3pass/38.73s；其余 8pass 不重跑。旧 Node 16pass、新实际 DTO 负例 1pass，独立增量审查容量 MUST 关闭。

剩余资格：真实模型 Engineer→独立产品 Reviewer→ConditionEvidence→自主接续，strict aggregate diskquota、完整异常 STOP/跨进程恢复、24h/8h 长跑及新安装完整应用验收均未证明。82 全库实际 4failed/2532passed/32skipped 历史保持，不将分轮定向回归重标全库全绿。集中模型/GPU 合同未获批准，不调用；instinctRL 保持只读/HOLD，尚未提供可声称准入的长跑版本或另窗验证 Goal。完整 M0–M5 目标仍 ACTIVE。
