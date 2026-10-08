# Checkpoint08：可信工具返回事实基础

2026-10-08，继承43fa074，T05工具metadata基础增量；不是公开工具日志或M1/Goal完成。

worker.prepare对recovery_protocol>=2请求，将session/generation/request_sha256/candidate_sha256的闭合tool_context写入可信MCP config。PREPARE身份指针不含released/STARTED、不能授予执行权限。新bound command intent包含context、scratch和实际memory limit，与原role/candidate/permissions/command/timeout一起hash；跨context或权限变化复用command ID拒绝。

CPU工具正常返回后持久化私有return-observation.json，闭合字段为schema_version/kind/tool/context/intent_sha256/result_sha256/state/exit_code/timed_out/wall_seconds/infrastructure_error。状态只允许RETURNED/TIMED_OUT/SETUP_FAILED，非零exit仍是RETURNED而不是成功。不存在绝对开始/结束时间、命令/command ID、stdout/stderr、路径、自由错误或模型文本。不能据此推断模型运行、工具启动、进程树已停止或release权限。

先提交result再记录return fact；崩溃缺fact可在锁内以同一已提交result恢复固定记录、不重执行。已有fact与result/intent摘要不符拒绝。只有intent而无result继续保持outcome unknown，不重试副作用；legacy无context保留行为且不生成伪bound证据。context/result类型、finite elapsed、固定infrastructure reason均检查。

## 测试与审查

目标回归：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_tool_return_facts.py tests/test_command_checkpoints.py tests/test_cpu_approval.py tests/test_process_recovery.py tests/test_startup_observation.py tests/test_startup_v3.py
```

**68 passed/1 skipped/46.63s**，原日志audit/hybrid-v1/checkpoint-08-targeted-final.log。先前初始command8passed/1.71s，新增target33passed/3.71s。没有出现测试失败。新增25个负例/集成参数包含实际隔离CPU写一次、caller replay、context/permissions换代、unknown intent、result/fact崩溃窗口与tamper、旧config、非法context/非finite result及有限结果标签；config测试无模型验证context传递。

独立High只读验证31passed/1deselected/3.56s（已运行过的supervisor SIGKILL case未在独立子集重复，不代替完整回归），本基础范围无MUST_FIX。明确公开collector仍需与可信request、DB已提交release、session/generation、权限和startup proof独立核验，不能只信context/hash。根为唯一写入者。

随后冻结全回归 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`：**455 passed/32 skipped/1 warning/145.80s**，日志audit/hybrid-v1/checkpoint-08-full-pytest.log。跳过仍为原外部dispatcher18/H1 14；warning仍为已安装Starlette anyio别名deprecated，不新增跳过。compileall、pip check、git diff --check通过；源码/输出SHA256见evidence/checkpoint-08-final-tests.txt。未修改static/Web行为，未虚称本轮再次浏览器QA，沿用checkpoint07已冻结13项实际浏览器证据。

## 未完成边界

本轮未实现公开collector、公共schema/API/UI工具条目、disk raw-root安全解析、逐工具STOP/新授权marker、资源telemetry；Web仍显示TOOL_METADATA未接入。未触发模型/GPU/训练/公开服务/生产数据/push，不改批准/预算或现有调度权。下一项继续collector与持久化公共事实，再补资源与M1 gate；M2–M5及长期验收保持原scope。
