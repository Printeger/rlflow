# 阻塞与证据缺口

目前仍可推进开发，没有需要终止完整 Goal 的外部阻塞。

Checkpoint17归档任务cardinality与优化模式拒绝已验证，无新外部阻塞；10k短循环CPU中位数只提示后续idle诊断，不虚称5min NFR失败/通过。下一项组合真实100k/10k、有限实际idle/活跃工作与B1；完整M1/M2–M5继续保留。

Checkpoint16单对象真实100k历史终态/完整性/ratio1.041488已验证，无新外部阻塞；完整B1、任务cardinality、活跃reconcile/idle/维护并发/RSS/WAL和长期证据仍未完成。M1_ACCEPTANCE_REPORT.md明确列出范围，下一项继续实际10k任务测量，不把单轴通过当完成或阻塞。

Checkpoint15 已移出周期快照全状态构造并通过586/32全回归、独立37项和browser20项，没有新增外部阻塞。full-state builder仍非chunk/硬RSS/硬时限；发布BLOB、WAL retention、大规模尾延迟/idle与B1未完成，已有metadata损坏仅fail closed非自动repair交付。继续性能分轴测量和热路径整改，再完成M1 gate进入M2–M5，不将单样本锁占用探针冒充完整验收。

Checkpoint14：telemetry SSE/资源UI开发缺口已补，High两项迟到generation/排队续鲜finding已关闭，scope/source因果与optional发送错误隔离复验通过。B1/周期snapshot/首次历史性能与M1 gate及M2–M5仍是待开发/验收，不是需要停止Goal的外部阻塞。真实HOST浏览器数据不冒充真实vendor/工程科研闭环。

Checkpoint13：真实资源来源、loop heartbeat、非阻塞latest slot与项目scope只读API已实现。独立复核发现的陈旧FRESH、轮转丢witness、防御性JSON异常边界和同sid新generation误关联已修复；telemetry SSE/资源UI/B1/M1 gate仍属开发缺口，不是外部阻塞。只有监督循环心跳，不宣称模型活动或完整进程树资源；不会启动付费模型/GPU来填证据。

Checkpoint11：private VERIFIED返回固定历史task关联，旧缺字段保持未知；公共projection/log/API/UI仍待实现，属于开发缺口而非外部阻塞。不得用当前session回填旧任务，或直接把private receipt放入公共allowlist。

Checkpoint12：公共工具返回projection/log/API/UI代码已接入；High task digest与损坏/恢复覆盖边界finding关闭。仍可自主推进资源telemetry/worker freshness/M1 gate与M2–M5，无新的外部阻塞。旧ledger历史不隐式回填，损坏tool coverage保留RESYNC_REQUIRED等待显式离线恢复，而非重置未知历史。

Checkpoint08：private工具返回事实基础与全回归455/32通过，独立High范围无MUST_FIX。公开collector尚待开发而非外部阻塞；需要bounded发现、可信release/权限核验、事务幂等写入，不能将现private context/hash当放行证明。其余环境证据缺口如下保留。

Checkpoint09：执行前REGISTER/有界reader与全回归478/32通过，High父目录durability finding关闭。继续core pending/事务offset与公开collector，没有新的外部阻塞；partial尾修复、源恢复/历史coverage不能静默处理，仍属待实现恢复合同。

Checkpoint10：private core collector与冻结505/32通过，High异常隔离/Unicode上界finding关闭，没有新的外部阻塞。下一步公共tool projection/log/UI及资源；disk raw、安全repair/restore迁移、周期snapshot全量maintenance、严格逐工具STOP仍是开发/验收缺口，不可据private ledger通过宣称完整M1。

本切片故障不是外部阻塞：冻结全回归暴露 guardian teardown race 与角色可写 default guard 控制目录，已经按完整真实身份和控制文件隔离修复，最终 r3 368 passed / 32 skipped，High 范围内阻塞 finding 全部关闭。没有删除测试、延长业务终止门槛或忽略 cleanup 错误。

1. 原 Codex 版本不匹配已修复：0.161.0 的工具注册、隔离测试通过；使用独立空 HOME 的固定 census catalog 与本机 localhost 拒绝端点，零模型调用。真实 runtime 的供应商 usage/interrupt/恢复仍未验证，不能把 doctor 通过当作真实业务闭环通过。
2. cgroup v2 存在，但未证明本项目拥有可委派 subtree；严格任务拒绝执行。后续资源测试先验证能力，不能修改宿主安全配置绕过。
3. 真实模型、GPU、付费资源未获单独精确运行授权。可完成普通本地代码、模型无关测试、实验与故障验证；真实供应商闭环属于独立证据缺口。
4. 24h fixture / 8h 浏览器 soak、B1 性能、干净安装、迁移及最终审查未执行，不能用短测试替代。

pytest 默认加载宿主 ROS 插件时缺少 lark。已通过 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 使用项目隔离测试入口，不修改宿主包，也不删除项目测试。

Checkpoint18真实组合idle未达标：300s daemon-only单核CPU1.773328%≥1%，逐秒全控制文件watch也不满足NFR06无全仓库轮询。本项为可继续诊断/修复的开发与验收缺口，不是权限阻塞。下一优化无工作view/key枚举与事件失效代码guard，保留安全门；完整API/B1/长期与M2–M5仍未验证。见IDLE_PERFORMANCE.md，原证据保留。
