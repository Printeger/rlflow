# Workspace hold：checkpoint38

基于 checkpoint37 `70249f4`。当前已接实际协作目录锁、隔离 working-copy、三 private 持久域与固定 WorkspaceService 的 source/budget/Controller guarded acquire、两阶段关闭及审计/回放/快照恢复。root/High最终九modules各358pass（195.50s/195.74s），中央full原95667实际exit0，1621pass/32既有skip/1既有warning589.10s；21SHA一致、范围无MUST、compileall/pipcheck/diff0。最终证据见evidence/checkpoint-38-final-tests.txt，提交进度见PROGRESS.md。未接runtime注册/release，服务续期暂时拒绝；不是T12/ARC-01/A04完成，不是ExecutionLease。

旧组件 root/独立High各102passed（0.57s/0.58s）只绑定当时冻结6SHA。随后四modules root组合实际终态146pass/1warn30.05s，接Store后service r1/r3/r4实际终态9pass/9.26s、20pass/36.10s、22pass/25.12s；九modules integration r1实际356pass/159.06s/21SHA一致。追加2cases actual writer等待过期及large合法Prep容量闭合，actual2pass22deselected/38.63s；新版final九modules r2原89827实际terminal exit0，358pass/1既有warn195.50s，21SHA完全一致。最终High独立358pass/195.74s及中央full1621pass/589.10s已终态，见最终证据。各结果只绑定当时版本。pure关闭DTO不证明实际FD关闭，actual close witness仅由原owner实际成功关闭全部FD后签发。

## 目录锁的实际边界

`DirectoryHold` 固定保护端路径，以 NOFOLLOW 打开所有祖先，持有目录与父目录 FD，核实际 dev/ino/mount id、完整祖先链、当前 mount namespace、原 owner PID/starttime/PGID/boot、owned 0700 和 CLOEXEC。只接受 ext4/xfs/btrfs/tmpfs 且 mountinfo root 为 `/`；subtree bind/subvolume、overlay、网络文件系统的物理祖先来源无法证明时保守拒绝。此处没有使用 mount 权限，也没有为 btrfs subvolume 放宽证明。

