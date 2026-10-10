# Checkpoint 94：原受管范围的持久物理闭包恢复

交付行为：父进程死亡后，公开 history --recover-task-evidence 现在可以从原 PROCESS 事件和 v2 签名报告恢复 ORIGINAL_CONTROLLED_SCOPE_CLOSED。这表示历史原 Invocation generation 的受控生产者集合已物理关闭，不是同名 unit 当前永远为空，不恢复原 manager Job/控制权、FREE 或预算结算。managed_scope_status 仍 UNKNOWN，controls/condition/replay/settlement 均 false，预算 UNKNOWN 和 Pool 占槽不变。

G 前原 PROCESS 事件绑定原 service 顶层 path/root/control/task devino/uid、完整 keeper Invocation、transport/owner identity、原 proc root/PID namespace 视图、closed-producer 协议版本和原公钥。原 guard 重新比对实际 source ready、transport、origin、view，PROCESS 后不能增补/修改/删除。manager 原 ControlGroup 精确匹配；原 noRestart/强制重启列表/辅助命令等门保持 93 实测约束。

服务真实 fork/confine task 后给 keeper 安装不可逆生产者 fence。最终 task kill→全部 reap→empty→held root 空/control 仅原 keeper/无额外子组，再核同 scope 绑定；close原task句柄和output/control后 v2 签完整 scope+task_closed+outputs。候选不能得到私钥；未完整报告、未持久 PROCESS 或 v1 不得获得物理升格。v1 原任务证据兼容保留。

冷核验仅原认证 whole-event/approval/schema/pins/path/inode/stable reads/公钥验签。必须同 boot、同原 proc/PID namespace；进程终态使用 pidfd whole-thread-group poll，主线程 Z/X 不代表完整 owner 死亡，PGID 改变不算死亡；原 starttime 不同只表示 old PID generation 退役，不对新进程做控制。proc stat bounded4096/NOFOLLOW/NONBLOCK。每个新 FD 自打开起由该调用持有，fstat/identity/close 任一异常保留原 FD/已捕 actual identity；foreign 不关闭，内层 stat 失败外层 pidfd 仍独立清理。不能从 GC/not-found/PID 缺失（视图未知）推断闭包。

验收：
- 首接线纯 reader + actual parent crash + actual normal：26 passed 28.95s，早期尚未加 view/pidfd 资格，不能混称最后版本。
- 原 view/pidfd 引入后父死 1 passed 15.39s；最后 protocol/完整 Invocation/有界 stat 加入后实际 leader Z 仍 live thread 拒、父 SIGKILL v2/独立 CLI/成对篡改/Pool1、normal 原 owner live 拒升格且完整 STOP/FREE，共 3 passed 29.33s。
- PROCESS immutable 与 v1/reader 30 passed .14s；原 profile 完整 26 passed .11s（含重叠的6新纯 immutable guards，不充作新增资格）。
- High 清理 FD MUST 修复后，4 stat/pidfd fstat/close 故障+真实 zombie leader 5 passed .08s；foreign 两项 2 passed .06s。新的独立进程仅冷读原真实766 Store，namespace/scope/Invocation拒且 FD 集合、业务版本不变、原物理证明同值，exit0；不重新执行任务。
- 共享非 local Runtime 原 terminal/replay/recover/Pool cold join 必要回归 1 passed 11.80s。
- 归档前旧766临时 Store 被pytest保留机制删除，补读原PROCESS FileNotFound exit1如实保留，不能伪造原公钥。补齐原 PROCESS/公钥/raw report采集后仅父死一项必要复验 1 passed14.12s，未重跑其他实际场景；最终原事件/绑定/报告及Budget UNKNOWN/Pool1归档，离线 v2 公钥验签及同scope匹配 exit0。
- High 最后窄复审 FD MUST 关闭，无剩余确证 MUST；未测试/写入。本片没有新全库、新安装、24h/8h、产品 Reviewer/自治资格，82 历史全量4fail/2532pass/32skip未重标。

证据：evidence/checkpoint-94-scope-recovery/。不同实际运行的 PID/Invocation/公钥不能互换；actual-* 属原766，final-crash-* 属最后770。JSON 是格式归一化的真实输出副本，非完整账本 byte seal；原 pre-G PROCESS 来自实际 reader._point 完整验证后采集。最后离线验签只证明归档签名/scope值可复核，不替代原审批事件链的正式 seal。

下一实际交付：把认证物理闭包用于原 HostPool 槽的可恢复物理退役/对账，并保留原预算 UNKNOWN 全曝险；不能伪造旧 Job/FREE/SETTLED 或退款。随后补可信完整用量来源与长期跨账本故障恢复。真实模型 Engineer→独立产品 Reviewer→ConditionEvidence→自主接续、strict disk quota/长跑仍缺；集中模型/GPU合同未答不调用，instinctRL 只读/HOLD，准入包和另窗 Goal prompt 待实机资格成立。无新增需用户决定才可继续本地实现的事项，原 Goal ACTIVE。

Kernel thread-group 语义核对：[Linux v6.8 pidfd_poll 原实现](https://raw.githubusercontent.com/torvalds/linux/v6.8/kernel/fork.c)。该资料用于接口设计，不作为实际项目测试的替代。
