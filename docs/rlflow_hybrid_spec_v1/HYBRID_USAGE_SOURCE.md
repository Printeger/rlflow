# 原来源有限用量观察（Checkpoint 43）

97修复已复现完整性漏账：不能过滤无计数线程后称complete，也不能在parent-inclusive时隐藏子线程缺失/空/部分计数。完整性核验全部已观察参与者，inclusive仅影响求和；已知prefix显示不变，不将缺失补零。cumulative末完整总计可覆盖原缺失快照，per-turn旧轮缺失不能被新轮完整数抹去。原实际三语义回归及新负门已定向验证，详evidence/checkpoint-97-usage-completeness.txt。此处仍SOURCE_ONLY/settlementfalse，不证明真实模型scope/CLI计数或驱动实际预算结算；不能把此补强当首次模型任务完成。

交付行为：保护 startup 的 FixtureUsageSourceOwner 从同一原 HostPool Membership/Claim 创建私有来源，保留一次原 attempt、实际 Popen/PID/start/boot/PGID/pidfd、直接 stdout 文件 FD 和原 stdin 管道。固定有限 CPU producer 直接追加 JSONL，不通过 caller Path、JSON、FD 或 capture_output 导入。原能力对象才可 poll/seal/cleanup；启动不确定不重复 Popen，不收养历史进程，不退还占用。fixture 不执行模型、工具、GPU 或生产迁移。

每次 poll 最多读取 64KiB（包括尾锚与 partial tail 校验），最多解析 128 行/32768 节点；每行最多 16KiB/4096 节点/32 层。文件上限 16MiB，64 threads/4096 稳定事件，最多 32 owners/每 owner 32 sources。只消费完整 JSONL，partial 不推进，缺计数不是零。每 poll 的回滚只复制有界线程状态，不复制全部事件历史。旧 stable-ID 重放不重复计数，也不能关闭后来 active turn；同 ID 改计数、累计回退、cached>input、overflow、重复键/非法 Unicode 等拒绝并隔离。

明确 cumulative 与 per-turn；固定 parent-inclusive 场景仅用 parent totals，不再加 child totals。忽略模型正文中的伪 usage。所有计数来自合成 CPU 协议，data_mode=fixture/source_only=true，actual_cost=UNKNOWN，execution_enabled/settlement_enabled=false；不是实际模型 tokens 或 invoice，也不能驱动 Budget settle。

实时 receipt 是已观察前缀的 as-of 记录，不证明任意旧前缀仍未改写。原 producer exit0、固定 end、完整无 tail 后进入 AUDITING；每次 seal 最多审计 64KiB，在最终稳定 stamp 下重新计算全部前缀 SHA，与实际观察 SHA 一致才 SEALED。旧前缀改写并追加不能绕过最终审计。缺 usage/failed source 即使文件封闭也不报告完整用量。替换、截断、同尺寸改写、超长行均隔离。

验收行为：真实 finite producer 的三种语义、partial 原管道续写、缺计数/失败、不接管复制能力、实际原文件损坏/旧前缀改写、bounded read、异常 ID 的整 poll 回滚、实际 Popen 身份捕获失败一次 attempt、原 pidfd 清理且池仍占额、partial close 保留重试、实际 fork 子关闭继承 FD 而父来源可继续。Pool 是唯一 fork coordinator，统一 Pool registry→Pool owners→Source registry→Source owners，避免 Python 逆序 before 回调造成 ABBA；保持 42 的原交易中 fork 零 child SQL 行为。

有限 producer cleanup 不叫 Runtime STOPPED：只证明本固定无子进程 CPU producer 的原 Popen 已回收，不能证明任意 process tree/cgroup 已空，亦不发池/预算退款。关闭后保留原 immutable historical receipt，不把 CLOSED 当新来源许可。

剩余缺口：实际 Task/ExecutionAttempt/ExecutionLease、Runtime producer 注册与可信 usage 结算；安装 CLI 的原 stdout/offline-provider 协议接线；Pool/项目 Budget 两库 matching CAS；真正执行 release/started ACK；完整执行树 STOP 与 OS/model/data/network/写范围强制。这些是下一依赖切片，不能拿 SOURCE_ONLY 的测试通过代替。详见 evidence/checkpoint-43-source-tests.txt。
