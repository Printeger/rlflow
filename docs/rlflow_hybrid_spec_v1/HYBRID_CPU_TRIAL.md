# 固定、真实、无模型 CPU 数值试验：Checkpoint49

48已经提交da1d541d2f5985d84186d4e98abbf23cc475a43f。本切片不再扩展UI或纯准备组件：执行固定PI估计试验，保存原始坐标与独立计算的指标，沿原能力完成STOP及资源关闭。它是实际有限计算增量，不是完整科研Goal或Codex原生工程执行验收。

## 独立 profile 和批准

新kind为LOCAL_CPU_NUMERICAL_TRIAL、authorization为LOCAL_CPU_TRIAL_ONLY、profile为FIXED_CPU_PI_TRIAL_V1。旧PROTOCOL_CONFORMANCE origin仍闭合兼容，旧批准/JSON/复制grant不能转换。旧固定Task API过滤新kind，不能把科研试验伪标成协议Task。暂不提供通用HTTP trial创建、任意脚本、caller路径/FD、候选执行或模型接口。

保护启动的Registry必须精确登记cpu_trial tool/command与cpu_trial_rule、当前固定program/evaluator SHA、输入生成与输入SHA、全部partial限额。原已批准research Goal必须只允许该tool/command/rule、EXPLICIT_NONE外部数据、零模型/GPU/retry预算，experiment_starts具有足够可用量；收尾预留政策不变。WorkingPlan中的Codex argv不执行、不改写为本试验命令。

原owner签发CpuTrialGrant，绑定同published bundle/token/observation、原Goal/approval/config/scope；grant只绑定一个原attempt。register/COMMIT/Popen/G继续用原writer、当前完整来源和末deadline guard，重核当前grant与evaluator文件。复制、历史JSON、同key改body、跨attempt均不生权限。

资源明确compatible_cpu/partial：固定child实际设置CPU2s、AS128MiB、FSIZE1MiB，原3s未G入口期限不变；固定代码不读候选、不联网、不派生。它不是OS强制network/tree/cgroup证明；strict或不同限额profile拒绝。预算对G可能送达的原attempt保守消耗一次experiment_starts，未知发送不返还；原可证未G为0，旧protocol仍wall-only。ACK/STARTED历史事实必须推出G-attempt=True，不能用矛盾历史把启动结算成0。

## 真实执行与证据

固定LCG32_TOP16_V1，seed7/11/19，每seed128点；每点实际输出x/y/inside。固定程序报告kernel process_time_ns与monotonic wall的emit-as-of测量，不冒称父wait4最终整树CPU账单、模型usage或invoice。父评价器独立复算原坐标/inside/估计值/与baseline3的平均绝对误差，不信任worker提供的accepted或改善结论。负结果仍有效，不强求hypothesis_supported=True。

collect只接原Lease，不接caller结果JSON：原source/producer/nonce/ACK、退出0、SEALED完整SHA、有界≤64KiB原read FD、前后物理stamp必须闭合。最多384点，缺失/partial/损坏/非有限/超界不能产生结果。原CpuTrialResult缓存复用，不重算、不新Popen/G。

完整结果作为原FIXTURE_SCOPE_STOPPED Budget事件的有界字段持久化，不另建执行队列。历史校验从origin nonce、runtime producer、384点、确切completion测量及end重建唯一canonical原流并核SHA；结果的raw/metrics/hash不能各自合法却互不相关。来源和结果只AUDIT_ONLY、goal_completed=False，当前Goal证据激活/独立评审/下一步科研决策尚未接入。

run_cpu_trial执行有限原Start→读/seal/collect→finally原STOP；早STOP不启动，Stop原cap续清不再计算。结果/source FD关闭失败仍UNKNOWN/STOP_REQUESTED、Pool占槽，不退款/FREE；全部原FD关闭后才终态/结算/FREE。scope只限原固定单参与者，不称任意树STOP。

## 已发生的验证与失败（FINAL）

原smoke3467实际1fail14.92s：G时BrokenPipe，stderr/source皆0。原36791改实际batch/exit诊断而非盲重跑，1fail15.16s，batch2.2408s、退出126。随后改为不Popen的原登记闭包cProfile：原19982实际1pass9.28s，1.922M calls/0.481s，主要重复原审批/Registry校验。条件schema和CPU历史去重复修复后原98154仍1fail14.89s：batch2.1778s、G前2.8780s、末gate0.1900s，定位实际超原3秒，没有延长期限。

进一步只复用完整审批校验已经算出的binding，不增加cache/skip参数，旧_validate_approval API返回值不变；每次原lookup/Goal形状/确认view/hash/hardtoken检查继续执行。外层source与approval内部record来自不同key，明确核hk/rk/proposal_hash对应同原revision。原非执行cProfile90984实际1pass8.19s，1.588M calls/0.393s；不是运行验收或CPU性能基准。

原数值smoke12961最终252173 exit0、1pass21.00s：batch2.0147s，G前2.6659s、末gate0.1883s。实际inside_counts96/101/104，估计3.0/3.15625/3.25，平均绝对误差0.08821911547006896，baseline0.14159265358979312；worker CPU543230ns、wall1032015ns（本次as-of，不推广成性能SLA）。384raw/SHA、独立评价、持久结果、consume1、reap/Pool0、重复不改version、audit/replay/snapshot/recover、ACKFalse及raw/metrics/hash负例通过。

边界原12829实际4pass/1fail/1warning29.44s：原result-readFD真实关闭故障→UNKNOWN/占槽1→同cap重试全部关闭/FREE通过，grant复制/JSON/noG0与旧批准拒绝通过。唯一失败是新跨revision夹具没有重算contract.hash；只修夹具，不放宽断言。原73931定向跨revision与未complete源收集/noG实际2pass/1warning9.05s；未改通过的故障闭环不重跑。

唯一必要7模块integration原83562终efa0ca exit0，182pass/2warning437.80s；241全部源/测试SHA冻结且终态后匹配，manifest6672c9ecfc3f86cf5ddbafa45de1c55bd98226649b524b89daf997addb91f3fe。必要既有命令browser原71053终55ddf3 exit0，1pass16.108s（runner16.307s）：真实原key丢receipt恢复/ACK/STOP故障原key续清/reap/FREE及owner关闭通过。没有重复全部53前端或48两身份browser。编译/依赖/diff/最终241SHA各exit0，无live测试，正在归档提交49；见evidence/checkpoint-49-final-tests.txt。所有原失败/诊断日志保留，High确认的历史ACK→G、raw/metrics/sourceSHA及审批同revision三项MUST已静态关闭；一次deepcopy误报经相同SHA实码核对被reviewer明确撤回，未据此增加重复测试。

下一缺口：当前合同的证据激活/独立科研评价/有效性与下一步，以及真正工程candidate闭环；native/model/严格OS/data/network/任意树/长期/安装迁移/完整Goal依旧待验。未经授权不触发付费模型/GPU，不迁移生产或调用保护runtime。
