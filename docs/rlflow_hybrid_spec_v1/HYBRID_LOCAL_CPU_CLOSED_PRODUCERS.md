# Checkpoint 93：实际原 keeper 与 service 的生产者边界

交付行为：真实任务 fork/confine 完成之后、ready/signing/G 之前，可信 keeper 安装单线程 x86_64/arch/x32 fence，拒绝 fork/vfork/clone/clone3、execve/execveat、io_uring 三接口及未知新 syscall。原候选已 fork，不继承后装的 keeper filter，仍可在原沙箱里 fork/exec/setsid。不是候选权限缩减或模型调用替代。

原 held service root/control/task 的目录拓扑仅允许两个原子组，root 无进程、control 仅原 keeper、control/task 无嵌套子组。ready/G 和最终 task handles close 前核验；异常拒 G/完整终态。拓扑门独立于安全 STOP：仍先原 pidfd kill、task cgroup.kill/reap，再拒未知范围收尾，保留原句柄，不接管额外目录或重构能力。

实际 manager 原连接另核 Restart=no/NRestarts=0、RestartForceExitStatus 原 (aiai) 退出码/信号两列表均空、空 ExecCondition/StartPre/StartPost/Reload/Stop/StopPost、空 OnFailure/OnSuccess/Triggers/TriggeredBy。读取 typed array 仅接受完整空数组；非空/IO错误拒绝。source 新命令显式 Restart=no。bind ready/G 末门核，收尾在 original manager.stop 后独立核，策略异常不拦其他物理清理。仅原 full STOP 完成后策略验证成功才留 canonical same-owner terminal context 供 closed connection cleanup 重试；admission-only 不缓存，source/keeper/unit/terminal变更拒复用。这不是 durable cold policy。

验收证据：
- 首 kernel fence/额外子组/真实配置 Core fork+setsid+签名+完整 STOP/FREE：3 passed 14.98s。
- 加 manager policy 后：13 passed / 1 failed 28.44s，父 SIGKILL 原签名 cold 及 UNKNOWN/Pool1 通过；失败是正常 full STOP 已完成后 alias 退休重试在 closed socket 重查 policy，确认为产品回归。
- 根因修为原 post-STOP policy context 缓存，并按 High MUST 拒 io_uring；只受影响 kernel/purepolicy/Core normal：14 passed 14.89s。
- post-STOP 缓存五个负例：5 passed 0.03s（pure synthetic，非实际冷能力）；原 manager-close partial cleanup 重试：1 passed 15.52s。
- High 最后指出强制重启可绕过 Restart=no 的 MUST，修为 typed (aiai) 两个空列表及完整结构核验；受影响纯策略/解析负例与实际 normal full STOP/FREE/alias 重试：25 passed 14.94s。
- High 最后窄复审确认 io_uring/RestartForceExitStatus MUST 均关闭，无剩余确证 MUST；审查未执行测试或写入文件。
- 未重复已过 extra-scope 或父死 case；后续改变只涉及 keeper io_uring 拒绝和 closed-manager 同 owner 重试，前者已有最终 raw syscall 与 signed normal 覆盖，不影响既有 task evidence recovery reader。

完整命令、源版本区别、失败与结果见 evidence/checkpoint-93-closed-producers/runs.txt。JSON 为真实输出的格式归一化副本，非完整账本 byte seal。没有运行当前全库/新 wheel 安装/24h/8h 测试；82 历史全量 4 failed/2532 passed/32 skipped 不重标。

下一闭合真正冷协议：原 PROCESS/G 前持久 service 顶层 cgroup identity/topology、transport/owner identities、原闭 producer policy；用完整 signed final no-more-producers scope 证据加原进程 kernel terminal 验证物理闭包，再接可恢复跨项目预算/HostPool 对账。当前 task 签名/GC/PID death 不授 STOP/FREE，UNKNOWN 占槽仍保持；旧 source/pins 不升级。实际工程/科研独立产品 Reviewer、ConditionEvidence、自主接续及 strict disk quota/长期资格仍未完成，集中模型/GPU合同未答不调用，instinctRL 只读/HOLD，Goal ACTIVE。

参考 ABI：Linux [seccomp filter](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)；systemd [v255 D-Bus 定义](https://raw.githubusercontent.com/systemd/systemd/v255/man/org.freedesktop.systemd1.xml)。这里只用于实现接口核对，不据此声明项目验收。
