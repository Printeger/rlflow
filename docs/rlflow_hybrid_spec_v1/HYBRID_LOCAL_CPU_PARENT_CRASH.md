# Checkpoint 90：父进程崩溃后的物理资源退役

交付行为：新批准本地 CPU source 启动 transient service 时设置 `CollectMode=inactive-or-failed`，原 manager 每次 snapshot 精确复核该策略。保留 `RemainAfterExit=yes`、原 RefUnit、Invocation、JobRemoved done、空受管范围和 FD 闭包证明门；不修改 Budget 或 Pool 释放规则。

实际故障注入仅 SIGKILL 一次隔离 fixture 父进程。任务产生真实 setsid 后代，测试在崩溃前持有 keeper、leader、后代的原 pidfd，确认所有进程终止；只读观察原 unit 被 GC。`not-found` 仅是物理 GC 诊断，不是同 Invocation 的 STOP 证据。冷读原 Store 保持 UNKNOWN、无 managed terminal/settled usage、无 controls/ConditionEvidence；以死前原安装 pins 受保护 attach Pool，仍 occupied=1、无重建 claims、读前后 Store/Pool 不变。

验收与证据：

- 旧策略 baseline：99838 / 84c7e5，1 passed in 11.62s。否定“父死必然留下活动 service”的初始假设，实际 keeper/task 已停止，但 failed unit 长期保留。
- 新策略故障 + 原正常完整 STOP/FREE + 原 deadline 归档回归：26445 / b3dc90，3 passed in 52.31s。此时故障 case 尚无 Pool 冷读断言。
- 追加 Pool 冷读后的受影响故障 case：55148 / aed070，1 passed in 11.67s；未重复前两项正常/期限测试。
- `evidence/checkpoint-90-owner-crash/` 保存各终态与最终实际 history/state/pool。JSON 格式化副本不是 byte seal。
- High 独立窄审无新增确认 MUST；compile/diff 检查通过。最终只读 manager 清单仅原 4 个 failed unit（含 baseline），新策略运行未新增保留单元；不执行 reset-failed、历史清理或生产迁移。

原 3 项命令：

```sh
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_hybrid_local_cpu_parent_crash.py tests/test_hybrid_local_cpu_runtime.py::test_actual_configured_core_task_result_managed_stop_budget_and_free 'tests/test_hybrid_local_cpu_negative_result.py::test_actual_negative_result_archived_stopped_and_cold[deadline]'
```

设计依据：systemd v255 [Unit CollectMode](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.unit.xml) 与 [D-Bus RefUnit/CollectMode](https://raw.githubusercontent.com/systemd/systemd/v255/man/org.freedesktop.systemd1.xml)。原 bus 引用保住正常证明；父死引用消失后允许 failed 单元 GC，不能据此补业务终态或退款。

剩余缺口：父崩溃后的原输出/终态报告尚无可信持久恢复通道；预算 UNKNOWN 与占槽不能自动收敛。下一片应交付原批准任务证据的持久恢复行为，先建立前 G 绑定、任务不可伪造的发布源，再冷读验证，不重建失去的原 manager/STOP 权限。不称完整恢复、全量回归、新安装资格或 24h/8h 长跑通过。真实模型 Engineer→独立产品 Reviewer→条件证据→自主接续仍待此前集中资源合同答复；strict quota、科研自治和 instinctRL 实机准入仍未完成。固定 fixture 不是自主闭环。
