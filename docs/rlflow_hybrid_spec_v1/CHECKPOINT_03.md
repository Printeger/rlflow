# Checkpoint 03 — trusted 启动释放观测

任务 T05 基础、T03 公共字段扩展；父 checkpoint `3fa157a`。不构成 M1 完整退出。

新增 startup_observation.collect/observe，锚定 root/roles/sid，用 dirfd、NOFOLLOW、NONBLOCK、regular-file 检查读取有界事实（request 4MiB，其余 64KiB）。验证 request、ready、ledger committed release、release 文件、held command、codex identity、model release 和 START_ACK phase/digest 的完整绑定链；核对 candidate/before、reservation/limit、resources。

事务内再核验 generation/release_binding/identity/directory/scratch/phase/before/limit/resources；幂等键绑定 ACK digest，一次性保存。ACTIVE reconcile 和 accept_result 入口调用，覆盖首次无ACK、随后短命进程 ACK+receipt 到达的竞态。历史事实不要求 PID 仍活跃；文件缺失/错误仅拒绝本观测，不改变结算或阻止其他 reconcile。

公开 CLI_RELEASE_ACK 与两个 ISO 时间 startup_released_at/startup_observed_at；仍 STARTING/PARTIAL/usage UNKNOWN。wrapper ACK 在 exec 前，不是 execution.started 或模型消费证明，不填实际 started_at。typed StartupObservation 与公共摘要验证忽略 malformed optional proof，不能用缺失 generation 匹配或破损 hash/time 声称 ACK。

不改：legacy session status/launch_phase、审批、预算、派发策略、供应商模型能力。不启动真实模型/训练/生产 state，不自动 push。T11 必须接入有证据的实际运行事件；日志、资源与完整 T05/M1 验收仍未完成。

测试：68 项针对回归；最终冻结全回归 **399 passed / 32 skipped / 135.90s**。真实 held-wrapper 执行无模型 Python pass 后退出，再采集历史 ACK；绑定篡改、FIFO/符号链接/oversize、双 collector、换代、malformed proof 与 receipt 前补采集均覆盖。初版测试对不存在 authorizations section 的断言 KeyError，改为精确比较缺省空映射后通过；没有修改实际预算/批准门槛。

High 独立只读审查发现并关闭两项：candidate/limit/resources 额外绑定与提交再核验；公共 optional proof 破损不能中断 source 事务。独立 68 passed，当前范围无阻塞 finding。见 IMPLEMENTATION_VALIDATION.md 与 evidence/checkpoint-03-final-pytest.txt。

为 T07 准备的独立 web_checks npm dev 环境已锁定 playwright-core；实际 Chrome 保持 sandbox、禁 GPU、空账号上下文启动/退出。尚未作为 Dashboard UI 验收，根目录用户 package-lock.json 未动。
