# 需求包离线校验报告

Checkpoint25终态：schema1.1 显式工具/registry-profile hash/评价数据与冻结规则声明兼容旧1.0不可变版本；仍仅UNAPPROVED DRAFT。root/独立High三模块80passed，冻结全量689passed/32既有skips/1既有warning/238.29s，原83613已terminal exit0，不再live。范围MUST_FIX关闭，见HYBRID_GOAL_DRAFTS.md/evidence/checkpoint-25-final-tests.txt。无1.1 command/HTTP/MCP/skill桥、实际registry核验或审批/lease/执行；无新增browser/性能证据，完整T09/M1/B1/长期与M2–M5继续开发，Goal active，无新增外部阻塞，用户package-lock保留。

Checkpoint24真实Store草案首切片：DRAFT/UNAPPROVED、私有immutable contract/command receipt与CAS head，内容与项目绑定，同事务/回放/完整snapshot（含周期）守卫闭合。root36passed/独立161passed、四项MUST_FIX关闭，冻结完整663passed/32既有外部/H1skips/1warning/234.49s（原66508终态exit0）。见HYBRID_GOAL_DRAFTS.md与evidence/checkpoint-24-final-tests.txt；无新browser/性能负载，不虚称T09可信批准/执行或M1–M5/完整Goal完成。

Checkpoint23有限组合HTTP独立终态：100k历史+10k归档task、400实际Store写/双SSE各400完整事件/128查询（64snapshot+64page），核心100401/公共100451、task精确不变/session0/source unchanged/ownedAPI TERM-reaped。submit-call→完整帧p95 246.724ms、snapshot8.144/page10.167ms，完整raw独立重算精确匹配；root21passed/10.21s、High21passed/10.65s，三项MUST_FIX关闭。见HTTP_PERFORMANCE.md与evidence/checkpoint-23-http.jsonl/final-tests.txt。生产未改，不虚称full/browser重跑，不代表DOM延迟/B1/完整NFR/M1或M0–M5 Goal通过。

Checkpoint17归档任务规模：r2真实100/1k/10k任务+每档audit==replay，无工作阶段core/cursor不变且session0；10k scoped/legacy写p95=7.061/14.747ms、viewkeys2.677ms，无工作CPU p50=10.257ms/次非5min平均。High测量assert省略调用finding关闭，两driver拒绝-O及真实负例；root20passed、独立7passed、原始分布/来源SHA归档。见TASK_PERFORMANCE.md/evidence。生产未改，无全量/browser重跑；旧100k额外RO真实audit通过且DB字节不变。不代表活跃闭环/组合B1/M1 gate，继续完整Goal。

Checkpoint16 真实历史单轴：新增驱动及40项定向/独立High28项通过；实际100k core/public写终态exit0、recover==audit==replay，普通写p95 8.337045→8.682933ms、ratio1.041488≤2；100个千次边界max11.077177ms、公共版本/值精确核对通过。原始样本与SHA见HISTORY_PERFORMANCE.md/evidence/checkpoint-16-history.jsonl及checkpoint-16-final-tests.txt。生产模块未改，不虚称全量/browser重跑。M1_ACCEPTANCE_REPORT.md明确尚未通过：单对象warm/direct Reader探针不替代10k任务/3项目/限定硬件/并发B1、RSS/WAL/idle/24h/8h或M2–M5闭环。无新外部阻塞，Goal保持active。

Checkpoint15 周期快照维护：冻结全回归586passed/32既有外部依赖skipped/1既有warning/215.49s，定向108passed，独立High37passed/无新增MUST_FIX，Chrome+Node20passed/0skipped/9.44s。第1000次写只标记due、锁外构造/原子发布确认、marker索引、真实线程并发及三处实际进程死亡恢复通过。小型单样本8MiB锁占用43.238→15.825ms但总耗时更高，非B1/RSS/WAL或硬时限验收。见CHECKPOINT_15.md/SNAPSHOT_MAINTENANCE.md/evidence；legacy热路径、M1 gate、M2–M5/闭环/长期验收继续保留。

执行日期：2026-10-07。

结果：**16 项检查通过**。

1. JSON Schema meta-validation: command.schema.json
2. JSON Schema meta-validation: event.schema.json
3. JSON Schema meta-validation: goal.schema.json
4. JSON Schema meta-validation: payloads.schema.json
5. Goal proposal fixture valid and UNAPPROVED
6. Pause command fixture valid
7. Nested goal reference in submit_goal resolved offline
8. Negative fixture rejected: proposal self-approval
9. Negative fixture rejected: client-supplied trusted actor
10. Negative fixture rejected: pause without expected version
11. Negative fixture rejected: arbitrary shell parameter
12. Scoped emergency stop can omit expected_version
13. 6 event fixtures: envelope, typed payload, sequence, identity, budget arithmetic
14. Configuration template cannot directly enable a real runtime
15. OpenAPI starter YAML: 12 unique operations, required path parameters, local references
16. 36 acceptance cases, 26 implementation tasks, 16 source entries, no tool-citation leakage

## 检查边界

仅运行本包 schema/fixture、YAML、引用、编号和安全模板的离线检查。OpenAPI 未由真实服务器导出，也未执行完整 OpenAPI 语义一致性认证；泛型读模型及其余领域 payload 仍由 T03 固化。未启动 rlflow/Codex/GPU，未验证真实运行隔离、恢复、性能、费用或研究有效性。

## 2026-10-08 实施验收入口

