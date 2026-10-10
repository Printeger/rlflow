# 有限审计应急空间与同源诊断

Checkpoint 68 在 67 的共享文件系统准入上接实际 blank 分配、STOP 消费和现有 Dashboard 诊断。新增行为与必要回归已通过，进入归档提交；完整 Goal 仍 active。证据见 evidence/checkpoint-68-tests.txt。41–67 不重启，不改变原 M0–M5 验收。

## 实际行为与权限

首次原 SDK/认证 HTTP RUN 在写 request 和 HANDOFF 前，每个原绑定 FS 分配一个 8MiB blank；最多三个 FS，名义总上限24MiB。使用原私有 Pool/runtime 目录，working 独立 FS 时使用原同 FS 私有父目录；无法验证同 FS 就拒绝。原链、dev/fsid、目录身份及权限必须一致，文件要求原 FD/命名 inode、600、单链接、不可继承、尺寸上限及 mtime/ctime。posix_fallocate 后 fsync 文件/父目录并检查实际 st_blocks，不用 sparse 文件替代。原对象先登记再 IO，分配后重新读可用量，实际已分配块不加回余额。

所有原绑定 FS 完整分配才称 ready。明确 pre-open pending 可在同对象恢复；已持有 parent FD 经原目录验证后复用。真实部分分配或 fsync 失败保留原 FD 和 stamp，可在未消费时恢复。creation_entered 但没有原文件 FD 属 UNKNOWN，不能按名字采纳、重建或伪造成功。没有冷启动 adoption 或跨重启额度恢复。

STOP 在第一接受事实和 Pool 等待之前验证物理可用量及原身份，不依赖损坏账本读。明确低盘或未完整分配的原 owned reserve 先纯冻结新效果，再持原 Pool 截断原 blank 为零并 fsync。未知统计/身份只冻结，不按路径截断。明确无文件的早期准入拒绝不永久冻结，保持67原 body/key 空间恢复后可执行的验收。已经 HANDOFF 的缺失救援容量则保守冻结。

同一原 RUN/HTTP STOP operation 的 fallback 复用首次 rescue 结果，包括失败，不自动重复截断。新显式 STOP 可重试原部分失败 FD。释放失败仍使用原66物理回收，UNKNOWN 不伪 terminal/FREE；已消费预留不能补充新工作。正常 worker STOP 不紧急冻结，否则会错误阻断工程 apply。原最终 Auth 后还有纯内存冻结门，资源 IO 不后移到 G/pwrite/COMMIT 的最后授权之后。Pool shutdown 失败保留唯一 owner/FD；fork 子进程只关继承 FD，不截断父文件。

CPU source-only poll 完成原有有界审计后，以原 Project 只读 snapshot 查 phase，不等另一项目的 Pool 效果锁。真实 ACK 新事实仍取 Pool 并重读 phase，只有仍为 RELEASE_INTENT 才经原 guard 写 STARTED；STOP 优先。spawn/G/pwrite/collect/STOP 原锁、4s结果期限、3s worker watchdog、CPU384与工程21门槛不变。

## API 与 Dashboard

GET /api/v1/finite-host/disk-admission 延续67认证、无查询、独立容量1读取池及读取后重新认证。闭合 DTO 新增 audit_reserves、emergency_frozen、reserve_profile。每个 reserve 仅含 allocated_bytes、logical_bytes、allocation_complete、released；不暴露路径、FD、凭据或能力。reserve_profile 固定 SMALL_BEST_EFFORT_NOT_COMMIT_GUARANTEE，audit_reserve_allocated 仅全覆盖且未消费才 true。

冷态 GET 返回空 reserves，不分配、不写 Store/Pool、不执行工作；此时 new_run_admissible=false，真正 RUN 可按原早门分配并重新准入。前端只手动同源 GET，不自动轮询、不以诊断 gate STOP。校验67固定 headroom 公式及 credit≤32，拒绝自报低阈值、非法额度和畸形 DTO；来源 UNKNOWN 明确显示。项目切换、退出及晚到旧认证响应清除/拒绝私有 DOM。

## 验收记录

新增 reserve 场景采用分轮合成证据，不称最后新模块一次全跑。R1 3pass79.57s，R2 5pass86.12s，R3 4pass79.15s，R4 4pass87.11s；R4 的 pwrite 参数最初只证明 intent 早门，独立审查后 R5 仅加强该参数1pass27.90s，验证原 FD 已开、_apply_once 最后 Auth 后冻结且 pwrite0。Node最终6pass133.16ms；Chrome真实1pass31.83s，GET不写/不分配、实际CPU384、STOP及私DOM清理，不重跑未变浏览器流程。Chrome pins 是冻结期间捕获，不虚称预启动。

必要受影响 R6 38case自然终态36pass/2fail834.55s，原失败保留。早拒inode恢复失败已定位并R7原失败项+3实际恢复场景4pass89.28s。另一失败是共享Pool等待；R8诊断单项1pass63.33s捕获CPU seal10ms、poll5.117s与工程apply5.128s重叠，不能凭该次pass关闭。修复后R9实际只读poll/STOP间隙、原parentFD复用及原双项目端到端4pass106.13s，CPU384/工程21/一次pwrite/最终占槽0。最后仅新poll影响的原ACK、STOP、expiry、lost-return、badACK、恢复、tamper、部分关闭、fork及停止后文件增长12项通过134.48s，不重复已通过38项或旧全库。335最终输入、各轮pins及完整原始日志SHA已归档；编译、依赖、diff检查通过，无live测试和新增MUST。开发High不替代产品 Reviewer。

## 剩余缺口

这是有限最佳努力容量，不是硬 quota、STOP COMMIT 保证、真正填满 FS、三真实独立 FS、强 same-UID 隔离或完整 RES07/A26/T21。外部写入、WAL、inode及project quota仍可耗尽；应急消费不等于任何账本写必然成功。没有删除证据、生产迁移、系统权限变更或付费模型/GPU。

原 native、独立产品 Reviewer/正向 ConditionEvidence、可信 invoice、严格 OS/任意树、安装/B1/24h fixture/8h UI、T23/M5 和完整 Goal 尚未完成。下一切片须依据依赖交付可运行行为并单独列验收，不能将本片组件或测试数量当作整个需求完成。
