# 原有限全集紧急 STOP（Checkpoint 64）

交付：`create_finite_host_app` 为同一原 Host/Pool/Auth、1–3 个已独立批准的原项目安装一个有限 STOP coordinator。原 CPU/工程 Run 不变；Dashboard 的全集 STOP 不等待某个 Run 回执，不接收外部目标、lease 或路径，不建立调度器、审批或新执行能力。

## 行为与验收合同

- `GET /api/v1/finite-host`：所有固定原 scope 的 viewer 权限才可读取。明确 fixture、执行开关 false、固定 scope/hash、原 owner 可用性；不是整个 Goal 或任意子进程树。
- `POST /api/v1/finite-host/commands`：唯一 body 为 `{"action":"CANCEL_ORIGINAL_FINITE_UNITS"}`。同源 human session、CSRF、每个原项目的 operator 权限及全部原 key 冲突检查必须先于任何取消锁存。
- 全部目标通过验证后，先在内存中锁存全部原 Unit 取消，再进入 Store/Pool/producer 收尾。容量拒绝不能撤回取消；有界原 cap 安全收尾不伪造已接受的 STOP 事实。
- 每项分别返回原 STOP intent、实际清理状态和 post-cleanup 返回状态。仅全部三项均已知成功才返回 202 / `ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN`；部分或未知返回 200 / `PARTIAL_OR_UNKNOWN`。不承诺跨 SQLite 原子事务或持久全集回执。
- `GET /api/v1/finite-host/commands/{id}`：仅本 actor、全部原 scope viewer 权限可读已有结果。普通同 body/key POST 是回执恢复，不重复已执行的清理。
- `?resume_cleanup=1` 是显式续原未知项；已知 intent/cleanup/post-cleanup 三项成功的 scope 不重做。返回 JSON 是私有 canonical 缓存的副本，客户端篡改不能隐去 UNKNOWN。
- SDK 等待者中断不拥有 worker 生命周期。实际提交的 future 全部终态前保留 running/容量；部分 executor 提交失败仍对其他 scope 做有界原清理。最多 32 个 command、2 个 active batch、3 个 cleanup body 并发、每原 scope 一项容量拒绝安全 future。
- Dashboard 不自动 POST。UNKNOWN 仅人工原 body/key 普通重试；重新得到 PARTIAL 后才能显式续清理。切换项目/认证或退出立即清除私密 scope/intent/result，旧异步回复不能回填。

## 真实执行边界与失败诊断

原 runtime 的 `start` 在共享 Pool 锁内完成 spawn→register→G 的短阶段。两个 G 前 worker 同时等待屏障会阻塞第二个原 spawn，不能用扩大 watchdog 或绕开原权限锁使测试表面通过。

r6 首次双 pre-G 屏障失败；r8 改用真实 worker 终态和进入时间诊断，再次失败，确认两个 register 进入相差约 4.26 秒及原锁范围。两个失败均保留，未获得“两 producer 同时 pre-G 存活”的证据。

对应可执行验证是两个原 Run：一个真实 pre-G producer、第二个等待原 Pool；全集取消必须先全部锁存，双方不得进入 G，已启动 producer 必须实际 reap/FD 关闭，最终 Pool 占槽为零。该验证不是放宽 Goal 的并发、STOP、严格资源验收，也不声称支持任意树或严格 OS 全局 STOP。

原单活 worker HTTP STOP、全 scope 先锁存、部分清理 UNKNOWN 保留占槽、返回 JSON 篡改无效、续原未知项、HTTP 零提交拒绝、pending future 中断与部分 executor 提交拒绝分别保留实际证据。Chrome 是原未启动两 scope 的实际 human STOP/原事实/Pool 释放；不要将该浏览器场景称为双活 producer STOP。

## 剩余缺口

固定 CPU384/工程单写 AST21 仍是机器验收待独立产品 Review。开发期 High 审查不是产品 Reviewer；没有 Goal 完成、模型账单、严格 OS/任意树资源释放、native 执行或生产迁移声明。原 native/Reviewer/ConditionEvidence、T21、T22 的 B1/24h fixture/8h UI、T23 安装迁移及依赖后的 M5 验收继续保留。

复验命令、终态、必要回归、失败与 SHA 归档以 `evidence/checkpoint-64-final-tests.txt` 为准；本页不替代验收证据。
