# Checkpoint15：周期快照维护与 marker 索引

2026-10-08，基线 `acc9d19`，完整 Goal 仍 active。此次属于 M1 性能基础整改，不是 M1 gate/B1 或 M2–M5 交付。

业务第1000次写不再同步 full replay/canonical/snapshot，而是原事务只标记 due。readonly consistent capture → 业务锁外构造/validate/hash → nonblocking writer 原子 publish/ack 保留原 snapshot/recover 格式、旧快照与完整历史。单个可选 daemon thread、每60秒最多一次；没有第二个 supervisor 或开发 Goal 自调度。scalar marker 查询使用部分索引，legacy map 全 key 枚举仍未解决。协议/容量/迁移限制详见 SNAPSHOT_MAINTENANCE.md。

## 审查修正

独立 High 要求并已修正：新表迁移与已有损坏 singleton 区分；metadata 非负/不超 head/对应 complete snapshot 校验；descriptor 按 UTF-8 bytes 且含 section/key；已有快照必须核对实际有界 BLOB 正文、内容 SHA 与摘要列；publication 不能在 due 缺失时误认成功；json.loads 前增加保守结构预算。原子失败与真实进程死亡、真实后台线程并发均增加负例，不靠仅 monkeypatch 返回成功证明恢复。

最终独立测试 `tests/test_snapshot_maintenance.py tests/test_projection_v3.py`：**37 passed / 4.27s**，`audit/hybrid-v1/checkpoint-15-high-r1.log`。当前范围无新增 MUST_FIX。定向 r6（snapshot / projection / observation / engine）：**108 passed / 29.54s**，`audit/hybrid-v1/checkpoint-15-target-r6.log`；r1–r6 是递增覆盖的全部通过记录。

冻结全回归 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest`：**586 passed / 32 established external dependency skipped / 1 established Starlette warning / 215.49s**，`audit/hybrid-v1/checkpoint-15-full-r1.log`。compileall、pip check 与 git diff --check 通过；未删除/放宽测试。

现有 Dashboard 回归 `node --test web_checks/*.test.mjs`：**20 passed / 0 skipped / 9.44s**（sandbox Chrome、owned loopback/model-free fixture，无前端改动），`audit/hybrid-v1/checkpoint-15-browser-r1.log`。fixture/browser 均已退出；不作为真实 vendor 或 soak 证明。来源/log SHA 与终态摘要见 evidence/checkpoint-15-final-tests.txt。

## 小型锁占用探针（非 B1）

全回归结束后使用独立 TemporaryDirectory；每个大小/入口创建新 Store，以一次真实 transact_objects 保存固定 historical payload，再设置隔离 fixture due=1。计时 Store.lock 获取成功到释放（包含 publication COMMIT）；手动 snapshot 作为兼容 full-state 锁内基线，新维护使用 maintain。每次检查 source version=1、audit==replay、完整 snapshot 与 due/complete=(0,1)。没有调度器、模型、GPU。宿主 x86_64/16 logical CPUs，不是 B1 限制环境，每点仅单次样本，不声称 p95。

| ASCII payload | 手动 snapshot 总耗时 / writer hold ms | maintain 总耗时 / writer hold ms |
|---|---:|---:|
| 1 KiB | 2.972 / 2.928 | 3.957 / 2.833 |
| 1 MiB | 7.100 / 7.059 | 10.102 / 3.626 |
| 8 MiB | 43.330 / 43.238 | 63.158 / 15.825 |

原始数据 `audit/hybrid-v1/checkpoint-15-lock-probe-r1.log`。仅说明本次探针的锁占用减少；新维护总耗时反而更高，发布 BLOB 仍有随字节增长的 writer hold，不能宣传常数时间或吞吐提升。不是 old commit 实测对比、100k events/10k tasks 或 RSS/WAL 验收。

## 未完成边界

新维护仍是全状态兼容构造，不是 streaming/chunk，32MiB 输入/canonical 与2M结构预算不等于硬 RSS。5秒 deadline 是协作检查，不可抢占 parsing/validation/canonical/hash/commit。WAL retention、GIL、发布 I/O、B1 4vCPU/8GiB/100k领域events/10k任务、5min idle、24h fixture/8h browser 均不能由当前短测试证明。手动 Store.snapshot 仍锁内 full-state，非 daemon 调用者需显式维护。已有损坏元数据 fail closed，不代表自动 repair 工具已交付。

下一优先项：分轴测量固定投影10k→100k历史普通写与1000维护边界，再测试10k对象/真实公共读链；根据证据优化 validator 构造、legacy map 和活跃工作索引，完成 M1 gate 后按依赖进入 M2–M5。
