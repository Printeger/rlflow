# A 原模型执行与归档桥

`NativeModelOwner.run_workflow_native(lease, launch=original_launch)` 接通原 accounted FIRST_ENGINEER 或 INDEPENDENT_REVIEW：原 start → 有限 Source 观察/collect → 无条件原 STOP → 原完整结算及 usage/result 归档证明。它不读取凭据、不生成 launch、不代替真实运行批准、不另开会话或重试。

第一次只允许原 REGISTER_NO_HANDOFF。exact lease/launch 在任何执行前核验；强留唯一序列与同一 deadline，失败或 STOP 丢返回锁存 unresolved，不再 start/G。短 admission→Pool 段内核原当前 phase 的 guard，退出原 writer 后才观察 stdout/发布 ACK。shutdown 不等待整个 RUN，只置 freeze 并等待当前短段。

deadline 从本次原 start 前锚定，不由 poll 重置；guard、poll、collect 后末采样，Source 在原 cap 发行前后也核同期限。Source 末门同时核 owner freeze、物理 freeze、STOP latch，避免 shutdown 已发出但尚未拿锁时新发结果。异常与 STOP 清理失败同时保存 cause/note；任何过期、缺用量、UNKNOWN、归档尺寸降级或 STOP 不完整都不能返回成功。

成功须原自然 exit0、完整前缀审计、原 STARTED/ACK/Source result cap，再核原 Budget terminal whole-event/dependencies、当前 SETTLED、实际 Pool FREE 回执与全部 FD 关闭，且 Source usage/result 与持久 terminal 逐值相同。已完成重复只返回强绑定 cap/原 terminal 的冻结副本，不重新生成。返回 `condition_evidence_enabled=false`；此执行结果还不是条件接纳或接续权限。

本地验收实际将 G 截断：运行失败后原进程/私有凭据副本和资源池完整清理，预算 UNKNOWN，重复拒绝且无新进程。成功流、超期和发行竞态使用显式纯 harness / synthetic Source 验证控制流，不能证明真实生成。证据见 `evidence/a-workflow-native-run-20261011.txt`。

下一直接实现：真实 Reviewer 结果与原机器/Engineer 父事实的条件接纳 CAS、预算内一次需求驱动自主接续，再以非预设真实任务验收。真实模型运行仍待小额 A 合同批准；本地代码不受此阻塞，GPU/B/C/instinctRL HOLD 不变。
