# 固定参与者终态内核用量

Checkpoint70 已将原固定 CPU 和工程参与者的实际内核终态用量接入既有认证资源接口、SSE 和 Dashboard。必要影响回归、最终窄修复验和独立 High 审查已完成，无剩余 MUST 或 live 测试，进入归档提交。69 已提交 `c04442e2ec1afb314ba879162593329b29113a25`；未重跑其未改变的快照验收。

## 交付行为与来源

在原 gated Source 调用原 `subprocess.Popen` 并登记强引用后、首次 poll/wait 前，为该实例安装有限 wait4 观察钩子。不改全局 waitpid，不绕过原固定 argv、环境和程序 FD 守卫；仅 Linux CPython 3.12 支持该观察路径，其他环境保持用量未知。

成功收割产生 `LINUX_WAIT4` 的 user/system 微秒、峰值 RSS 字节、真实退出码及收割时间。CPU 是原固定参与者全生命周期累计值，覆盖启动和等待阶段实际消耗的 CPU，而非把等待 wall 当 CPU；峰值 RSS 不是当前 RSS、内存预留或进程树求和。Linux 的 rusage 可包含已等待后代，因此只有当前固定且不派生后代的 CPU/工程程序适用该窄范围，不扩展到任意命令或整树。内核字段含义见 [wait4](https://man7.org/linux/man-pages/man2/wait4.2.html) 与 [getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html)。

原 `FixedUnitTelemetry.sample()` 显式采样后，将独立可空 `final_usage` 发布到现有资源 DTO。GET 和 SSE 仅读内存，不 poll/wait、不启动任务、不采样，也不把采集器中后来出现的结果升级到旧槽。观察不写业务事实、预算、version 或 cursor；模型账单与真实供应商成本仍为 UNKNOWN。

## 失效与可靠清理

原 Popen 的 waitpid 锁继续协调并发 poll/wait；fork 在继承锁之前拒绝。外部已收割、缺失采集器或观测转换失败均为未知，不填零，也不改变实际收割退出状态、STOP 收尾或 FREE 合同。内核结果只驻留原 owner 内存，重启后的历史未知，不冒充持久计费来源。

实时 CPU/RSS 在取消、退出、时钟回退或样本过期时撤回；已采样的终态累计值在原绑定有效时保留 as-of。采集器、原 producer 或原 owner 绑定失效时终态值也撤回；恢复指针不能复活旧槽，仅显式新采样可重新发布。

真实采样序号步长为 8；原实时撤回占 1 或 2，终态撤回独立占 4，最大偏移 6，不碰撞下个真实采样。撤回不刷新 observed_at、source_state_version 或原时钟；SSE 和前端可接受撤回，而非因重复 sample_id 丢弃。项目、Store epoch、业务来源版本屏障和 logout 沿用现有界限。

## 验收条件

真实正常 wait/poll、并发 wait、SIGKILL、外部收割、fork 和转换异常分别证明唯一实际收割及未知语义。实际认证应用分别执行原 CPU 和工程程序，核终态内核值、实时 UNKNOWN、无读侧执行及采样不改变 version；取消和过期不抹去历史终态，复制或替换原来源不得重新采纳。真实 Chrome 经既有 SSE 显示累计值，并在原 owner 关闭后撤回，同时另一项目不受影响、viewer 不发执行请求、logout 清空。

必要回归仅覆盖新增收割路径及其原 Source、Runtime、profile、有限应用、整组 STOP、资源观察和前端消费者，不用测试数量代替交付。失败及源码冻结强度分别记入 [测试证据](evidence/checkpoint-70-tests.txt)。

R3 七模块影响回归完整通过 81 项、722.93 秒；其 340 输入终态全匹配。随后只改收割与观测门分离及相应测试/浏览器夹具五个路径，其余 335 路径不变；R4 最终新模块 8 项通过、87.85 秒，覆盖实际双结果、观测失效 HTTP STOP 与并发退休读取。Node 9 项通过；真实 Chrome 1 项通过、46.14 秒，包含实际过期后无业务事件的 SSE 撤回。R1 环境插件错误与首 Chrome 旧样本过期断言失败保留；R2 未在改动前完成冻结取证，仅作早期 6 项通过证据。不是最后全库或再次七模块通过声明。

## 剩余缺口与下一项

该观察不证明供应商用量或 invoice，不用于预算结算，不是硬 CPU/memory/pids 控制、独立 quota、控制资源预留、强 sameUID 隔离或任意进程树 STOP。当前 cgroup 未委派给 uid1000；严格正向执行需管理员准备，未答的既有授权问题不是授权。产品 Reviewer 隔离合同和非零模型预算也仍待用户选择，不把开发审查作为产品 Review，不调用付费模型或 GPU。

下一切片按 T14/T21→T22 依赖选择实际可交付行为，优先明确 native 本地协议和执行权限门的缺口；若真实执行须新增授权，先问具体合同及预算，不绕过零额度。安装、B1、长期运行、独立科研 Review 和完整 M0–M5 验收保留，原 Goal active。
