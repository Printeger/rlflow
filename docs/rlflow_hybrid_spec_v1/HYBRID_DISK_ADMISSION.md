# 有限 Host 共享磁盘准入

Checkpoint 67 在原共享 Pool、已批准固定 CPU/工程 Unit 和认证 RUN 上增加可用空间准入。低磁盘或低 inode 在 HANDOFF 前拒绝新 RUN，恢复后原 body/key 可再次执行；实际 spawn、G 与工程 pwrite 的末门重新检查空间。STOP 不调用新工作门。基线为已提交的 66 `d3ab5e2`，41 不重新开启。

## 交付行为

原 Host 绑定原 Unit 时捕获 Pool、Project runtime 和实际 working copy 的祖先链、设备及 filesystem id。每次准入重新打开原链，以真实 fstatvfs 获取可用块和 inode；同 FS 合并项目承诺占额，不各自使用全部余额。最多三个实际 FS，超出拒绝绑定，不能忽略未覆盖目录。

政策是每 FS 保留 128MiB 和 16 inode 正常 headroom，再为每个未完整收尾的原 claim 承诺 16MiB、8 inode。这是额外收紧的运行准入，不是合同预算新维度、计费用量、硬 quota 或 SQLite STOP 写放大证明。诊断明确标为 PROCESS_LOCAL_FS_AVAILABLE_NOT_QUOTA。

非 FREE claim 无本 Host 原绑定时，新执行 fail closed，包括冷 UNKNOWN 和 PENDING_BIND 窗口。不恢复重启余额、采纳旧 reserve 文件或按 ID 恢复能力。额度退出要求原 Pool 不再占用该 claim、原 terminal/pool_closed，以及真实最终收据或原取消清理明确完成。正常 worker STOP 后工程 apply/accept 未完成仍占额；取消 latch、默认无错误、等待者退出及 UNKNOWN 都不退额。

资源 IO 位于原最后 Auth/TTL/cancel 门之前，不在通用 Store commit 回调获取 Pool 锁。HANDOFF 后低盘拒绝只续原收尾，不自动第二次 spawn；工程末门拒绝不自动重写。认证 GET /api/v1/finite-host/disk-admission 返回同源诊断，不写事实、分配空间或调度；阻塞读取后重新认证，来源不可用返回 503。

## 验收证据

新增九个逻辑场景采用已通过项与最后差量的合成证据，不声称最终新模块全量重跑。r1 四项通过，99.04 秒：双项目同 FS 占额、SDK 零执行/原 key 恢复、HTTP 低 inode 503/STOP 202/原 body key 恢复、工程 Pool FREE 后 pwrite 末门拒绝并保留额度。r2 两项通过，36.87 秒，覆盖取消 latch 不退额和诊断返回前权限失效/来源故障分类。

r3 加强为真实 AuthStore.revoke 并覆盖实际 spawn/G 末门，三项主体通过，59.04 秒，但 spawn 场景有一项 teardown 错误：测试误用普通终态关闭已有 HANDOFF 的无 producer scope。修为既有原父 FD safety retirement，r4 仅该失败项通过，19.46 秒；占槽仍为 2，无伪 terminal/FREE，产品源码不因此改变。

唯一必要受影响回归 r5 实际 27 项通过，1 条既有告警，661.52 秒；所有 333 冻结输入一致。实际终态后只修诊断 GET 默认线程队列无界提交问题：独立容量 1 的诊断池，不共享 STOP 槽，真实 future 结束才退容量。r6 最后两项定向通过，35.77 秒，覆盖真实撤销后的重新认证和实际队列满 429、取消等待者仍占额、原项目 STOP 202、future 完成后 GET 200、生命周期关闭。测试屏障在 Pool 锁之前，不据此声称文件系统挂起时 STOP 有硬完成时限。另 331 输入不变，不重复成功回归、旧 bare 模块或 UI/Node 测试。

独立 High 增量审查四个 MUST 均关闭，无剩余必须修复项。最终 333 输入 SHA 为 0703d679e4586c5f86e47250ce50d6199d68a30241d0ed98ac7cc6dbcd4a8a24，源和 19 归档项全部核对一致；编译、依赖和差异检查通过，无运行中测试。证据见 evidence/checkpoint-67-tests.txt、checkpoint-67-final-inputs.sha256 和 checkpoint-67-log-sha256.txt；原所有失败保留。

## 诊断接口

GET /api/v1/finite-host/disk-admission 仅接受空查询和原全集可读会话或只读 bearer。200 响应含 profile、new_run_admissible、unbound_occupied_claim、filesystems、stop_gated、audit_reserve_allocated、restart_credit_recovery、goal_completed。每个 FS 含 available_bytes、available_inodes、promised_claims、required_bytes、required_inodes、admissible；不返回路径、凭据、原始能力或持久额度。容量拒绝 429 是诊断 future 任务槽，不是计费 Budget。401/404 保持原认证/不可见 scope 语义，非法查询 400，源故障 503。诊断不改变原 START/STOP 接口，也不触发自动采样或执行。

## 剩余缺口与下一片

未实分配审计应急空间，不能关闭 RES07/A26 或完整 T21。下一片在原私有同 FS 管理目录接真实有限预留、分配失败可清理及 STOP 消费路径，并接现有 Dashboard 同源诊断。预留大小是有限政策上限，不是 STOP COMMIT 保证；WAL、inode、外部写入及 project quota 保持明确边界。

硬 quota、独立卷、跨重启持久额度、生产迁移或大额预留不在本片权限。严格 OS/任意树、native、独立产品 Reviewer、可信账单、安装/B1/24h fixture/8h UI、T23/M5 及完整 Goal 缺口保持；不调用付费模型/GPU，不改用户 package-lock。
