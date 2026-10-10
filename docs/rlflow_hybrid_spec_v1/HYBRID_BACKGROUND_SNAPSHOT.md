# 有限 Host 后台快照维护

Checkpoint69 已完成原有限Host私有SDK→共享单固定受限进程→真实快照/ACK→隔离snapshot加真实STOP尾部恢复。缓存请求不改变业务version/cursor，维护job占槽时拒绝第二项目mark；原STOP在实际构造完成、进入哈希前的诊断暂停中继续完成。生命周期故障与必要影响回归已按分轮证据关闭，源码独立High无剩余MUST，无live测试，进入归档提交。不增加业务调度器、HTTP功能或自动周期任务；资源强制仍为partial，不缩减原严格验收。

## 现有能力与实际缺口

新增14case采用明确分轮合成证据：R3七项、R4两项、R5三项及R7/R8末两项通过；不宣称最终新模块全跑。必要回归R6实际80pass/1fail504.61秒，原domain OSError合同修复后R7原失败及受影响清理/真实15秒超时通过；writer替换被更早原身份门拒绝，仅test文案断言失败，修断言后R8单项17.17秒通过。所有失败日志与各338冻结终态一致证据保留；compile/pip/diff通过。详[evidence/checkpoint-69-tests.txt](evidence/checkpoint-69-tests.txt)。真实SDK快照12与STOP尾部2经owners停止后的隔离backup、无DDL attach及recover闭合；test-only trace不是生产启动pin、实际哈希计算并行计时或强OS沙箱证据。低盘、晚资源门和callback期限拒绝保留pending；晚门两项是维护函数差量验收。

`SnapshotBuilder` 已按64KiB流式复制和哈希，最多4096文件、256MiB及30秒协作期限；working-plan材料同样分块并验证原stamp。Preparation复制在业务writer外。上述能力不能证明有界后台进程，也不能仅从同步入口推断心跳已经阻塞。

`snapshot_maintenance.maintain` 已有5秒、32MiB、100k行、2M节点构造边界、一致只读事务、完整历史来源校验、短非阻塞writer发布、原event tip及due核验。旧 `Maintenance.tick` 每60秒最多一个后台线程，68基线有限Host未接入它。69复用维护算法，补实际进程边界和有限Host入口；不为此改写业务事件、授权合同或旧维护语义。

原fixture已经创建并捕获 `snapshot-maintenance.lock`。`Store.attach_existing` 仅捕获writer锁，不恢复此维护身份；直接child attach后调用maintain会拒绝发布。不能用 `Store(root)` 的DDL/恢复或临时相信同名锁绕过。新工作必须继承父已捕获的精确目录链、DB及两锁inode身份，而不是从调用者路径重建所有权。

## 交付行为

原Host的私有SDK新增显式请求当前快照维护的有限操作，只接已捕获的原项目能力，不接调用者version、path、限额或JSON身份。一个原Host/Pool的已绑定有限项目（最多32原units）共享一个实际child槽，无等待队列；先占槽再标记due，忙时在任何mark之前拒绝。业务Pool最多3个active claim，不是项目总数或OS总进程上限；维护child属非业务Task的派生缓存工作，不占业务STOP槽。原进程/fork及Host身份门先于IO和锁。

请求在原Store的短 nonblocking writer/BEGIN IMMEDIATE 中核验原DB、epoch、锁身份、当前projection与event tip以及合法维护元数据，将due合并到该事务实际current version。只写派生缓存维护元数据，不改变业务events、state version或观测cursor。SDK显式请求本身是真实consumer，不在BOUND Store伪造FIXTURE事件，也不重复旧1000次写入marker测试。

独立固定工作程序复核父捕获的原项目、epoch、目录链、DB及锁身份后attach，再复用原maintain的一致读取和出版。它不构造Host/Runtime/Unit、不采纳冷能力、不继承Auth、Pool、reserve或业务program FD；不将child JSON当新cap，不将完整state回传父进程全量再哈希。结果仅报告原维护状态及完成快照版本，所有结论必须以实际原记录为依据。

工作进程有固定CPU、地址空间和wall边界、PDEATHSIG及原pidfd生命周期控制；不调用模型/GPU或启动后代业务。调用者取消/退出不提前归槽，只有实际进程终结并收尾后才可再请求。启动结果未知时保留不确定状态，不盲重启。shutdown回收原进程；fork只关闭继承描述符，不杀父job。

它是可信派生缓存写入者，会写snapshots、snapshot_due及SQLite sidecars，不是只读Reviewer、强sameUID沙箱或cgroup硬控制资源预留。GET不触发维护写入，STOP任务槽不共享维护槽；不新增长期Supervisor。

## 必需验收

真实原SDK请求标记due，独立PID发布完整snapshot及ACK；业务version/cursor不变。随后追加真实原事实，在owners停止后的隔离恢复中证明snapshot+tail闭包。不得以旧crash测试中 `Store(root)` 重建替代新无DDLattach路径。

真实hash/构造期间设置诊断屏障，证明原控制路径和STOP继续完成；不将writer出版或内核文件IO挂起误说成硬完成时限。第二请求拒绝，等待者取消仍占槽，只有真实job收尾释放。

实际超限、crash、launch失败/未知及timeout保持pending和旧完整snapshot，不伪造成功或FREE。COMMIT后丢返回不能假称rollback或清除已发布快照；恢复只核原事实。原路径、epoch、DB/锁inode漂移拒绝；shutdown及fork不影响父job或业务worker。每次失败先定位，连续同因两次不原样重跑。

## 剩余边界

当前uid1000位于 `/user.slice/user-1000.slice/session-2326.scope`，该目录root755，procs/subtree_control root644，未获用户委派。RES05严格cgroup内存/CPU/pids、控制与worker分组、独立硬quota正向仍待管理员准备；已向用户提出一次具体选择，未回答不当授权。现legacy严格缺保证拒绝、固定CPU/工程拒strict变型已有，不重复负例代替严格执行实现。

69仅补RES07固定可信cache后台进程和控制路径可用性，不能关闭完整T21/A25、硬OS资源预留、任意树、native、独立产品Reviewer、可信invoice、B1/长期/T22–T25或完整Goal。不得因这些外部缺口缩减原验收或将partial显示为strict；UNKNOWN handoff仍保占槽且不自动采纳/盲重启，未宣称SDK任意故障均可自动恢复。没有生产迁移、系统权限修改或付费调用。
