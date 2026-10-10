# Checkpoint 91：原任务证据的崩溃后恢复

交付：父进程 SIGKILL 后仍能读取原任务 stdout/stderr、原 keeper 的任务退出状态和控制终止原因，并按原批准 spec 重算机器验收。公开入口是显式 `history --recover-task-evidence`；不自动扫描目录或重新执行任务，不恢复 Controller/lease/manager 权限，不结算 Budget、不释放 Pool。原普通 history 仍如实显示 UNKNOWN/no terminal。

```sh
python -m rlflow.isolated_local_cpu history --root /absolute/original/store --store-epoch ORIGINAL_EPOCH --reservation-id ORIGINAL_RESERVATION --recover-task-evidence
```

来源与安全边界：

1. 原 allocation 预分配 private task-report 和输出源；HANDOFF 前持久路径、物理 chain、原 inode/uid、config SHA 与 source/unit 标识。partial allocation 不发布不完整 binding，原 no-launch 清理仍可收尾。
2. keeper 在真实 task fork、关闭控制 FD 并完成 sandbox ready 后才生成 Ed25519 私钥；私钥只在 keeper 内存，任务 fork 内存/磁盘/config/日志均无私钥。严格闭合 ready 协议只给公钥；原 manager/keeper/task 绑定成立后 PROCESS 原事件首次记录公钥，后续不可变，原 G guard 复核。
3. 原 task/后代停止、reap 和输出 fsync/FD closure 后，keeper 对带独立 domain 的完整 canonical task_closed + output hashes 签名，原报告文件一次 append/fsync，之后才写父 stdout。父死亡造成 stdout BrokenPipe 不丢已经持久的报告。
4. 冷读仍验证原 Budget whole-event/links/approval；仅使用原事件公钥，核原批准 libcrypto hash。NOFOLLOW/NONBLOCK、regular/private/single-link/原 inode/chain、文件读前后 stamp 和输出 hash 全部门控。精确 key32/signature64、独立 libctx、default provider、无 load_config 或 fallback。成对改写报告/输出及伪退出状态仍被验签拒绝；missing/partial/无原公钥历史不升级。关闭每个读 FD 时核本次实际 opened identity，独立尝试全部关闭，失败/未知句柄保留在异常上。

使用本地已有 libcrypto，无依赖安装、网络模型或 GPU。[OpenSSL Ed25519 one-shot 签验](https://docs.openssl.org/3.0/man7/EVP_SIGNATURE-ED25519/) 与 [独立 library context](https://docs.openssl.org/3.0/man3/OSSL_LIB_CTX/) 为接口依据。整个文件系统/可信 Core 被同 UID 全面替换仍不属于此协作式 trust root 的抵抗范围；本片拒绝的是输出和报告源内容被改写，不声称能抵抗可信 Store/代码同时被攻陷。

验收结果：

- 首未签版 1fail/2pass45.62s，内部测试事务接线修后受影响 1pass13.54s；未签证据不称认证通过。
- 签名版真实父 SIGKILL + fresh CLI + paired forgery refusal、正常 full managed STOP/FREE、no-handoff、deadline：4pass65.30s。原 keeper/leader/setsid 后代的死前 pidfd 全终态，unit GC；原 budget UNKNOWN、Pool occupied1/no claims、controlsfalse、不退款/不重放。
- 独立窄审 source integrity/partial allocation/FIFO/FD cleanup MUST 全关闭。最终 pure/CLI 合同和真实 partial allocation no-dispatch 收尾 49pass9.09s，FIFO/replacement FD 回基线、close-fault 保留原失败 FD；签名运行未被最后异常 read-close 差量影响，不重复运行。当前最终 CLI 冷读同原 signed recovery，exit0；签名 suite 后只有 read cleanup 与测试变化。
- compile/diff/USERlock SHA 检查通过。原 4 个旧 failed unit 保留，无新 active/积累；不清历史。分轮命令、终态、JSON/publication binding/report 见 `evidence/checkpoint-91-crash-recovery/`，格式化副本不是 whole-event byte seal。

明确剩余缺口：这证明任务证据来源，不证明完整 manager scope 的同 Invocation STOP/job、keeper 自身终态或安全结算能力；UNKNOWN/占槽仍不能自行收敛。报告缺失、私钥生成前父死亡、原 PROCESS/公钥持久失败仍保持 UNKNOWN。没有 power-loss/24h/8h、当前安装或全量回归资格。真实模型 Engineer→独立产品 Reviewer→条件证据→自主接续尚缺集中资源合同答复，strict diskquota、科研闭环及 instinctRL 实机准入未完成。固定故障 fixture 不计自主任务完成。

下一片行为目标：使崩溃残留的原受管资源及占槽能够按可信恢复协议安全收敛，先解决原 manager 证明失去后的资格门；验收须原 scope/预算/Pool 一致、无重复执行或计额、缺证据仍 UNKNOWN，不以新 bus/name lookup 重建旧 STOP 能力。不以更多准备组件/fixture 数量代替该行为。
