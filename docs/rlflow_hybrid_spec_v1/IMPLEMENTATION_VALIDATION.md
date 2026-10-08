# 系统实施验收记录

2026-10-08，基线 HEAD `d25cf02`，Python 3.12.3。本报告区别于原需求包的静态验证。

| 命令 | 结果 | 能证明的范围 |
|---|---|---|
| `.venv/bin/pytest -q` | 未进入测试；宿主 ROS plugin 缺 lark | 环境污染，不能作为代码失败 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q` | 307 passed, 32 skipped, 2 failed, 100.33 s | 旧实现基线；两个 doctor 失败由于版本 0.153.4 与本机 0.161.0 不匹配 |
| `.venv/bin/python -m rlflow.capabilities --pinned-version 'codex-cli 0.161.0'` | 本机 schema 生成成功，315 files | 无生成、无账号凭据的本机协议声明核查 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/test_hybrid_capabilities.py -q` | 4 passed | 缺失/失败/旧版本 pin 拒绝，无生成、不加载凭据、cgroup 声明不当作强制保证 |

协议 SHA256：`e18d9d29dd6ca3826af3a2b0fead0813160ceb099e80b9c1a4102313d0acb9e5`。

尚无 A01–A36 的完整验收结论。M0 未退出；其余里程碑未验收。未运行真实业务模型、GPU、生产迁移或远程开放。

## Checkpoint 01：协议、观测与 0.161.0 隔离兼容

实现：`rlflow/capabilities.py`、`hybrid_protocol.py`、包内 `hybrid_schemas/`、`observation.py`、`Store._commit` 事务 hook、`isolation.py` 固定 census catalog 与注册表指纹。未改变现有调度流程、批准、预算或业务范围。

| 命令 / 检查 | 实际结果 | 证据范围 |
|---|---|---|
| `pytest tests/test_hybrid_observation.py tests/test_hybrid_protocol.py tests/test_hybrid_capabilities.py -q`（使用隔离 pytest 环境变量） | 37 passed，随后补 3 项协议测试并单独通过 | 快照/事件接缝、幂等、公共读模型、脱敏、usage unknown、epoch、原始事件 bytes 不变、读连接禁写、索引分页、逐对象版本、序列断裂 |
| `pytest tests/test_hybrid_observation.py tests/test_hybrid_protocol.py tests/test_projection_v3.py tests/test_store_policy.py -q` | 65 passed | 新旧投影、事件事务、授权/预算不变量；该结果属于更早中间候选 |
| `pytest tests/test_isolation.py tests/test_cpu_approval.py tests/test_hybrid_capabilities.py -q` | 17 passed | 0.161.0 工具注册、真实内核读写/网络/嵌套调用隔离、批准范围 |
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs` | 346 passed / 32 skipped / 110.85s | 第一轮全量回归，输出 `audit/hybrid-v1/checkpoint-01-pytest.log`；原两项失败已解决 |
| 原 `validate_spec.py`，仅抑制报告写入 | 16 checks / 6 events / 12 operations / 36 A / 26 T 通过 | 离线需求结构校验，保持原报告不被脚本覆盖 |
| `.venv/bin/python -m compileall -q rlflow`、`git diff --check` | 通过 | Python 编译与补丁空白检查 |
| GPT-6.1 Sol High 独立只读复核 | 本 checkpoint MUST_FIX 全部关闭，9 项相关负例通过 | `ARCHITECTURE_REVIEW_M0.md`；不构成最终独立交付验收 |

最后三项新增协议测试证明：不可变合同 hash/identity/COMPLETED 必需信息、同会话不能构成独立 PASS 证据、非 Engineer lease 不可请求写入。协议 `compatible` 现要求同时匹配 version 和 schema SHA256，不能只匹配版本。

进程故障测试实际在隔离临时 state 中运行子进程，使用 `_exit` 在 commit 前/后退出，分别验证源事件/public projection/outbox 全部回滚或全部持久化。测试没有调用真实模型。32 项 skipped 分别为 18 项外部 reviewed dispatcher、14 项外部 H1；原跳过保留，未来通用实验 adapter 必须补自己的实际验收。

最终代码冻结后的完整回归：**349 passed, 32 skipped, 109.97s**。命令 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`；输出 `audit/hybrid-v1/checkpoint-01-final-pytest.log`，版本化副本 [evidence/checkpoint-01-final-pytest.txt](evidence/checkpoint-01-final-pytest.txt)。能力探测实际 JSON 见 [evidence/checkpoint-01-capabilities.json](evidence/checkpoint-01-capabilities.json)。执行期间不修改 Python 源码或测试。

冻结代码 SHA256：

```text
1731b5494df9593c8338a8938719962c55e7611be3ee37ee3635ff87a6111067  rlflow/capabilities.py
9c3f54b94309e7a8e4bb35d9925423e49734bb3105e7d5bf59c3b25c7a47331c  rlflow/hybrid_protocol.py
06de466ef07e6cddb818b37c2dd0f556e9313b59f13b37d28de9d7f7e8b814d4  rlflow/observation.py
323a37a2d2ce598bbcc3b8d5d6028bb6c1fc3b48bce6284c23a573e71c8f554e  rlflow/isolation.py
3864290b8c05b895426fd2cf1aa7a9a8ddea826392697ab5050bf2073e7d4c9e  rlflow/store.py
9ae36bf0bee041d47b7b5e6effeac6a4769a586231558fa1d9e51e89f5dced98  tests/test_hybrid_capabilities.py
ec46e1f68eb5181dde7eb140a28a956620c4dadfe172bc090ac2415d3b98015c  tests/test_hybrid_protocol.py
1d69f66a3fd6f9b16b3715baba83e1255697d94a5c9faf38b0d0c3187fd66025  tests/test_hybrid_observation.py
```

