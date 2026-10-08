# Checkpoint 01：基线、协议与事务观测基础

任务 ID：T00–T04 初始切片（后续验收仍有未完成项）；完整范围 M0–M5 不变。

改动：基线审计与差距矩阵；无凭据能力探测；本机 0.161.0 的隔离兼容；闭合 JSON Schema/语义校验；opt-in 原事务观测桥与追加 outbox；独立对象版本、有限 counters、只读快照与索引分页、源版本/序列校验、公共字段白名单和脱敏。

边界：没有新 scheduler、没有本次开发 Goal 的 rlflow 调度、没有真实模型/GPU、没有修改生产状态或网络开放。旧批准/预算/原始事件不被迁移为新授权。原生子代理和严格资源能力未证实时禁用。

输入/输出：`Store` 原始 patch → `legacy.observed` 类型化观察；公共实体只代表旧状态的可观测字段。旧 session RUNNING 在 ACK 未核实前显示 STARTING，角色报告接受不表示 Goal 成功。UNKNOWN 不记零；费用无账单为 unknown。

故障验证：原事务 rollback、实际进程提交前/后退出、重放幂等、旧游标/epoch、源投影不一致、序号断裂、缺失 usage、敏感正文/ID/路径、readonly 写入拒绝、真实内核单写/只读边界。记录见 IMPLEMENTATION_VALIDATION.md。

资源影响：公共事件分批上限 200 对象，snapshot 上限 30，分页上限 200，counter 状态有限；正常读/写不全量重放历史。一次性 enable 导入已有可观察投影，仍需 B1 大规模实测，不能宣称 NFR 达成。

独立 review：`hybrid_architecture_review` / GPT-6.1 Sol High；当前 checkpoint MUST_FIX 已关闭，详见 ARCHITECTURE_REVIEW_M0.md。最终交付审查尚未执行。

尚未验证：T05 实际启动 ACK 生命周期、T06 HTTP/SSE/认证/背压、T07/T08 真正 UI、M2–M5 全部完整门槛，以及 100k/24h/8h NFR。

迁移/回滚：观察表是旧库增量新增，不改旧事件 bytes；旧源码只读审计可忽略新表。切回旧执行器必须先停止新派发并核对活跃/UNKNOWN 工作；它不维护观察表，因此不可让新 UI 静默显示旧投影。新 reader 发现 source_version 漂移时 fail closed。正式生产迁移/回滚合同仍属于 T23，不在本 checkpoint 声称完成。

本记录的 Git checkpoint 将以 `hybrid-v1` 分支提交保存，未自动 push。供给的需求包作为版本化开发输入一并保留；原有无关 `package-lock.json` 不暂存、不修改。
