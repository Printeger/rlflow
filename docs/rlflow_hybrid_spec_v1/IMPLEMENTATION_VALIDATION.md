# 系统实施验收记录

Checkpoint17归档任务规模：r2真实100/1k/10k任务+每档audit==replay，无工作阶段core/cursor不变且session0；10k scoped/legacy写p95=7.061/14.747ms、viewkeys2.677ms，无工作CPU p50=10.257ms/次非5min平均。High测量assert省略调用finding关闭，两driver拒绝-O及真实负例；root20passed、独立7passed、原始分布/来源SHA归档。见TASK_PERFORMANCE.md/evidence。生产未改，无全量/browser重跑；旧100k额外RO真实audit通过且DB字节不变。不代表活跃闭环/组合B1/M1 gate，继续完整Goal。

Checkpoint16 真实历史单轴：新增驱动及40项定向/独立High28项通过；实际100k core/public写终态exit0、recover==audit==replay，普通写p95 8.337045→8.682933ms、ratio1.041488≤2；100个千次边界max11.077177ms、公共版本/值精确核对通过。原始样本与SHA见HISTORY_PERFORMANCE.md/evidence/checkpoint-16-history.jsonl及checkpoint-16-final-tests.txt。生产模块未改，不虚称全量/browser重跑。M1_ACCEPTANCE_REPORT.md明确尚未通过：单对象warm/direct Reader探针不替代10k任务/3项目/限定硬件/并发B1、RSS/WAL/idle/24h/8h或M2–M5闭环。无新外部阻塞，Goal保持active。

Checkpoint15 周期快照维护：冻结全回归586passed/32既有外部依赖skipped/1既有warning/215.49s，定向108passed，独立High37passed/无新增MUST_FIX，Chrome+Node20passed/0skipped/9.44s。第1000次写只标记due、锁外构造/原子发布确认、marker索引、真实线程并发及三处实际进程死亡恢复通过。小型单样本8MiB锁占用43.238→15.825ms但总耗时更高，非B1/RSS/WAL或硬时限验收。见CHECKPOINT_15.md/SNAPSHOT_MAINTENANCE.md/evidence；legacy热路径、M1 gate、M2–M5/闭环/长期验收继续保留。

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

## Checkpoint 04：初始只读 UI

最终冻结 **402 passed / 32 skipped / 1 warning / 139.90s**，实际 browser+reducer r2 **9 passed / 0 skipped / 3.99s**；编译/diff check 通过。命令、哈希与输出见 evidence/checkpoint-04-final-tests.txt，失败过程和独立审查见 CHECKPOINT_04.md。High 复验独立 Python34/reducer8通过，首次 render/原生POST/跨主体cache+DOM/迟到认证三项阻塞关闭。

真实本地 Fixture HTTP→SQLite committed outbox→SSE→DOM 的任务总数、bounded windows、offline/catchup、详情、XSS、keyboard/mobile、identity switch 和 native no-JS POST 已证明；Fixture明示，不等于运行器模型执行。未知费用/资源仍 UNKNOWN，未实现日志/资源/virtualization/完整error与筛选/真实来源E2E/8hsoak。完整 M1 和 M2–M5 仍未完成。

## Checkpoint05：虚拟事件列表

geometry/reducer/真实Chrome Fixture浏览器 **11 passed/0 skipped/3.92s**，Web/CLI Python回归 **11 passed/1 warning/7.95s**。本轮只改前端，未重跑全量后端；测试命令/日志/哈希与实际阅读锚点、keyboard、viewport可见性见CHECKPOINT_05.md。虚拟DOM替代200条全挂载，不改变事件事实和权威总数。完整日志/资源、真实来源验收与M1–M5仍未完成。

## Checkpoint06：公共日志后端

CORE_STATUS同事务append-only投影、closed schema、scoped summary/lazy-body API已实现。最终目标子集80 passed/1 warning/5.31s，独立High27日志测试通过且三项integrity/partial-schema finding关闭；Chrome/reducer/geometry回归11passed/0skipped/4.50s，日志checkpoint-06-browser-regression.log。本次Chrome只验证现有UI/SSE不回归，尚无日志UI验证。

初始实验test错误使用未支持的experiments集合，被RuntimeState拒绝；已改实际usage relation fixture，不放宽产品schema。两次全回归在审查修复期间主动SIGINT停止、保留原日志，不列为成功。独立复验后r3最终冻结运行，后端日志的实际边界/失败/恢复与证据见CHECKPOINT_06.md。资源与工具动作metadata、真实供应商、完整M1–M5仍待交付。

r3冻结最终 **430 passed/32 skipped/1 warning/143.61s**，编译/diff check通过；命令/源码hash/实际结果见evidence/checkpoint-06-final-tests.txt。本轮仍无日志UI与真实工具日志验收证明，下一项继续实现。

## Checkpoint07：公共日志 UI

最终Chrome/reducer/geometry/log-validator **13 passed/0 skipped/5.85s**，相关Python logs/API/local **39 passed/1 warning/5.21s**；模块语法/fixture编译/diff通过。列表不预读正文、索引过滤/固定high-water下一页、独立业务cursor、虚拟DOM、503同项目保留/恢复、乱序body与身份重置后迟到list/body隔离已验证。High本范围无剩余MUST_FIX，具体修复/过程失败/hash/命令见CHECKPOINT_07.md及evidence/checkpoint-07-final-tests.txt。未改后端且未重跑全量430/32；工具metadata/资源/完整M1–M5继续保留。

## Checkpoint08：private工具返回provenance基础

