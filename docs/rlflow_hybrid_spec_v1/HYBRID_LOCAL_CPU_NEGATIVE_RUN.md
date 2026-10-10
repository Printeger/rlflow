# Checkpoint 88：实际长时失败执行与原 STOP 报告

公开入口 `python -m rlflow.isolated_local_cpu run --parent PRIVATE --spec JSON --approve-isolated-local-cpu` 仍须原精确 scope 确认，未增加授权、重试、模型或 GPU 能力。现在原 run 返回成功结果时报告 `execution_outcome=RESULT_ARCHIVED`，原机器 PASS/FAIL/NOT_CONFIGURED 的退出码 0/1/2 不变。原 run 抛异常但原历史验证及上下文收尾成功时，输出 `execution_outcome=FAILED_NO_RESULT`、result=null、原历史及 Pool 快照，退出码 3。不把执行异常变成机器 FAIL/独立 Review。

原 run finally 尝试原 STOP，context 仍执行原生命周期收尾；本片不新增执行或外部 Supervisor。报告的 history/pool_after 是原 run 后、context 退出前读取的 as-of 状态，不因 context 后续清理而升级为更晚状态。如果历史验证或 context 收尾失败，则异常继续传播，不发布最终报告，仅保留 G 前已发布的 historical_recovery locator。异常类型和消息不进入新公开报告；因此详细失败诊断仍需要下片原日志证据，不将这个有限报告宣称为完整失败分类。

实际验收：一次新批准的本地研究配置，读取 measurements、打印均值、等待65秒后非零退出；任务期限90秒，原预算reserve wall100/start1，原 Controller/workspace/Pool 初始60秒，不延长或续期。真实原 task wall69、consumed wall69/experiment_starts1、managed manager JobRemoved(done)/kernel terminal/全原关闭、FIXTURE_SCOPE_STOPPED/SETTLED/Pool0；context退出后只读cold与报告history完全一致。测试原55052终fb8bd6：1pass81.80s。只证明原既有授权到期后安全收尾，不证明跨崩溃恢复、24h/8h或自主科研。

4个CLI合同stub回归0.19s验证原三个机器退出码以及context异常不发布最终报告/原run仅调用一次。stub不作为运行或STOP资格。独立增量只读审查无新增确认MUST，compile/diff检查通过；仅三个既有failed/failed超时unit保留，没有新active unit，未reset-failed。用户package-lock SHA不变。完整证据：[checkpoint-88-negative-runner](evidence/checkpoint-88-negative-runner/)。JSON副本换行归一化，不称byte seal；本片未运行安装态/全库/UI重复测试。

下一必要行为：非零退出/超时的原stdout/stderr及实际退出原因要作为有限持久实验诊断证据，而不能因为打印了合格metric就给PASS。当前结果collector只接成功退出，FAILED_NO_RESULT历史机器UNKNOWN/ReviewNOT_PROVEN/conditionfalse是诚实缺口，不是失败科研验收完成。真实模型Engineer→独立产品Reviewer→条件证据→自主接续仍待集中资源合同批准，strictquota/全部异常STOP与长期恢复/长跑/instinctRL准入仍未完成；原完整Goal ACTIVE。
