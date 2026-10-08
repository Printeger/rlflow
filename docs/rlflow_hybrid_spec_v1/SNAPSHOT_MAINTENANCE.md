# 可选快照维护协议（checkpoint15）

业务写入每跨 1000 版本，只在原事务更新 singleton `snapshot_due.due_version`；不构造全状态、不新增事件/version/outbox，不更改日志、预算或 authority。`projection_markers` 部分索引避免 scalar marker 查询扫全部对象，但不解决 legacy ObjectMap 的全 key 枚举。

现有 daemon 在 dispatch 后最多每 60 秒启动一个可选 daemon thread；已有任务未退出则不启动第二个。不是第二个 supervisor，不接管开发 Goal。仅使用 CLI 写入而不运行 daemon 的库用户不会自动执行维护，可显式调用维护或原 `Store.snapshot()`。

## 一致性与发布

1. 独立非阻塞 maintenance lock 防止多个构造者。readonly SQLite BEGIN 捕获 projection 版本 V 与该版本 immutable event tip，并从同一读事务构造状态。
2. 在业务 writer lock 外解 blob、校验 schema、canonical 与 SHA；允许业务继续提交 V+1。只接受完整状态，任何失败不发布部分快照。
3. 非阻塞 writer lock / SQLite timeout=0 / BEGIN IMMEDIATE 重新核对 V 的 event tip 与当前 projection head。已有 V 快照须实际 BLOB 正文、摘要列与内容 SHA 都一致，不能只信摘要列或覆盖损坏正文。
4. 原格式完整快照与 due acknowledgement 原子提交。仅清除 ≤V 的 due，构造期间产生的新 due 留待后续。恢复仍使用原完整 snapshot + append-only event tail，并执行原 hash/version/schema 校验。

首次升级仅当整个 maintenance 表不存在时初始化，从现有完整快照版本与 core head 推导槽；不改历史事件与快照字节。已有表缺 singleton、负数/未来版本或 last_complete 无对应 snapshot 时拒绝初始化，要求显式恢复。此拒绝行为不是已交付自动 repair 工具，T23 恢复/迁移仍待实现。

## 预算及证据边界

默认 32 MiB 累计输入/最终 canonical、100k projection rows、2M 保守结构计数、5 秒协作 deadline。SQL CASE 在返回 Python 前限制 descriptor 的 UTF-8 字节（含 section/key）；blob 按剩余字节过滤并验证内容 SHA。json.loads 前计数括号/分隔符（字符串内也保守计入），防止仅以字节上界容许巨大节点树。超限、竞争、损坏、deadline 失败均保留 pending due 与旧完整快照。

这仍是 **O(projection) 的 full-state 兼容构造器，不是 streaming/chunk snapshot**。预算不是 RSS 上界；deadline 不能抢占 json.loads、schema 校验、canonical、hash、SQLite commit。长读事务仍可能增加 WAL retention，GIL 与 I/O 仍可能影响业务延迟。大规模 RSS/WAL、尾延迟、失败重试可观测性、chunk/manifest 与硬时间限制仍需验证/实现，不能据短测试宣称 M1/B1/NFR 全通过。

显式 `Store.snapshot()` 保留原 writer-locked 全状态兼容路径，并同步 acknowledgement；不把它误认为新维护的非阻塞入口。

## 确定性验证

`tests/test_snapshot_maintenance.py` 覆盖实际第 1000 次写只标记、索引 query plan、完整快照 + 新 tail 恢复、构造期间并发写/保留更新 due、实际线程暂停构造时写入可推进、字节/row/node/deadline、损坏 blob/已有正文/错误 SQLite 类型、锁竞争、旧表迁移、损坏 metadata 拒绝、publication rollback 与 rate/single-job。三个子进程实际 `os._exit` 点验证构造中、INSERT 后 commit 前、commit 后重启无半发布/丢 acknowledgement。

这些是 model-free 隔离 fixture，不证明真实供应商执行、完整科研闭环、24h/8h soak 或 B1 性能。
