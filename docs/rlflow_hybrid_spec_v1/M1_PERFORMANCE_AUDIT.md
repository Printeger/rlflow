# M1 性能审计与下一实施入口

2026-10-08，checkpoint14源码8f91f7b。此文是静态审计和小型只读query-plan证据，不是B1通过报告；不以没有benchmark结果宣称NFR达标。

## 已确认热路径

- `Store._commit` 每1000次write在BEGIN IMMEDIATE/writer lock内调用`self.replay(db)`，全projection解blob、canonical整state并INSERT snapshot。这不是每次普通写全历史events replay，但会产生与projection规模相关的同步维护尖峰。
- `Store.view` 的 scalar query `SELECT section,value FROM projection WHERE object_key=''` 在现有索引上需扫projection；随后每个`ObjectMap.__init__`枚举该collection全部key，即使调用者只取一个对象。
- legacy `Store.transact` 取得view、逐map changes与提交后再次return view，因而不能将“body lazy”误说成“key discovery bounded”。`transact_objects`只读取/核验明确selected set，已有增量安全性质应保留。

根只读临时Store执行`EXPLAIN QUERY PLAN`（fixture已清理）：

```text
SELECT section,value FROM projection WHERE object_key=''
(2, 0, 0, 'SCAN projection')
SELECT object_key FROM projection WHERE section=? AND object_key!=?
(2, 0, 0, 'SEARCH projection USING COVERING INDEX projection_status (section=?)')
```

NFR-10要求固定当前projection规模下历史events从10k→100k普通写p95比≤2；B1另含10k任务。必须将“历史长度”和“projection cardinality”分轴，不能由上述静态发现虚称普通写随历史events线性增长，也不能通过缩小projection/删除历史绕过实际B1档案。

## 下一动作与约束

先建立deterministic benchmark：保持同projection分别10k/100k历史，另测10k对象cardinality；分开普通write、恰跨1000的maintenance boundary、bounded public snapshot/page/SSE与core hot view。捕获p50/p95/max、RSS、writer lock时长、SQLite query plans、真实硬件与B1档案差异，不将宿主30GiB/多核实测冒充4vCPU/8GiB限定环境。使用独立fixture和model-free runner，不启动开发Goal调度器或paid/GPU，不让大benchmark与回归并发干扰timeout证据。

独立High建议的最小快照方向：`_commit`同事务只记录small snapshot_due版本槽，不新增core event/version；单个maintenance从readonly BEGIN一致快照捕获V、immutable event tip与projection，锁外构造/validate/hash；短writer事务重新核对immutable tip后发布完整snapshot V，清理仅≤V的due。新core写允许继续；构造/崩溃未完整发布一概不用于recover，保留旧完整snapshot+完整事件tail，不改outbox/log/epoch或历史事件字节。

这只是待验证设计：首次锁外full状态构造仍O(projection)/RSS，不等于流式bounded；必须有single-job、失败保留due和WAL read transaction期限/abort，后续chunk/manifest才可声称内存有界。显式Store.snapshot/原snapshot兼容、digest与version核验、恢复tail校验、idempotency/expected-version/事务rollback/单writer均不能删除或弱化。lazy map改造须单独测试membership、delete/clear/pop、original mutation检测、callback授权读取和consistent read snapshot，不能为省keys破坏authority语义。
