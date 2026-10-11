# 有限 A 工程总入口

`NativeModelOwner.run_workflow_engineering(lease, launch=original_launch, launch_issuer=authorized_issuer)` 将原 FIRST_ENGINEER 执行、同预算 CPU 交接/实际检查、独立只读 Reviewer 新计划/会话、三父条件 CAS 和明确需求的一次接续连接成有限调用。只接受原 accounted A stage；不接 caller PASS、候选、Review 或条件证据。

发行回调必须显式提供，入口不读取账户、不创建运行批准、不自动调用供应商或 GPU。回调在 admission 锁外执行，返回之后重新核原当前 Owner、STOP 和 launch。Controller 续期不重置 A 起点、总窗口或额度。原 STOP/结算/持久证据门继续生效。

CPU FAIL 或执行未成功返回 `NOT_ACCEPTED/CPU_CHECKS_FAILED`；Reviewer 非 ACCEPT 返回 `NOT_ACCEPTED/REVIEWER_NOT_ACCEPTED`，不进入条件或接续。通过且没有批准的后续任务返回 `ACCEPTED/NO_EXPLICIT_CONTINUATION_DEMAND`；有明确后续需求且其原 run 成功返回 `ACCEPTED_AND_CONTINUED`。这些返回都是冻结 DATA，均 `goal_completed=false`，不证明当前激活资格，也不代表整个 A 或完整 Goal 完成。修复额度不是修复派发实现。

任意阶段异常永久锁存本序列，按同原 Budget/Pool/member 当前 Owner 清理；安装成功后丢返回也清理唯一已装 child，不清理退休父或调用方外来 Owner。STOP 失败保留主错误并注明清理缺口，必要安全清理不晋升 FREE/结算；重复入口拒绝重派。

`original_engineer_owner.stop_workflow_engineering()` 是跨三次正常交接仍可使用的原 STOP 句柄。永久 latch 先于 admission 锁，既不等待序列锁，也不等待外部发行回调。只清理同原协调器当前 Owner。原正常 shutdown 成功、Source/Owner 实际退休、注册集合移除后才保存 exact root/current/source ACK；重复只读该 ACK。安全退役或正常 shutdown 返回丢失且无 ACK，返回 UNKNOWN，不能冒称正常停止。fork 在 Event/锁/身份 IO 前即由原 PID 拒绝。

## 本片实际验收

新增测试 16 passed / 1 warning / 40.19s：13 项显式 DATA 流转 harness，3 项真实原 Owner/本地进程验证。真实 Python gate 的 G 写入被 TEST 截获，零模型执行；原 STOP reap、FD/cache 全关、UNKNOWN/Pool0、序列不重派、audit=replay。原无 handoff STOP 为 SETTLED，正常 ACK 重复不新增事件。实际 fork 继承另一线程持有的 admission 锁，子进程立即 PermissionError，零 STOP latch/ACK/状态修改；warning 是特意构造该锁风险的多线程 fork 警告，非跳过测试。

必要旧 native 执行桥回归 19 passed / 22.68s。独立窄复核关闭发行回调持锁、退休父缺跨交接 STOP、fork STOP、安全退役误作正常确认四项问题，没有新增确证 MUST。未重跑此前已通过的条件/接续完整链，也不声称本片证明整个真实正向总入口。详见 [原始证据](evidence/a-engineering-sequence-20261011.txt)。

## 收敛首个真实任务的最小剩余

1. 固定真实仓库文件与提交来源、非预设任务和用户目标；外部配置验收、明确接续需求进入原批准 envelope。固定加法、π 和 parser 示例不可作为验收。
2. 将原任务输入、实际修改、CPU 检查、不同真实模型会话 Reviewer、条件接纳和接续关联为统一交付包；包装不得替代原事实或产生运行权。
3. 原小额 A 合同批准之后，才运行真实 Engineer/Reviewer/接续并验收上述证据。当前真实任务 NOT_EXECUTED，本地实现不以运行许可为前置。

不新增长期 Supervisor、模型重试、自动修复、恢复增强或额外资源合同。现有 A 小额合同未批准，GPU/B/C/instinctRL HOLD 不变；完整工程/科研、实验 Runner、长期恢复和长跑验收仍保留。
