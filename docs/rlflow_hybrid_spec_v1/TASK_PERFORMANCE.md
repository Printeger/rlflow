# 归档任务规模探针（checkpoint17）

2026-10-08，生产基线9d7b897/与checkpoint15同一生产源码。新增 tests/acceptance_tasks_v1.py；仅测归档synthetic任务cardinality，不是活跃工作、组合100k历史、完整B1或M1 gate。

```bash
.venv/bin/python -m tests.acceptance_tasks_v1 \
  audit/hybrid-v1/checkpoint-17-tasks-r2 \
  --sizes 100 1000 10000 --samples 30 \
  > audit/hybrid-v1/checkpoint-17-tasks-r2.log 2>&1
```

每档新Store/fixture observer；同一个真实core bootstrap事务保存全部schema-valid任务，公共桥自然按200对象分批。记录全部DONE但completion全部false、无stage授权/queued/session/job/repair/release；这是结构测量fixture，不是已实际完成任务。随后各30次scoped/legacy改task0版本，真实生产Store/observer不替换。各档core均61；公共events分别62/66/111，差异是bootstrap真实分批，不把public history冒充固定相等。

以有限次数直接reconcile→dispatch_one测无工作迭代，没有启动daemon/开发Goal或模型。DONE-only使实际执行路径不可达，断言session=0且该阶段core version/cursor不变；optional OS telemetry的private slot可更新。最后每档audit==replay；所有任务和历史保留。调用顺序、首次导入/缓存会影响结果，不是随机化对照。snapshot/page为直接Reader，不含HTTP/auth/SSE/浏览器。

## 最终 r2 原始结果

| 任务数 | scoped write p95 ms | legacy write p95 ms | view keys p95 ms | no-work wall p95 ms | no-work CPU p50 ms |
|---:|---:|---:|---:|---:|---:|
| 100 | 5.118500 | 8.011567 | 0.220702 | 6.342692 | 2.399684 |
| 1000 | 8.711955 | 8.774685 | 0.394784 | 4.114630 | 3.201414 |
| 10000 | 7.061118 | 14.747284 | 2.677056 | 10.979106 | 10.256932 |

direct snapshot p95分别1.976179/1.943449/1.956029ms，task page p95 0.247162/0.318893/0.266313ms；各30样本，nearest rank。顺序profile进程累计peak RSS（含此前audit）42860/52736/115604KiB，不是每档独立RSS，不包含API或浏览器。宿主仍未施加B1 4vCPU/8GiB限制。

10k归档任务下全key发现和legacy写成本增大；无工作迭代CPU中位数10.257ms提示值得后续真实idle测量，但不能乘1Hz就称5分钟平均CPU失败/通过。快速循环中telemetry按秒限频，实际1Hz负载不同。下一项组合100k/10k、有限实际idle及活跃工作路径/完整B1，不用此probe代替。

## High 修正与证据

独立High发现probe MUST_FIX：实际reconcile/dispatch放在assert内，Python优化模式可移除真实调用。已改先实际调用再单独检查；两个history/tasks入口在mkdir前显式拒绝sys.flags.optimize非0，记录flag；真实-O子进程负例验证无输出目录产生。r1保留，r2重新跑三档，均optimize=0、exit0，不使用r1作最终判定。

根定向（两probe+projection）：20passed/2.34s；独立两probe7passed/6.13s，无剩余MUST_FIX。独立重算r2全部wall/CPU分布、30样本与public分批计数一致。生产模块未改，不虚称全量或browser重跑。compileall/pip check/diff及SHA检查见evidence/checkpoint-17-final-tests.txt，原始r2完整JSONL随文档保存。

checkpoint16原100k数据库额外以mode=ro直接执行实际Store.audit(db)/replay(db)（调用不在assert内），version100000/optimize0/两状态相等，state SHA edc23fb0b25922136c69e727117faa73f35ef0eb14507c65b9822f06f40181ad；未初始化或repair，原DB字节SHA完全不变。此加强校验不重复seed100k，原测量源码/原始证据仍对应其原commit版本。
