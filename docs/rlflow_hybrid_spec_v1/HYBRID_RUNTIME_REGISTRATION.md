# Runtime 注册前置：下一切片设计，尚未实现

41 root 冻结集成回归期间的 High 独立只读设计。本文不是运行许可、42代码或验收证据，不修改当前 WorkingPlan.start、CodexExecAdapter.start 和 BOUND 冷 legacy 的拒绝行为。完整 Goal 继续。

## 优先依赖

先实现真正共享的 HostPoolOwner 和有界来源观察/UsageOwner，再接 Runtime registration 与 BudgetHEAD 的联合 CAS。新资源池是资源专账，不是第二个 Goal 调度器。现有 resources 的 cgroup 检查和 usage 的累计/增量算法可以复用；它们本身不是共享会话池或 Hybrid 可信结算来源。

现有 WorkingPlan packet 尚无完整受保护 Task/ExecutionAttempt/ExecutionLease 链。后续必须实际派生并持久化这些身份，不能让 caller 补几个字符串就宣布 RUN-02 已通过。若某组件只完成来源观察而未绑定实际 Runtime producer，名称和状态必须明确 source-only，不称完整 UsageOwner 或消费许可。

## 实际共享池

保护 startup 固定唯一 pool namespace、完整路径/DB/锁身份、host/boot；不允许项目 JSON 或环境变量各选一个“全局池”。原 cooperating fixture 项目必须引用同一 actual PoolOwner/持久身份，初值总计 3 个真实 kernel slots，包括所有受管父子会话。新 fixture 证据不泛化为旧 UNBOUND namespace 或非合作 same-UID 程序已迁移。

slot 使用原持有 FD 的内核锁，并保留持久 immutable claim/派生 head。CLOEXEC 与 fork 后 FD 清理需真实进程测试。锁空闲、PID 不存在、TTL 到期、Controller 死亡或 owner 重启都不能自动释放未知持久曝光，更不能从历史 DTO 重建原进程能力。未强制逐个后代先占 slot、观察和回收之前，native delegation 继续禁用。

## Pool 与项目两数据库

两库不冒充原子事务。顺序是 Pool durable HELD/no-handoff → 项目 writer 内 registration intent 与 Budget reservation/head 联合 CAS → Pool linked ACK。固定锁顺序为 PoolOwner → 项目 Store writer → Controller → Workspace/Working/Runtime；项目 writer 中不反向等待 Pool 锁，也不调用会重入 writer 的 Budget.record。

跨库错误或 COMMIT 丢返回保留原 claim、amount 和 UNKNOWN，不做自动补偿退款。实际 handoff 前，两边必须完整 matching 且原能力仍 live。REGISTER 与 CANCEL 竞争同一 ReservationHEAD，只有一方可胜；unknown_exposure 是 reserved 的子集，不重复扣除。release 需要核心原未 handoff tombstone 或实际全执行范围终态证明，不能接受 caller 的 NOT_STARTED/已终止布尔值。

没有实际受控 child identity 的记录只称 REGISTRATION_INTENT/NO_HANDOFF，不称 STARTED 或 RUN-03 identity registration。真正任何 Popen、供应商请求、模型 stdin 或工具副作用之前，先 durable HANDOFF_UNKNOWN；随后登记实际 PID/starttime/boot/pgid/cgroup，另 CAS authorize release，最后实际 started ACK。发送成功不是 started。

REGISTER 后使用独立 Runtime guard：核原 READY/INTENT 的完整历史 proof 与 Budget origin，再核当前 registration lineage、原 Workspace claim/实际 FD、Controller、批准与候选。旧 plan current guard 要求 HELD/NOT_AUTHORIZED，不能用 skip_guard 或改写旧 source_context 适配后续状态。

## Usage 来源与结算

固定实际 producer/source 句柄使用 NOFOLLOW/NONBLOCK regular-file 检查、原 inode/路径/producer identity；先核 registration/lease/session/generation/plan/model/profile/semantics，再有限读取完整 JSONL。每 poll 限行/字节/节点，partial tail 不推进，替换、截断及同 offset 变更拒绝。持久稳定 backend thread/turn/event ID、原 source position/hash 做幂等，不无界聚合 observations。

累计与增量分别处理，父 inclusive totals 不再与子 totals 相加。缺计数、失联/错误、cached 大于 input、未知语义保持 UNKNOWN，不记成零；价格仅 estimated，实际 invoice 未有可信来源仍 UNKNOWN。只有实际 owner observed receipt 才能驱动 settle/adjustment，通用 JSON、模型正文、CPU 工具 stdout 或旧 session 字段不是结算许可。

## 放行与停止仍欠缺

cgroup 整树限制、磁盘硬 quota、model access、数据 manifest/provenance、命令模板/network enforcement、候选写范围及 bootstrap 必须实际验证。严格任务缺任一保证仍拒绝，partial/RLIMIT 不冒充 cgroup 保证；本设计不批准创建 cgroup、sudo、模型或 GPU 调用。

STOP 先 durable STOP_REQUESTED，禁新 release/工具副作用，再协作中断、有限 TERM/KILL、原 identity 与完整受管组/cgroup empty 确认。只有 leader 死亡或 ACK 文件存在不称 STOPPED；不确定保留池和预算曝光。重用有限 worker/guardian 思路但不绕过 BOUND legacy 门。

## 必要确定性证据

两项目/两进程第 4 slot 拒绝；fork/替换/boot/restart 不 adopt；两库 COMMIT-before/after 丢返回不释放或重复 handoff；CANCEL/REGISTER 一赢家；copy/generic/source 欺骗拒绝；usage 累计重复、父子范围、partial/truncate/replace/缺计数；实际无害 held-process 身份只证明 fixture 原语，不证明完整 model/data/OS/runtime 门。所有 suites 串行且冻结输入，真实模型和训练仍需单独批准。
