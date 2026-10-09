# Checkpoint 53：原始证据冷复算与持久机器决定

52 已提交 `37e18c5`。本切片交付 private `CpuAssessmentService.decide`，消费原 CPU lease、controller token、较早 plain appraisal key、原 client key 和全局版本。新操作实际独立复算原384点并提交不可变机器核验事实及保守下一步，不调用模型/GPU，不再启动 CPU 试验。

## 行为和验收边界

1. 阶段一 `hybrid_cpu_cold_verifier.derive` 只接固定规格和原始点，不接既有 result 指标、appraisal 或聊天。独立拼写 LCG 模数/商及计数、估计、误差，不调用49 inputs/evaluate/validate_result；阶段二才逐规范字节比较原结果。
2. 完整点、种子、坐标、规格、指标不匹配是来源/核验拒绝，不冒充科学负结果。无原结果为 UNAVAILABLE / NO_AUTOMATIC_RETRY；原raw核验匹配为 MACHINE_VERIFIED / REQUEST_INDEPENDENT_REVIEW。
3. 复用50受保护 append-only appraisal事实，不新造legacy evidence/research/decision域。可选 request.prior_assessment_key、fact.prior_assessment_hash/machine_verification 只出现在新decision事实；旧请求/事实/hash/canonical inputs不回填。decision只能引用较早 plain appraisal，原terminal/result/Goal/批准/config/规则同绑定，不能引用decision形成链或循环，原UTC因果不得倒置。
4. 全原prior appraisal EVENT、terminal BudgetEVENT、Prep、Controller、Goal/批准和依赖证明；原真实STOP/全FD/PoolFREE仍是新操作前提。沿同owned writer/CAS/current Registry/实际服务guard和末TTL提交；generic writer/DTO不能注入。audit/replay/recover/manual与周期snapshot沿既有完整域tip/count闭包验证，不跳过新可选事实。
5. 新写入捕获有界16KiB verifier source fingerprint，owner启动固定，再在实际guard核当前源码未换。历史用持久 verifier_version/hash 验证固定V1算法，不读取或要求今天源码hash；未来新算法必须保留V1历史分支或显式迁移，不能使合法历史因源码更新失效。
6. 闭合机器schema、实际 bool/int 与canonical比较拒绝96.0/96、0/false混淆。原key精确重复返回旧事实 NOT_RECHECKED，不追加事实或再次启动试验；用于完整性证明的有界算术验证不属于新执行/新独立会话。
7. `.inspect` 实际返回持久机器事实与current/historical as-of；既有51cold reader可证明含decision的新事实且只暴露原有safe DTO，尚不对外新增机器决定字段或按钮。旧页面不误宣称新增review。

## 不是完成的部分

确定性机器冷核验不是 PRD ARC-05/DAT-06独立 Reviewer 会话。independent_review_status=NOT_PERFORMED、condition_coverage=[]、goal_completed=False、dispatch_enabled=False 保持。保守next是记录的有限决定，不是当前执行许可或自动派发。固定三seed、partial资源、真实费用UNKNOWN仍不升级；科研完整闭环、真正工程candidate/native及安装/严格OS/任意树/长期门继续待。

## 实际证据

- 原74456终0199aa exit0：新3case实际3pass42.48s，包括实际CPU cold derivation→持久/幂等→cold读/原prior损坏拒→恢复/过期，以及NoG unavailable；未称独立Reviewer完成。
- High只读发现三项MUST：历史动态源码hash、宽松JSON相等、decide None降级。历史身份/新guard分离、闭合类型与canonical比较、入口ID验证实码关闭；初始化fingerprint在Store bind前完成。
- 原11674终a8e101 exit0：新边界1pass23.56s，真实COMMIT丢回执、周期snapshot、历史禁止source IO、源码换pin拒与末TTL拒。
- 原41607终c766e2 exit0：新非法ID与机器float/bool混淆1pass11.80s。
- 必要受影响回归唯一原48427终fa5fd1 exit0：47pass/1warning182.40s（assessment/service/HTTP/read/snapshot＋最终实际CPU cold decision及UTC因果增量）。最终270SHA全匹配，manifest2144df2db1f9b3cdeb001721e1a206270fbf0fc6dc49a3b6f41a78bc0e411330；compileall/pipcheck/diff通过，无live测试，无并行或运行中源码编辑。

日志 `audit/hybrid-v1/checkpoint-53-*.log`，最终归档索引另见 evidence/checkpoint-53-final-tests.txt。当前无需新增用户权限；继续完整原Goal，不扩大付费/GPU/生产边界。
