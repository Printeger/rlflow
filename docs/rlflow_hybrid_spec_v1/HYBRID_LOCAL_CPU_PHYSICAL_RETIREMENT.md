# Local CPU 原执行物理退役（Checkpoint 95）

实际行为：父进程 SIGKILL 后，当前受保护 `HostPoolOwner.retire_local_cpu(membership, claim_key=..., reservation_id=..., expected_version=...)` 从原 REGISTER 解析项目，重新核验原事件、审批、PROCESS 公钥、v2 签名 scope 与整线程组终态。独立取得并关闭原 slot 排他锁后，只在 Pool 追加 `LOCAL_CPU_PHYSICALLY_RETIRED`。该 head 是可复用容量，不是旧 `FIXTURE_FREE`，更不是原 manager Job、执行许可、Review、ConditionEvidence 或预算结算。

Project/Budget 零写，原 UNKNOWN 与全额预留不变。没有原签名闭包、源坏、旧 owner 活着、锁忙、关闭失败、CAS 不匹配均不能退役。复制/派生 Pool 对象没有这个写权限。新临时 slot 的关闭失败保留原 FD，独立清理其余 FD，不在 finally 隐式重试；原报告二次捕获核 opened inode/稳定路径，失败 FD 同样强保留。对象身份检查不在 Pool 锁下取得 registry 锁，避免 fork 锁序反转。

退役记录内联完整有限 v2 signed envelope、原 Project fact/claim/lease/reservation 引用、物理证明 hash 和本次 recovery owner。历史审计验原持久事件与内联签名，不依赖临时 report 仍在，也不把新的 kernel 观察冒充旧观察。现有 16KiB fact 上限不扩大，超界保守拒绝。仍要求原 Project 事件/安装源可信并保留；这是应用 fixture 恢复协议，不迁移生产或跨 boot。磁盘责任/未知财务曝险不由容量退役退款或清除。

幂等 key 绑定原 claim，同一 reservation/原 expected version 重试只认原退役事件。COMMIT 前失败保留占槽；真实 COMMIT 后丢返回可确认唯一持久记录。槽位已被新 claim 复用时，旧请求不取得/关闭新 slot，不重放旧执行。可信 Dashboard accounting 使用同一可复用状态判据，预算来源保持独立。

验收已实际覆盖：父死含 setsid 后代→原 scope 闭包→Pool 1→0；签名篡改、复制/派生对象、stale CAS、真实 busy flock 和 slot close 故障均不追加退役；COMMIT 前/后丢返回；重复请求；原 report 移走后新受保护 owner 冷审计；同 slot 新 claim→旧请求不干扰→新 no-handoff claim 正常收尾。整个旧 Project version 不变，UNKNOWN 保留。该任务是实际恢复/槽位复用结果，不是非预设模型工程任务或自主科研结论。

证据：`evidence/checkpoint-95-physical-retirement/`。774 是 close-failure 版，final-777 是追加 COMMIT 负例后的最后实机；PID/Invocation/key 不混用，JSON 为规范化副本，非完整 ledger byte seal。分轮必要变更复验，不把四次同名不同输入测试当四项资格；旧 Pool 31pass、accounting 3pass 与 capture 2pass 另列。

依用户最新优先级，95 后不继续其他恢复增强。下一直接推进真实 Engineer→独立产品 Reviewer→条件证据→接续；最小缺口见 `HYBRID_REAL_ENGINEERING_MINIMUM.md`。集中模型/GPU合同未批准，不启动调用；本片没有模型/GPU/生产修改，也不证明全库、安装或长跑准入。
