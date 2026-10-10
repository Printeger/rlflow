# A 独立 Reviewer 的原 CPU 父证明

## 同 Budget 模型 Owner 交接

核验并封存输入后，`cpu.handoff_workflow_reviewer(lease, cap, token=current_token)` 核所有原 CPU 责任 SETTLED/FREE/FD、当前 Controller token，关闭全部原 Workspace，正常退休原 CPU/source，然后原子安装唯一的新 `NativeModelOwner`。Budget 指针从原 CPU 直接到新 Owner，不清空、不另建账本、不复用旧 reservation/plan/claim。

新构造器 `_review_handoff` 不是公开 Caller 授权：须 exact 原 CPU/lease/cap、不可变 root 与原正常退休 tuple/source/Workspace 完整 close 回执摘要。Safety 退休、单独 `retired=True`、复制或跨作用域均不能安装。child 在安装点强留，原关闭 COMMIT、shutdown 或构造返回丢失时，重试只接续同原责任或取回同 child。关闭 CAS 只复用原已核 helper：同快照证明 fact/event 双不存在且前驱不变才重链，已有 COMMIT 保留 exact request。

锁序为 admission→Pool→registry；在退休前永久冻结 CPU 新准备，不等整个运行 sequence。新 Owner 只具原构造能力，没有 Reviewer grant、新角色 WorkingPlan/high 配额或模型后验资格；FIRST_ENGINEER 仍不能重置。下一直接实现是原 Evaluator plan 与候选绑定、同 A 登记/重放/高配额，继而真实 Review/条件/接续，不把交接称为独立评审。

`LocalCpuRunnerOwner.prepare_workflow_reviewer_input(lease)` 只接收该原 Owner 已发行的 CPU lease；完成实际 candidate checks 后，必须已完整 STOP、原 Budget SETTLED、全部原 source/Pool FD 关闭且原 Pool FREE 已 COMMIT。

发行前重新核 CPU 原 whole event 与 history/dependencies、原 Engineer terminal、当前同批准/Registry/module pins、原唯一 CPU stage 和 A 窗口。由 `from_cpu` 重算原候选 CPU binding/spec/机器结果，要求机器 PASS 且原 wait-status 对应 SUCCEEDED，候选 hash 必须等于原 Engineer 持久结果中 files。CPU 与 Engineer 批准来源严格比对，仅采样字段 `source_version`/`evaluated_at` 不作身份（沿现有 Budget guard 语义），不是忽略批准版本。

返回 exact `LocalCpuReviewerInput` 强绑定原 lease/cap/raw；复制、跨 lease、修改原结果缓存或 raw 不成为有效输入。`_issued_workflow_reviewer_input` 每次重新核全部原证明并返回 fresh decoded data。窗口和批准 expiry 在最后序列化后重采样，材料本身不授予执行、CPU 再次派发、条件或结算权限。

材料含 Evaluator/high 的同 A spec、冻结 packet/schema、两级持久 parent refs 和机器结果 hash，`condition_evidence_enabled=false`。它不等同产品独立 Reviewer：还需原 CPU Owner 正常退休后的受保护 model Owner 交接、不同 Evaluator 角色计划与真实会话、同 A high 配额累计、真实输出/usage 归档，再由机器和 Review 父事实进行条件 CAS 与一次需求接续。

测试的 Engineer Source 明确合成且 G 被截断，只有 CPU 实际执行；这份证据不得计首个非预设真实任务闭环。小额 A 模型合同未批准前不调用，GPU/B/C/instinctRL HOLD 保持。证据见 `evidence/a-workflow-reviewer-parent-20261011.txt`。
