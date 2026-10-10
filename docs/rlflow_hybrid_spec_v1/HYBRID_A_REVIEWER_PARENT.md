# A 独立 Reviewer 的原 CPU 父证明

## 同 A 的 Evaluator 登记已本地接通

`reviewer.prepare_workflow_reviewer_plan(current_token)` 从原 CPU 责任派生新 preparation、reservation、Workspace 和只读 Evaluator WorkingPlan；不接受 caller candidate/checks/额度。每个准备步骤持短 admission 锁并核 exact-live/freeze，异常锁存，不再生成另一套准备。

`issue_workflow_reviewer_grant` 重新证明两级 whole-event/dependencies 和同批准，重算 candidate packet/schema。受审候选是原已执行文件的冻结 stdin；只读 WorkingCopy 仅为原 Source baseline。模型工具关闭，Evaluator 无 write roots，不能将 baseline manifest 当作 candidate。只有显式 INDEPENDENT_REVIEW 绑定采用这一规则；FIRST_ENGINEER 与历史 V1 仍要求原 manifest，不能借 Reviewer 放宽。

原 REGISTER CAS 在同 Budget head 累计 high+1 和完整 reservation wall ceiling，按原 CPU registration 唯一登记，不重置首 Engineer、Medium 计数或原 started_at。历史 ledger 重新读取两级父事件、scope/epoch/批准及 plans 后重算绑定，不将 DATA/hash 当作原 Source。

验收已实际走通 CPU PASS→新 Evaluator plan/grant/REGISTER→无模型启动 STOP→SETTLED/FREE/全部 FD 关闭→冷 recover=audit=replay。累计 Medium1/High1/controlled660 秒；重复登记、外来 CPU、错角色、High 超额和不足 teardown 额度拒绝。模型父仍显式 synthetic，Reviewer 未生成，因此不算产品独立评审或首真实任务。证据见 `evidence/a-workflow-reviewer-registration-20261011.txt`。

最小剩余实现按直接依赖推进：同 A 的真实 Engineer/Reviewer 执行调度与原 usage/result 归档；机器和真实 Review 父事实驱动的条件接纳 CAS；预算内一次需求驱动自主接续；非预设真实工程任务的完整验收证据。其他恢复增强后置。未批准的模型合同只阻实际调用，不阻这些本地实现。

## 同 Budget 模型 Owner 交接

核验并封存输入后，`cpu.handoff_workflow_reviewer(lease, cap, token=current_token)` 核所有原 CPU 责任 SETTLED/FREE/FD、当前 Controller token，关闭全部原 Workspace，正常退休原 CPU/source，然后原子安装唯一的新 `NativeModelOwner`。Budget 指针从原 CPU 直接到新 Owner，不清空、不另建账本、不复用旧 reservation/plan/claim。

新构造器 `_review_handoff` 不是公开 Caller 授权：须 exact 原 CPU/lease/cap、不可变 root 与原正常退休 tuple/source/Workspace 完整 close 回执摘要。Safety 退休、单独 `retired=True`、复制或跨作用域均不能安装。child 在安装点强留，原关闭 COMMIT、shutdown 或构造返回丢失时，重试只接续同原责任或取回同 child。关闭 CAS 只复用原已核 helper：同快照证明 fact/event 双不存在且前驱不变才重链，已有 COMMIT 保留 exact request。

锁序为 admission→Pool→registry；在退休前永久冻结 CPU 新准备，不等整个运行 sequence。交接本身只授原构造能力，不授模型后验资格；后续角色计划、grant 和高配额须另经上述原登记门。FIRST_ENGINEER 仍不能重置，不把交接称为独立评审。

`LocalCpuRunnerOwner.prepare_workflow_reviewer_input(lease)` 只接收该原 Owner 已发行的 CPU lease；完成实际 candidate checks 后，必须已完整 STOP、原 Budget SETTLED、全部原 source/Pool FD 关闭且原 Pool FREE 已 COMMIT。

发行前重新核 CPU 原 whole event 与 history/dependencies、原 Engineer terminal、当前同批准/Registry/module pins、原唯一 CPU stage 和 A 窗口。由 `from_cpu` 重算原候选 CPU binding/spec/机器结果，要求机器 PASS 且原 wait-status 对应 SUCCEEDED，候选 hash 必须等于原 Engineer 持久结果中 files。CPU 与 Engineer 批准来源严格比对，仅采样字段 `source_version`/`evaluated_at` 不作身份（沿现有 Budget guard 语义），不是忽略批准版本。

返回 exact `LocalCpuReviewerInput` 强绑定原 lease/cap/raw；复制、跨 lease、修改原结果缓存或 raw 不成为有效输入。`_issued_workflow_reviewer_input` 每次重新核全部原证明并返回 fresh decoded data。窗口和批准 expiry 在最后序列化后重采样，材料本身不授予执行、CPU 再次派发、条件或结算权限。

材料含 Evaluator/high 的同 A spec、冻结 packet/schema、两级持久 parent refs 和机器结果 hash，`condition_evidence_enabled=false`。它不等同产品独立 Reviewer：原交接和不同 Evaluator 计划/高配额现已本地接通，仍需真实会话、真实输出/usage 归档，再由机器和 Review 父事实进行条件 CAS 与一次需求接续。

测试的 Engineer Source 明确合成且 G 被截断，只有 CPU 实际执行；这份证据不得计首个非预设真实任务闭环。小额 A 模型合同未批准前不调用，GPU/B/C/instinctRL HOLD 保持。证据见 `evidence/a-workflow-reviewer-parent-20261011.txt`。