发布门槛缺口仍包括：完整生产 API/SSE/UI、工程/科研闭环、真实供应商接入、共享资源、B1、24h/8h soak、新安装与迁移、可信远程、回放、最终独立审查。不能宣布 Goal 完成。

## Checkpoint 02：认证只读 API/SSE 与 command guardian 修复

最终冻结候选 **368 passed / 32 skipped / 1 warning / 115.80s**。命令 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`；实际原始日志 `audit/hybrid-v1/checkpoint-02-final-r3-pytest.log`，版本化结果与源码 SHA256 见 [evidence/checkpoint-02-final-pytest.txt](evidence/checkpoint-02-final-pytest.txt)。r3 期间未编辑源码或测试。

| 验证 | 实际结果与边界 |
|---|---|
| 最终认证/API/SSE/loopback/isolation/CPU approval 子集 | 31 passed / 1 warning / 11.73s |
| 真实 loopback TCP HTTP | 提交后 domain 与真实公共 usage 字段到达；Last-Event-ID 重连无重复，heartbeat 不带 id；线程/server/socket 正常结束 |
| 纯 ASGI socket-facing send | 实际 send stall 超时、连接槽回收；100 条健康积压完整发送；真实慢 send resync+close；撤销阻止后续 buffered domain |
| 项目身份替换故障 | head 后更换 reader.db 时 snapshot 拒绝；head/snapshot/page/events 均在事务内绑定 project/data_mode |
| 登录/授权边界 | 匿名/跨项目/Host/Origin/CSRF/方法混用、body 过量、额外字段、surrogate、Bearer query token、Agent approver 全部拒绝 |
| command guardian 隔离与恢复 | 默认外部私有目录、真实角色写入控制标记被拒绝；旧 child 死亡断言保留并新增 supervisor/guardian quiescence；unknown/invalid identities 不允许删除 |
| 独立 High 安全/恢复复核 | 四项针对恢复测试通过；本范围 MUST_FIX 均关闭；详见 SECURITY_REVIEW_WEB_FOUNDATION.md |
| Python 编译 / 补丁 / 依赖 | compileall、git diff --check、pip check 全通过 |

保留失败证据：首轮 366/32 通过后，增加 heartbeat closed-schema 校验的冻结回归出现 **1 failed / 365 passed / 32 skipped / 116.57s**。原日志 `audit/hybrid-v1/checkpoint-02-final-pytest.log`；错误是原隔离死亡测试的 rmtree 与仍活跃 trusted recovery writer 竞争。不是跳过/忽略：独立诊断后修复角色可写控制目录与清理证明；中间 r2 368/32 通过，随后闭合 null/empty identity 防御并重新执行最终 r3。未降低业务终止期限或删除测试。

32 skipped 与 checkpoint 01 相同：外部 reviewed dispatcher 18、外部 H1 14。唯一 warning 为安装版 Starlette TestClient 的 anyio alias deprecation；没有项目测试报错。测试默认仍隔离宿主 ROS 插件。

该切片不是 M1 完成证明。T05 完整启动观测、T07/T08 前端、日志/遥测、完整 Error envelope、性能/soak、M2–M5 与最终 Goal 门槛仍未验收。新增仅 local read-only API；未调用真实模型、GPU、公开监听或生产状态。

## Checkpoint 03：绑定启动释放事实

最终冻结全回归 **399 passed / 32 skipped / 1 warning / 135.90s**；命令 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -rs`，原日志 `audit/hybrid-v1/checkpoint-03-final-pytest.log`，版本化输出和 SHA256 见 evidence/checkpoint-03-final-pytest.txt。目标子集与 High 独立复核均为 68 passed。runtime Python/pytest 源码在最终执行中未改变。

新增真实 model-free held-wrapper 子进程短命启动与退出，再以历史身份验证 ACK。只证明本地 CLI_RELEASE_ACK，不证明供应商模型执行。负例覆盖 request/release/phase/hash/identity/command/candidate/reservation/resource 绑定、换代与并发、FIFO/链接/读取上限、receipt 前补采集与 optional proof 破损。stage/task/approval/authority/usage 不因此观察事实改变；legacy source RUNNING 仍公开 STARTING/PARTIAL。

High 发现的两类问题已修：持久化前 candidate/limit/resources 必须再绑定；malformed optional proof 不能通过 None generation 或缺失/无效时间/hashes 伪造公共 ACK、不能阻止核心写入。时间字段命名 startup_released_at，避免伪称实际 execution.started。

独立 npm 检查环境（不动根用户 package-lock）已安装并锁定 playwright-core 1.55.1。实际 Chrome 151.0.7922.108 在 sandbox=true、disable-gpu、无账号 env 下 about:blank 启动并退出，证明后续浏览器 QA 工具可用；不属于 T07 UI 或 8h soak 验收。
