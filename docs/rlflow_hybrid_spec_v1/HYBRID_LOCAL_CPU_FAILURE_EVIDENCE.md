# Checkpoint 89：失败实验原日志与退出证据

可配置任务不再因非零退出而丢弃全部输出。原成功-only历史RESULT仍兼容，新结果增加闭合execution：status（SUCCEEDED/NONZERO_EXIT/SIGNAL_EXIT/DEADLINE）、原waitpid wait_status与control_terminal_reason。来自同trusted task_closed中唯一原task PID的真实reap，不从stderr或任务自报推断；历史校验重新推导并对照同原managed终态。DEADLINE保守覆盖退出状态。非成功必定机器FAIL，即使输出包含合格metric、stderr规则允许或未配置criteria，也不授Review/ConditionEvidence。

原stdout/stderr仍各64KiB raw UTF-8界、SHA绑定，原完整结果缓存前128KiB、terminal224KiB和Budget事件界不变；不可解码、超界或缺trusted report仍不归档，不由缺结果伪造FAIL/成功。原STOP、manager JobRemoved(done)、keeper kernel终态、transport/协议/所有句柄闭包和PoolFREE门不变。任务异常在sandbox+G后仅打印有限异常type/message并finally刷新两流，仍受原alarm/资源/输出限制；前G trusted准备异常不打印控制身份。日志是task-owned诊断，不是trusted科学结论。

PublicReader仅在configured_result投影可选execution，不暴露原PID/source/managed证明；前端闭schema重算raw退出状态、DEADLINE覆盖并拒矛盾PASS。旧无execution历史保持旧成功-only语义，不升级旧原事件。CLI正常返回归档失败结果的机器FAIL/exit1；88的FAILED_NO_RESULT/exit3仍用于无可归档结果异常，原context失败不发布最终report。88已通过的65秒期限后STOP证据不重复运行；其测试断言已适配新非零归档行为，不能称更新后的长时测试新通过。

实测首95039终d5f56b：1pass deadline/1fail nonzero，41.03s。失败根因是fork外层os._exit(125)此前吞异常、只成功flush，非零原stdout/FAIL已成立但stderr空。原失败保留。修后仅受影响非零、原EXACT PASS/FAIL及CLI合同stub复验96192终d10b1e：7pass60.49s；同原缓存重读不再次计start、原fullmanagedSTOP/SETTLED/Pool0、退出后cold完全一致、原wait状态/FAIL/输出被篡改拒绝。deadline原真实wait9/reasonDEADLINE、wall12；非零raw32000(125)/PRODUCER_EXIT、wall4；各experiment_starts1，合格loss0.1仍FAIL。deadline信号路径未受异常print/flush修改影响，不重复。源版本差量组合证据，不冒称最终一次整模块全绿。

纯profile19pass0.08s；原前端和矛盾DTO17pass80.46ms，实际两个公开失败DTO1pass67.75ms。High前端状态未重算MUST关闭，无新确证MUST。旧86实际安装任务原Store被当前公开history读取，验证旧success-only事件兼容（不重新执行）。编译/diff/原USERlockSHA通过、无live/新active unit；三个旧failed/failed timeout对象保留不reset。证据：[checkpoint-89-negative-evidence](evidence/checkpoint-89-negative-evidence/)，JSON是换行归一化副本，不称byte seal。

仍缺：真实模型Engineer→独立产品Reviewer→ConditionEvidence→自主接续（集中合同未批准）、strict aggregate quota、全部父进程崩溃/受管范围恢复、24h/8h与instinctRL长跑准入。下一按原批准范围推进崩溃后实验与资源的安全恢复消费，不能把历史归档当冷控制权或重新派发凭据。原完整Goal ACTIVE；本片非科学方法认证、自主科研完成、全库全绿或新安装资格。
