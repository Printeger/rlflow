# A 独立 Reviewer 的原 CPU 父证明

`LocalCpuRunnerOwner.prepare_workflow_reviewer_input(lease)` 只接收该原 Owner 已发行的 CPU lease；完成实际 candidate checks 后，必须已完整 STOP、原 Budget SETTLED、全部原 source/Pool FD 关闭且原 Pool FREE 已 COMMIT。

发行前重新核 CPU 原 whole event 与 history/dependencies、原 Engineer terminal、当前同批准/Registry/module pins、原唯一 CPU stage 和 A 窗口。由 `from_cpu` 重算原候选 CPU binding/spec/机器结果，要求机器 PASS 且原 wait-status 对应 SUCCEEDED，候选 hash 必须等于原 Engineer 持久结果中 files。CPU 与 Engineer 批准来源严格比对，仅采样字段 `source_version`/`evaluated_at` 不作身份（沿现有 Budget guard 语义），不是忽略批准版本。

返回 exact `LocalCpuReviewerInput` 强绑定原 lease/cap/raw；复制、跨 lease、修改原结果缓存或 raw 不成为有效输入。`_issued_workflow_reviewer_input` 每次重新核全部原证明并返回 fresh decoded data。窗口和批准 expiry 在最后序列化后重采样，材料本身不授予执行、CPU 再次派发、条件或结算权限。

材料含 Evaluator/high 的同 A spec、冻结 packet/schema、两级持久 parent refs 和机器结果 hash，`condition_evidence_enabled=false`。它不等同产品独立 Reviewer：还需原 CPU Owner 正常退休后的受保护 model Owner 交接、不同 Evaluator 角色计划与真实会话、同 A high 配额累计、真实输出/usage 归档，再由机器和 Review 父事实进行条件 CAS 与一次需求接续。

测试的 Engineer Source 明确合成且 G 被截断，只有 CPU 实际执行；这份证据不得计首个非预设真实任务闭环。小额 A 模型合同未批准前不调用，GPU/B/C/instinctRL HOLD 保持。证据见 `evidence/a-workflow-reviewer-parent-20261011.txt`。