新worker上下文/CPU bound intent/闭合return fact与crash/replay/换代/隐私负例通过。目标 **68passed/1skipped/46.63s**，High独立31passed/1deselected；最终冻结全回归 **455passed/32skipped/1warning/145.80s**，compileall/pip check/diff通过。命令/hash见CHECKPOINT_08.md/evidence/checkpoint-08-final-tests.txt。private记录不证明放行/STARTED/RUNNING或完整STOP，尚无public collector/API/UI工具条目，UI仍未接入。没有模型/GPU/公开部署；M1–M5继续保留。

## Checkpoint09：执行前工具发现源

REGISTER先于CPU副作用、固定有界hash-chain journal、登记当时launch witness及fd分页/checkpoint拒绝已实现。目标56passed/4.31s，High父目录durability finding修复后独立54passed/1deselected；冻结全回归 **478passed/32skipped/1warning/146.63s**。compileall/pip check/diff通过。首轮52passed/1failed为oversize测试断言顺序错误，正确拒绝保留，未减少测试。见CHECKPOINT_09.md/TOOL_DISCOVERY_PROTOCOL.md/evidence/checkpoint-09-final-tests.txt；core pending/事务cursor、公开collector/工具UI与资源仍未实现，M1–M5继续推进。

## Checkpoint10：core private工具collector/恢复ledger

27新增cases与engine/store/obs/log目标205passed/59.70s，最终冻结 **505passed/32skipped/1warning/172.21s**。High非法return异常、producer/reader Unicode bytes不匹配finding均关闭，当前source与事务范围无MUST_FIX；compileall/pip check/diff通过。绑定真实model-free CPU返回、原预算/authority不变、outbox同回滚、并发一次性、restart/recover/audit、null不追认、终态历史、公平pending/global cursor与Unicode/容量已验证。具体命令/hash/过程失败见CHECKPOINT_10.md/evidence/checkpoint-10-final-tests.txt。未加入公共tool allowlist/body/UI、尚无资源、严格工具STOP、M1–M5或长期验收；周期snapshot全量maintenance例外保留。

## Checkpoint11：历史任务关联前置

private VERIFIED工具返回保存已核验request.task_id，旧缺失不补、后续session不重分配。target200passed/73.49s，High独立4passed；冻结 **507passed/32skipped/1warning/188.76s**，compileall/pip check/diff通过。首次target audit断言API错误已修复且原失败保留，见CHECKPOINT_11.md/evidence/checkpoint-11-final-tests.txt。公共集成方案见PUBLIC_TOOL_IMPLEMENTATION_NOTES.md，尚未启用工具projection/log/API/UI，static未改无browser重跑声明，完整Goal继续。

## Checkpoint12：绑定工具返回公共纵向切片

实际model-free CPU→private collector→closed public projection/query、独立TOOL_METADATA与task/execution筛选、v2绑定冻结task、live-only覆盖/旧v1 UNKNOWN、epoch/损坏覆盖拒绝、工具日志故障整体回滚已验证。目标166passed/1warning/93.28s；最终冻结protocol/tools43passed/25.72s，全回归 **532passed/32skipped/1warning/200.39s**。High23passed/31deselected/23.93s，三类MUST_FIX关闭。Chrome+Node **15passed/0skipped/6.46s**，截图已查看；工具browsercase序列化Fixture证明DB/API/SSE/UI而非CPU/vendor，与真实CPU后台证据分开。compileall/pip check/diff通过；入口不存在、旧单event断言、top-level闭合声明失败及主动停止的首轮full均保留，见CHECKPOINT_12.md/evidence/checkpoint-12-final-tests.txt。资源telemetry/freshness、完整M1–M5和长期gate仍未完成。

## Checkpoint13：真实资源与 worker freshness 后端

HOST/STATE_FILESYSTEM/SUPERVISOR_PROCESS明确分域、loop限频best-effort心跳、非阻塞bounded公平采样、independent latest slot/持久indexed witness、CAS与读时age/当前generation绑定核验、项目scope只读API已验证。定向98passed/28.74s；High24passed/3.25s与防御性异常注入通过，当前后端范围MUST_FIX关闭；冻结全回归 **556passed/32skipped/1warning/208.02s**，Chrome+Node15passed/0skipped/6.50s。原32外部依赖skip与1个Starlette warning不增加。过程失败、deep JSON证据边界、命令/hash见CHECKPOINT_13.md/evidence。无telemetry SSE/资源UI或历史曲线；不是完整M1/M0–M5验收，下一项继续实时消费及B1。

## Checkpoint14：独立 telemetry SSE 与资源 UI

latest-only可丢弃帧/无durable id/optional独立task/关键FIFO优先，query/queue实际选送增龄、原sample source版本+客户端snapshot/domain O(1) barrier、旧槽null/workerUNKNOWN只读、重复/迟到不续鲜、项目/身份隔离及真实资源DOM已验证。target63passed/5.78s，High33Python/5JSpassed，两类MUST_FIX关闭；sandbox Chrome+Node20passed/0skipped/9.19s（真实HOST OS、业务明确Fixture），desktop/mobile已查看。冻结全回归 **562passed/32skipped/1warning/209.07s**，静态/依赖/diff通过。作用域误放assert的r4/high r1失败保留并修正，不放宽age精确断言。见CHECKPOINT_14.md/evidence/RESOURCE_TELEMETRY.md。仍需M1 gate/B1历史与snapshot维护性能、M2–M5/闭环/长期验收，未发布或调用paid模型/GPU。
