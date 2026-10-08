# 公共工具返回：下一切片实施门槛

2026-10-08，checkpoint11 High只读独立设计审查。本文是待实现合同，不是公共功能验收。

## 来源与字段

新增专用闭合tool_return公共变体与receipt→row转换，不将tool_receipts加入通用SECTIONS。至少检查COLLECTED、VERIFIED、非空fact与validation_digest，receipt/source/context/registration/fact语义一致；不能只信verification字符串。公开opaque ID、version、cpu_exec、RETURNED/TIMED_OUT/SETUP_FAILED、exit_code、timed_out、finite非负wall_seconds、固定infrastructure_error、execution_id、nullable task_id、core observed_at、PARTIAL。不公开命令、argv、cwd、输出、路径、原始context或来源hash。

execution_id来自已验证fact.context.session，task_id只来自checkpoint11冻结receipt字段；旧缺失表示UNKNOWN，不能查询当前session追认。RETURNED不是成功；SETUP_FAILED不证明命令启动，所有公共工具状态不推进execution、权限、预算或vendor/model状态。observed_at是core观察时间，不是伪造的命令发生/启动时间。

## 事务与覆盖

同Store事务提交private receipt、public row/counter、durable event与固定日志，outbox失败整体回滚。保持legacy.observed envelope可降低兼容成本，但需PublicObject严格变体、kind过滤/counter与前端同步升级。工具计数仅计已公开的验证返回，不能被理解为完整调用数。

优先live-only，并显式持久公开工具coverage起点；旧receipt不自动伪装新实时返回。如果后续补历史，必须有界可恢复幂等BASELINE，明确当前公开/观察时间。不把PENDING、UNVERIFIED、UNSUPPORTED、QUARANTINED、无journal或私有ledger历史缺口显示成零工具/完整历史。

## 日志兼容

CORE_STATUS v1按字节/字段保持旧解释：body读取会重新build历史source并比较immutable正文。不能全局改变tool_metadata、旧counted_status或模板输出。新增独立TOOL_METADATA闭合模板；每seq仍一条日志，普通与工具混合更新拆为同事务观察事件，source_event_id/output_index保持唯一。build refs与filtered-page membership复用同一个受控关系函数，tool→execution/task筛选两端一致。

## UI与验证

后端、闭合schema、reducer新kind、log-view模板/metadata验证、app标签必须同步上线。显示已验证绑定的返回记录，不用启动/成功动画冒充真实活动；仍保持raw PRIVATE_ONLY。采用Sites local-only流程，loopback、sandbox Chrome QA，不注册/同步/部署。

实施验收至少包含：VERIFIED+null或不一致fact拒绝、跨generation/冻结task、旧CORE_STATUS正文不变、live-only/BASELINE时间与coverage、事务失败/重放一次性、task/execution过滤、未知协议fail-closed、原始内容与XSS不泄漏。B1/资源/真实供应商/M1长期验收不能被该切片替代。