上文保留为原需求包校验记录。当前系统实现的基线、测试命令、进程故障注入和独立审查见 [IMPLEMENTATION_VALIDATION.md](IMPLEMENTATION_VALIDATION.md)，任务状态见 [PROGRESS.md](PROGRESS.md)。当前尚未完成 M1–M5；需求包通过不代表完整系统验收通过。
# 系统 Checkpoint 02 补充

2026-10-08：认证只读 API/SSE 基础和 command guardian 控制隔离修复的最终回归 **368 passed / 32 skipped / 115.80s**。真实 loopback HTTP/SSE 重连与 High 只读复核已通过。详细失败过程、修复、冻结 SHA256、证据路径见 IMPLEMENTATION_VALIDATION.md 与 CHECKPOINT_02.md；这不是 M1 或完整 Goal 完成结论。

## 系统 Checkpoint 03–04 补充

启动释放事实切片冻结 **399 passed / 32 skipped / 135.90s**；初始只读 UI 冻结 **402 passed / 32 skipped / 139.90s**，sandbox Chrome Fixture browser+reducer **9 passed**。High UI 初始范围 MUST_FIX 关闭；详细输出/哈希/失败记录见 CHECKPOINT_03.md、CHECKPOINT_04.md 与 IMPLEMENTATION_VALIDATION.md。Fixture、CLI_RELEASE_ACK 和连接 LIVE 都不能证明供应商模型 RUNNING；日志/资源、完整 M1、M2–M5 与长期验收仍未完成。

Checkpoint05虚拟事件窗口：geometry/reducer/browser11通过，Web/CLI回归11通过；命令和源码hash见CHECKPOINT_05.md。该前端变化不是完整M1或后端100k性能验收。

Checkpoint06公共CORE_STATUS日志后端/API：冻结430passed/32skipped/143.61s，浏览器回归11passed，High本范围MUST_FIX关闭。见CHECKPOINT_06.md/evidence/checkpoint-06-final-tests.txt；状态日志不证明工具/模型实际运行，日志UI、工具metadata、资源、完整M1–M5仍待交付。

Checkpoint07公共日志UI：Chrome/Node13passed/0skipped/5.85s，相关Python39passed/1warning/5.21s，High本范围MUST_FIX关闭，语法/编译/diff通过。见CHECKPOINT_07.md/evidence/checkpoint-07-final-tests.txt。本轮没有后端全量重跑，工具metadata/资源及M1–M5、长期验收仍待完成。

Checkpoint08工具private provenance：最终全回归455passed/32skipped/1warning/145.80s，目标68passed/1skipped/46.63s，High范围无MUST_FIX。见CHECKPOINT_08.md/evidence/checkpoint-08-final-tests.txt。可信request指针与固定返回事实不授予authority，也不代表public工具metadata已接入；collector/资源/完整M1–M5仍待交付。

Checkpoint09发现源：冻结478passed/32skipped/1warning/146.63s，target56passed，High父目录fsync finding关闭。见CHECKPOINT_09.md与TOOL_DISCOVERY_PROTOCOL.md。REGISTER不证明工具启动、fd reader不等于core事务collector；公开工具metadata/资源及完整M1–M5仍待交付。

Checkpoint10 private core collector/ledger：target205passed/59.70s，冻结505passed/32skipped/1warning/172.21s，两项High MUST_FIX关闭。见CHECKPOINT_10.md/evidence。恢复/事务/公平扫描及完整绑定已证明，private VERIFIED仍非模型/vendor启动证明；公共工具projection/API/UI、资源、M1–M5及长期验收继续保留。

Checkpoint11 private历史task关联：target200passed/73.49s，High独立4passed，冻结507passed/32skipped/1warning/188.76s，compileall/pip check/diff通过。见CHECKPOINT_11.md/evidence。缺失旧关联保持未知，公共metadata/UI尚未启用，后续安全集成门槛见PUBLIC_TOOL_IMPLEMENTATION_NOTES.md；完整Goal保持活跃。

Checkpoint12公共绑定工具返回：最终冻结532passed/32skipped/1warning/200.39s，protocol/tools43passed，target166passed，High23passed/31deselected，Chrome+Node15passed/0skipped。闭合projection/独立模板/筛选/事务/覆盖/旧合同兼容证据见CHECKPOINT_12.md/evidence及LOCAL_WEB.md；三类High finding关闭，实际CPU后台与序列化browser Fixture不混同vendor证明。资源、完整M1–M5/B1/长期验收继续推进。

Checkpoint13资源与worker freshness后端：最终冻结556passed/32skipped/1warning/208.02s，target98passed，High24passed，Chrome+Node15passed/0skipped，防御性JSON异常注入通过。来源范围/非阻塞/独立序号/高水位/读时陈旧与generation隔离证据见CHECKPOINT_13.md、RESOURCE_TELEMETRY.md和evidence；后端范围无新增MUST_FIX。telemetry SSE/资源UI、M1 gate/B1/M2–M5及长期验收仍未完成，Goal活跃。

Checkpoint14 telemetry SSE/资源UI：最终冻结562passed/32skipped/1warning/209.07s，target63passed，High33Python/5JSpassed，Chrome+Node20passed/0skipped。原采样因果版本、旧槽UNKNOWN、实际ASGI排队增龄及optional异常后domain继续、独立UI样本版本/陈旧和真实HOST OS显示通过；两类High finding关闭。证据见CHECKPOINT_14.md/evidence，桌面/390px手机已检查。不是B1/M1 gate或完整Hybrid闭环验收，继续完整Goal。
