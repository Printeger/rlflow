# A 原条件接纳 CAS

交付行为：`NativeModelOwner.accept_workflow_conditions(exact_reviewer_lease, token, idempotency_key=..., expected_state_version=...)` 仅从原已结算 Engineer、实际执行 CPU 和独立 Reviewer 三段 whole-event 派生证据，向受保护 append-only 域 `hybrid_a_condition_acceptances` 提交一次 CAS。调用者不能提供 PASS、候选、评审或结算数据。

原 Source 使用第一条受认证 ACK 的 thread ID 发布 `model_session_id`。Engineer 和 Reviewer 必须是不同会话、Source、producer、lease/task/attempt；相同候选哈希不能替代独立性。历史用量缺会话 ID 不回填。原批准 envelope 必须显式含每项 required condition 的全文哈希与 `ORIGINAL_CPU_CHECKS_V1` / `ORIGINAL_INDEPENDENT_REVIEW_V1` 验证器映射；没有映射的旧批准不自动升级。

CPU 必须 SUCCEEDED/PASS，Evaluator 必须接受同一已执行候选且无 MUST。原 Source result cap、持久 usage/result、完整 STOP/SETTLED、实际 Pool FREE 和 FD 闭合继续由原 Owner 重证。事务内重核原 Goal/Registry/批准、Controller、原三父事件及依赖、当前 Budget head，所有维度 reserved/unknown 为零且无 overrun。最后提交门还须保持原 A 总窗口、批准/Controller 期限和纯 STOP 门；受管 unit 控制锁覆盖实际 COMMIT。

同一 Reviewer/candidate 只有一个稳定事实键，重复原请求只读返回 `duplicate=true/current_activation=NOT_RECHECKED`，不重新激活或增加预算。不同请求复用该键拒绝。Store 的普通写入、marker-only、删除、额外 mutation、历史 source/hash 漂移均不得升级为接纳。snapshot/recover/audit/replay 必须闭合验证原事件和 append-only 域。

接纳不将整个 Goal 标记完成，也不自行调度：事实固定 `goal_completed=false/dispatch_enabled=false`。下一切片必须在同 A 额度与当前审批/STOP 下重新消费原事实，登记唯一需求驱动的接续，再提交实际执行结果。旧事实、reader JSON 或重复返回都不是新运行许可。

验收：本地测试明确拦截模型 G，使用显式 synthetic 模型来源，实际执行 managed CPU，验证三父条件 CAS、重复/改键拒绝和冷恢复一致。此路径只证明本地接线，不证明真实模型来源或独立产品 Reviewer，固定 parser 测试不算首次真实工程任务。真实 A 运行仍待既有小额合同批准；GPU/B/C/instinctRL HOLD 保持不变。

最小剩余实现与实证：

1. 在原当前 Controller/批准/预算/STOP 和同 A 窗口内消费接纳事实；拒绝旧 reader JSON、重复返回激活和未知曝光。
2. 只登记一次需求驱动接续，累计 medium/session/token/controlled-time 原账本；接通原 Owner 责任、前序正常退休/完整 FREE、新 plan/lease 和真实候选输入，不能重置 first-Engineer 或复用已结算 reservation。
3. 接续使用原有限 native 执行/归档桥，不重发不确定 G，不按固定加法/π或 parser 演示宣布闭环完成。
4. 在真实 A 合同获批后，以非预设项目工程任务及可配置 CPU 验收，提交实际修改、测试、独立 Reviewer、条件接纳及一次自主接续的原始证据。

其他恢复增强后置。本地实现不等待运行授权，也不因此扩大 GPU/B/C/HOLD 范围。
