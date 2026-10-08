# 历史长度分轴测量（checkpoint16）

2026-10-08，产品源码基线 `4623b42`。新增 `tests/acceptance_history_v1.py`，不修改生产行为。此次为 warm sequential / 单 usage 对象固定 cardinality 的真实 core/public history 探针，**不是完整 B1 或 M1 gate 报告**；version/counter 数字字节仍随历史增加，不承诺整投影逐字节相等。

## 运行与判定

```bash
.venv/bin/python -m tests.acceptance_history_v1 \
  audit/hybrid-v1/checkpoint-16-history-r1 \
  --checkpoints 10000 100000 --samples 200 \
  > audit/hybrid-v1/checkpoint-16-history-r1.log 2>&1
```

输出目录必须不存在，绝不覆盖原 fixture 或删除历史。每个 event 经实际 Store.transact_objects 与同事务 observer；不 bulk import/_commit 绕过校验。每个预定检查点保留最后200次写，普通写与跨1000边界分列，同时保存全程1000边界样本，不能挑快样本或隐藏尖峰。p95 使用 nearest rank，锁计时从获取 flock 成功到退出锁body（含COMMIT，不含获取等待及flock释放syscall），总耗时另报。

public snapshot/page/最后100条event直接经 ObservationReader，各30次查询；**不包括 HTTP/auth/SSE transport/浏览器可见延迟**，不能用于证明 NFR-01/02 端到端。每个检查点的可选 maintain 在写窗口之后单独测量，不伪称 daemon/维护竞争负载已覆盖。最后 recover==audit==replay 完整核对；该最后全历史 audit 不在热写计时内。

RSS 是该单进程累计 ru_maxrss、检查点发生于最后 audit/recover 之前，不是控制+API合计 RSS 或最终峰值。宿主 x86_64/16 logical CPUs、无硬件资源限制，不冒充4vCPU/8GiB。无模型、调度器、GPU、浏览器或付费调用。

## 当前证据

- 驱动/快照/投影定向回归：40 passed / 3.20s，`audit/hybrid-v1/checkpoint-16-probe-unit-r2.log`。首轮1 failed/2 passed 是短unit profile尚无1000边界却断言维护必须成功；改为按实际pending槽核对，保留失败日志和原维护条件，没有伪造due或放宽生产合同。
- 初始10k检查点：core events=10000、public events=10001（含初始公开记录）、projection rows=14、usage rows=1。普通写p95=8.337045ms，writer hold p95=8.293555ms；直接snapshot query p95=0.594425ms；该检查点single-process累计peak RSS=39556KiB。原始各样本保留日志。
- **原进程终态exit=0，100k已完成；recover==audit==replay，ratio=1.0414880812086298，本窄探针≤2。不是完整NFR/B1通过。**
- `audit/hybrid-v1/checkpoint-16-provenance-r1.log` 绑定生产HEAD、驱动/核心/运行schema与hybrid schema SHA、Python/SQLite/perf_counter信息、实际argv/PID/开始时间、worktree状态与终态记录。log/fixture DB SHA及摘要见 evidence/checkpoint-16-final-tests.txt；413MiB隔离fixture保留、不提交Git、不删除history。

原 exec session82782 / Python PID1145448，2026-10-08 22:43:51 Asia/Shanghai 开始；write_stdin 已返回 exit_code=0，原进程不存在，终态summary/完整性检查均通过。**不需重启r1，也不可覆盖其证据。**

## 终态实测

| 指标 | 10k core / 10001 public | 100k core / 100001 public |
|---|---:|---:|
| ordinary write p95（各199样本）ms | 8.337045 | 8.682933 |
| ordinary writer hold p95 ms | 8.293555 | 8.619053 |
| checkpoint 1000-boundary total ms | 7.018713 | 5.888500 |
| direct snapshot p95（30次）ms | 0.594425 | 0.642655 |
| direct usage page p95（30次）ms | 0.239452 | 0.179271 |
| direct last100 event page p95（30次）ms | 25.625400 | 25.547475 |
| optional maintenance total ms | 10.702666 | 11.078074 |
| pre-final-audit cumulative peak RSS KiB | 39556 | 40384 |

两个点均14 projection rows/1 usage object。全部100个千次边界总耗时max=11.077177ms，均记录不删除。写window之后maintenance成功、公共cursor与core version不变，最终due/complete=(0,100000)。额外只读事实核对 checkpoint-16-public-facts-r1.log：public=core+1精确数量，最后event source_state_version、usage object.version与fixture input_tokens均100000，data_mode=fixture（不是实际供应商token数）。

结论：本次warm单对象历史轴未见普通写p95超过2倍退化，不据此断言10k任务/reconcile、硬RSS、API合计内存、WAL或并发B1通过。生产模块未改，不虚称本checkpoint重跑全量586；生产基线冻结全回归见checkpoint15，本次驱动/相关模块40项回归与真实100k完整性作为新增证据。

独立High终态复核：28 passed/2.10s，原始p95/ratio/全部100边界重算、provenance SHA与公共tail事实一致，当前窄scope无剩余MUST_FIX；两处报告澄清与缺失的最终证据文件均已补齐。compileall/pip check/diff与最终manifest SHA检查通过。

## 后续必须保留

100k完成后另测投影cardinality/真实10k任务、3项目、4vCPU8GiB、活跃会话与10/s及50/s峰值、双浏览器、维护并发、WAL/idle/24h/8h；不得用本单轴替代完整B1。依据测量定位validator构造/map/active工作热路径，完整Goal仍M0–M5。