实际锁为 nonblocking exclusive flock，绑定 open-file-description，不是可删除的 lockfile。check 核固定 `/proc/self/fdinfo/<fd>` 当前单条 FLOCK/ADVISORY/WRITE、实际 PID/dev/ino 和全文件范围；缺行、显式解锁、相同 inode 的新 FD 均拒绝，绝不在 check 中重新 flock 掩盖丢失。[Linux flock 语义](https://man7.org/linux/man-pages/man2/flock.2.html)、[Linux 当前 FD 锁记录实现](https://raw.githubusercontent.com/torvalds/linux/master/fs/locks.c)。

强 process registry 保留 lost-return hold，不随 GC 自动释放。close 逐项核原 FD 身份并关闭，不 reopen/unlink/LOCK_UN。失败仍保留实际 hold、未关闭 FD 和明确 cleanup 路径；临时祖先 FD 的关闭失败进入有界私有 quarantine，阻止继续无限申请，并支持原进程显式 cleanup。不能把 close 失败标为已释放。

Python fork hooks 在 fork 前串行 registry，子进程只 close 自己继承的 FD 副本，不 LOCK_UN 父 OFD；清空子副本和重建 mutex。父 hold 仍排他。CLOEXEC 只涉及 exec，因此显式覆盖 Python fork 与后续子 fork；第三方 native fork/untrusted runtime 尚不支持。[Python fork hooks](https://docs.python.org/3/library/os.html#os.register_at_fork)。

这是 cooperative advisory lock，不阻止同 UID 非协作写入、可信 OS owner/root 或未改造旧二进制。0700 不是同 UID 隔离。没有全面 legacy 入口 deny、独立 UID/mount/LSM 或执行 sandbox 时，不能宣称任意写保护或完整 legacy 排斥。

## 原始 snapshot 与 mutable working copy

`WorkingCopyOwner` 保护端固定实际 SnapshotBuilder 与独立私有 namespace。namespace/source/library 的词法与物理祖先 dev/ino 都不得重叠；不同 mount id 不代表不同物理目录。任何 copy IO 前重新核 startup 原链，拒绝 alias/rebind；subtree mount-root 保守拒绝保证不能通过 bind 隐藏物理祖先。模拟 alias 负例不是实际 mount 验收。

只接受原 builder 实际签发的 CandidateSnapshot，不采用相同 JSON/路径构造的对象。复用有界显式 manifest 与原 finite copy/hash 实现，复制前后核原 library snapshot，另核新 copy 初始 inventory。原 source/library 不覆盖或删除。失败保留新私有 provisional artifact，不沿可能被替换的路径做删除。

新工作副本与原 reader snapshot 路径不同。base_snapshot_hash 锚原快照描述；initial_copy_hash 锚新副本初始描述；source_executable 的 provenance 可能使二者不同，不能拿这个元数据差异冒充复制字节损坏。output_snapshot_hash 尚为 null，不在修改 working tree 后把旧 copy descriptor 伪称为当前输出 hash。原 Prepared plan/argv 仍指向原 snapshot；未来执行必须另生成绑定 working copy 的实际 plan，当前组件不提供执行接口。

实际 issued WorkingCopyObservation 使用原对象 identity，而不是 JSON/类型/id 证明。核身份先于解析 raw，拒绝 malformed/deep/oversized forged exact-type 对象。UTC 与独立 monotonic 期限最长60秒，拒绝时钟回退；所有 namespace/FD 读取之后最后采样。renew 保留同一实际 hold，增加 observation epoch，仅新 actual 对象有效。到期拒绝操作，但不自动 close FD；第二协作 writer 仍被拒绝。`close_pre_runtime` 只适用于该组件从未提供 handoff 的范围，不是 runtime STOP、已停止证明或 UNKNOWN refund。

## 实际持久接线与后续边界

WorkspaceService 固定同 Store/Registry/Preparation/Budget/Controller 与原 WorkingCopyOwner。stage 验原 MaterialWitness 并在 writer 外复制；record 用实际 stage object，同 owned writer 核原来源、Goal/approval、双期限、STOP、workspace/head/global CAS 与原 budget reservationhead。历史 acquire/close facts 可以恢复审计，但不得恢复 FD/实际 token。原事件精确fact/head/claim/初始markers、canonical input hash与indexed tip/count拒旧 HELD head、整域或非latest遗漏、假的历史回执。普通Store写在原幂等检查之前要求 actual active Workspace guard，事件改名不绕过。完整闭合顺序为Goal/Authority→Prep→Controller→Budget→Workspace。

三项为immutable workspace facts、derived per-reservation heads、immutable workspace-id claims。claim 锚原 acquire 的完整 scope/fact hash，防同 reservation 换 workspace 或同 workspace 换 reservation。初始 copy hash从原 snapshot files（source_executable=false）重算；live capture 的Controller mono须在同实际obs窗口；Budget原links和稳定origin_sources与原准备/当前source交叉核验，不能仅信摘要。Store原event证明与actualowner guard共同约束结构写入。

当前 acquire commit 失败保留本次 actual hold 可达，不自动退款/重新签发。关闭按 durable CLOSE_REQUESTED → actual FD close success witness → durable CLOSED_PRE_RUNTIME 进行；第一commit失败FD仍持有，physical close失败不发行成功证明，第二commit失败保留原actual witness。成功commit后的memory ACK若失败，可用原已知actual slot/witness与原CLOSED事件回执明确重试退休；历史JSON不能重建能力。旧obs/批准TTL过期不阻该preRuntime清理，但核心事实写仍要求当前Controller/STOP策略。服务renew暂时拒绝，须新增同事务candidate observation activation，不能先替换actual token再让COMMIT失败留下不可清理的旧持久obs。

未来 REGISTER 必须与核心 CANCEL 共用 budget reservationhead 原子竞争，并在外部 handoff 前持久化 REGISTERING/UNKNOWN intent。未知 writer 或后代未证明停止时不得因期限/Controller重启/内核 lock可获取就释放、退款或重启。未来 runtime 还需完整 legacy 入口 fencing、working-copy plan、可信 usage、主机 pool 与实际进程 STOP。

当前真实测试只有隔离临时目录、有限无害 Python 进程与文件 IO，无 paidmodel/GPU、保护项目写入、daemon 自调度开发 Goal 或线上发布。完整 M0–M5 Goal 保持 active。
