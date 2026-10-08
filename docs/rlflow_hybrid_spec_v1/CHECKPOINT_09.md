# Checkpoint09：执行前持久化工具发现源

2026-10-08，继承16686f6。T05有界发现源及恢复reader实际代码；公开collector/工具UI仍未实现，不是完整M1/Goal。

独立架构审查识别result/fact后再通知的漏发现窗口，采用intent→durable REGISTER→CPU→result/fact。REGISTER为pending已知key，不声称STARTED；不需要RETURN通知来保证后续发现，未来core按indexed pending公平检查。实现closed bounded hash-chain journal、固定source文件、fd anchored分页及offset/checkpoint witness；不glob全目录。登记当时捕获既存launch摘要，null不事后升级。完整写读/容量/恢复拒绝/未完成合同见TOOL_DISCOVERY_PROTOCOL.md。

## 验证过程

初始旧command/fact regression33passed/3.73s。新增target首轮 **52passed/1failed/4.05s**：oversize fixture在预期异常断言之前调用reader，reader正确拒绝；移动读取顺序到写入破损数据之前，保留相同拒绝断言，r2 **53passed/4.14s**。过程日志checkpoint-09-targeted.log保留，不算通过。

High首次独立51passed/1deselected，发现一个真实MUST_FIX：创建commands/<digest>后，仅fsync其自身与audit parent不能保证中间commands目录中的新dentry断电后保留。已在REGISTER/CPU之前fsync commands与audit parent；增加fd目录同步顺序、父目录fsync失败不登记/执行的负例，并增加32并发REGISTER单链测试。最终target **56passed/4.31s**，日志checkpoint-09-targeted-r3.log。High修复后独立 **54passed/1deselected/4.16s**，finding关闭、本源范围无新增MUST_FIX。独立子集未重跑actual supervisor SIGKILL case，根target保留并运行该用例。

目标命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_tool_journal.py tests/test_tool_return_facts.py tests/test_command_checkpoints.py tests/test_cpu_approval.py
.venv/bin/python -m compileall -q rlflow tests/test_tool_journal.py
.venv/bin/python -m pip check
git diff --check
```

包括REGISTER前异常无副作用、REGISTER后intent-only未知、result已提交/fact缺失仍发现已知目录、回放不重复登记、70记录固定32条页/append继续、partial尾不推进且不自动修复、source替换/截断/checkpoint/ordinal/prev/closed字段/超长记录拒绝、FIFO/链接不阻塞、context及launch witness错代/事后release不升级、并发hash chain与实际CPU旧能力回归。compileall/pip check/diff通过；后续冻结全量证据在evidence/checkpoint-09-final-tests.txt。

独立finding关闭后冻结全量：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`，**478 passed/32 skipped/1 warning/146.63s**。原日志audit/hybrid-v1/checkpoint-09-full-pytest.log；跳过仍为外部dispatcher18/H1 14，warning仍为Starlette已安装anyio alias deprecated。没有新跳过、没有模型/GPU。静态UI未改，未声称本轮再次执行浏览器QA，保留checkpoint07实际13项浏览器证据。

## 范围边界

库函数reader已经可运行；尚无core pending表/事务offset、receipt语义digest、公平轮询、公开schema/日志API/UI，Web仍TOOL_METADATA未接入。没有自动修复partial尾、没有历史缓存隐式backfill、没有严格工具STOP授权marker。未知/损坏源不能显示为无工具历史。后续继续core collector、资源与M1 gate及M2–M5；未调用模型/GPU/训练/生产/公开hosting/push。
