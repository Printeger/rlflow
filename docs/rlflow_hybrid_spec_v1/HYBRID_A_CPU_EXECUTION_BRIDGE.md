# 同 A 原父事实自动 CPU 执行桥

入口：在 `NativeModelOwner.handoff_workflow_cpu(lease, cap, token=token)` 返回的 exact `LocalCpuRunnerOwner` 上调用 `execute_workflow_cpu(token)`。

调用不接受候选、checks、规则、预算、资源、路径、reservation 或 plan。它重核原持久 Engineer parent、同批准 envelope、当前 Registry/module pins，派生新 CPU 预留（全零模型维度、wall=task_seconds+10）、新 Workspace（60s）、原 WorkingPlan、新 Pool claim（60s）、新 grant/lease，并由原 `run_local_cpu` 执行、采集及完整 STOP。期限仍以原执行器/Controller/Workspace/Pool 门为准，不能借此自动延长原批准。

入口不替代授权或后验来源验证，不调用模型，不写原项目文件，不将机器 PASS 变为 ConditionEvidence。下一独立 Reviewer 必须核 CPU 原持久终态与 Engineer 原生成来源，并使用不同真实会话。

并发/重入调用使用独立非阻塞序列锁直接拒绝，不跨 Store writer 持有 Runtime/source 锁。完成后重复调用只读取原 lease 的结果，不增加 reservation、登记、执行或预算消耗。准备/运行异常保留阶段、原请求和已返回句柄，并锁存 unresolved；不凭异常重链 CAS，不补建 Workspace、不另开 claim、不重发 G。执行阶段沿原 `run_local_cpu` 的 finally 走 STOP；准备阶段尚无执行 lease 时只保留原责任，使用现有原组件清理，不声称退款或全范围 STOP 已完成。

在首个 reserve 前还核原 Budget workflow 的唯一 CPU stage、窗口及累计时间余额；不能靠清 helper 缓存再次预留。每个准备/登记步骤在独立 admission 短锁内核 exact-live/永久 freeze，强留返回句柄；CPU shutdown/safety 先永久 freeze，再只等待当前准备步骤收尾，不等待整个 sequence 锁或持锁运行 CPU。完成回执独立强绑定原 sequence/lease/结果 bytes，重复读取 fresh decode，不信可变结果缓存、lease 或 complete 标记。

`_workflow_cpu_sequence` 是原 Owner 进程内的保护状态，不是冷恢复能力或公开 caller DTO；本切片不增加长期恢复功能。后续需继续完成 Reviewer 接线、条件 CAS 和一次未完成需求接续。实际非预设任务、真实模型用量/结算、产品独立评审和条件接纳的最终证据仍需已提出的小额 A 合同批准后执行；GPU/B/C/instinctRL HOLD 不变。

本切片证据：`evidence/a-workflow-cpu-bridge-20261011.txt`。测试的模型父发布者是显式合成来源、原 native G 被截断；仅 CPU 子进程实际运行，不能计首真实工程任务闭环。
