# Hybrid v1 开发进度

Checkpoint21终态覆盖下述过程记录：inner无候选hint（非授权）+正式重新读取/generation原位完成；root86passed/40.99s、High86passed/67.92s无MUST_FIX、冻结614passed/32既有skips/1warning/251.12s，46989/91710均exit0，compileall/pip/diff通过。见CHECKPOINT_21.md/evidence。下一新独占fixture实际300s测三项视图优化合计效果（不单项归因）；代码watch未改，NFR06无全仓库轮询/B1/M1仍未通过，Goal active。

Checkpoint21最新覆盖下述r2在跑记录：原9495已终态exit0，86passed/40.99s；compileall/diff通过。现在冻结全量原session46989/log audit/hybrid-v1/checkpoint-21-full-r1.log已确认live；High当前slice只读/独立复验待回，不能据root绿标完成。源码/测试冻结，恢复先查同handle（不因观察timeout重启），结果后建证据与commit，继续真正idle性能/监控安全与全M0–M5。没有新的CPU/B1/NFR06通过声明。

Checkpoint21进行中：checkpoint20已提交9fdfb05/full609/32/1终态。inner generation仍原首行；closed hint与indexed候选过滤仅无候选早返回，实际工作丢弃hint对象并按原fullview重新控制/STOP/ACTIVE/queue/blocked，后续正式门原样。r1目标82passed/39.97s；追加在hint→formal之间真实PAUSE/blocked/delete/隔离STOP四种变化，r2原session9495/log audit/hybrid-v1/checkpoint-21-target-r2.log运行，源冻结，High只读复核进行中。未提交/未复测CPU/未通过NFR06，下一核对同handle→独立复验/全回归，并处理事件guard局限而非放宽安全门。Goal active，完整M1–M5仍未交付。

Checkpoint20终态覆盖下述过程：closed control early gate与blob/并发snapshot/成功失败close拒绝验证完成；target89+r3新模块10passed，独立High94passed/69.91s无MUST_FIX、冻结全量609passed/32既有skips/1warning/251.96s，原63583/91575均exit0，compileall/pip/diff通过。见CHECKPOINT_20.md/evidence；inner full/generation门未改、CPU未复测。下一无候选inner视图优化与有安全边界的事件guard（不能忽略inotify mmap/mount/network限制）。Goal active，完整M1–M5仍未交付。

Checkpoint20最终冻结回归进展覆盖下述过程：r2 session67982已exit0、89passed/40.39s；补5个错型/缺blob负例与失败关闭并收紧异常，r3新模块10passed/0.83s、compileall/diff通过。当前全量pytest原session63583/log audit/hybrid-v1/checkpoint-20-full-r1.log已确认live，High独立最终目标在跑（checkpoint-20-high-r1.log），源/测试冻结。下一恢复先核对原handle与日志，不因观察超时重启；结果后更新证据/提交，再推进事件失效源码guard/inner优化与实际复测。现无CPU修好/B1/M1完成声明；Goal active。

Checkpoint20进行中：checkpoint19已提交277a13a，全量600/32/1终态。新增Store.control_view仅读closed version/paused/enabled/autonomous且同BEGIN/blob解码/严格类型，自有连接close；dispatch outer用早门不枚举archive，inner完整view/generation/授权/STOP/active/schedule_pending与release夹层原封不动。r1目标87passed/40.34s；补blob与并发snapshot/close测试后r2原session67982/log audit/hybrid-v1/checkpoint-20-target-r2.log运行，源冻结，恢复先查同handle；High只读复核进行中。未提交/未验收/未测CPU改善，下一独立复验/全回归及真正事件失效guard/inner优化，完整Goal active。用户package-lock.json保留不stage。

Checkpoint19终态覆盖下述过程记录：目标r2 107passed/1warning/36.03s、High独立78passed/1warning/48.43s无MUST_FIX、冻结全量600passed/32既有external skips/1warning/241.02s，全部原handle终态exit0，compileall/pip/diff通过。reconcile默认API不变/daemon省尾view、未来测量显式baseline已验证，见CHECKPOINT_19.md/evidence。未复测CPU、未改变checkpoint18失败，下一consistent indexed dispatch早门与事件失效watch，完整Goal active。

Checkpoint19进行中（未提交/未验收）：checkpoint18已提交0405b8d，保留CPU未达标证据。第一最小生产优化reconcile新增默认True的return_view，仅daemon传False省掉丢弃的尾view，所有实际reconcile/采样/安全门未变；driver新显式baseline修复未来精确复算。r1目标107passed/1既有warning/36.11s、High静态无MUST_FIX；按review建议追加真实telemetry发布/core+cursor不变断言，r2原工具session34190/log audit/hybrid-v1/checkpoint-19-target-r2.log运行中，源码/测试冻结，恢复先检查此handle而非重跑。剩余全回归、独立测试/复核、更多indexed空闲dispatch及事件失效watch待做；未复测CPU、无性能通过声明。用户package-lock.json仍不改不stage；Goal保持active。

Checkpoint19最新覆盖上述在跑状态：r2 session34190已终态exit0，107passed/1warning/36.03s；compileall/diff通过。当前全量pytest原工具session77356运行中，日志audit/hybrid-v1/checkpoint-19-full-r1.log；High独立目标复验进行中，日志checkpoint-19-high-r1.log。源码/测试持续冻结，恢复先检查两个真实运行结果，勿重起长测/全量。下一完整性验收/文档/提交后继续安全空闲热路径优化，原CPU基线与checkpoint18 SHA不可改写。

Checkpoint18 组合idle终态exit0：100k真实历史只读backup+10k DONE/all-false归档任务，真实daemon测300.000899s，CPU单核1.773328% **未达<1%**，采样RSS39862272bytes；core100001/public100051、sessions0、业务/来源不变、子进程已回收。telemetry最终seq297只证明采样进展。短回归13passed/2.54s，High启动安全无剩余MUST_FIX；终态独立复核进行中。session90403已终态不重启；见IDLE_PERFORMANCE.md/evidence/checkpoint-18-idle.jsonl。原始结果保留，不调阈值；逐秒全控制仓库watch也不满足NFR06无全仓库轮询条款。下一项优化空闲view/key枚举及事件失效式代码guard，保留STOP/授权/代码generation门，再以新版本复测。完整B1、M1 gate及M2–M5未完成，Goal保持active。

Checkpoint17：归档任务100/1k/10k真实Store/公共桥探针r2终态exit0、每档audit==replay/core61/session0；10k scoped/legacy write p95=7.061/14.747ms、viewkeys2.677ms、无工作CPU p50=10.257ms/次，不能等同5min idle或活跃闭环。High发现assert可删除调用的测量保真缺陷已修：实际调用移出assert、两driver拒绝-O、实际负例验证；root20passed、独立7passed。见TASK_PERFORMANCE.md/evidence。生产未改；下一项组合100k/10k、有限idle/活跃工作与完整B1，M1 gate及M2–M5仍未完成，Goal active。

2026-10-08。完整目标保持 M0–M5 / T00–T25，不以首个切片作为完成。

当前分支 `hybrid-v1`，基线 `d25cf02`。开发由 Codex Goal 负责，未启动 rlflow 来调度本次开发，未调用业务模型或训练。

需求包原位保留；`docs/hybrid-v1` 是指向本目录的 Git 跟踪相对符号链接，保证路径可用且不复制两份需求。原 `VALIDATION_REPORT.md` 是需求包静态校验报告，系统验收记录见本文件关联的 `IMPLEMENTATION_VALIDATION.md`。

| 任务 | 当前状态 | 证据 / 下一动作 |
|---|---|---|
| T00 | 基线已记录 | Python 3.12.3；原 307 passed / 32 skipped / 2 failed；两项版本不兼容已修复 |
| T01 | 本切片回归已通过 | Store / accounting / process recovery / startup 原测试保留，doctor 全部通过；后续 fencing/STOP 仍须新验收 |
| T02 | 无生成探测与隔离兼容完成 | 315 schema；version+protocol SHA pin；initialize-only 独立握手成功；真实 usage/interrupt/子代理未证实，禁用不支持能力 |
| T03 | 初始闭合合同已实现，后续扩展中 | GoalContract/Task/Lease/Attempt/Approval/Evidence/Experiment/Usage/Budget/CommandReceipt、公共快照与已注册 payload；完整 API 实际接口尚待 T06/T16 |
| T04 | 初始事务观测桥已验证，性能验收未完成 | 只读 bounded snapshot/page、增量 counters、同事务 outbox、epoch、真实进程故障测试；B1 100k 与备份恢复集成待验证 |
| T05 | 启动释放、CORE_STATUS、绑定工具公共返回与资源纵向切片已验证，完整观测未完成 | private ledger→closed projection/TOOL_METADATA；真实OS/loop HB/独立telemetry SSE/API/UI、age与因果barrier；不授予authority或证明vendor/STARTED；完整来源闭环与M1 gate待验证 |
| T06 | 只读基础切片实现，未完整验收 | 同源登录/project scope/短期 Bearer、snapshot/page、bounded durable SSE、loopback CLI；无写命令/任意 artifact；见 LOCAL_WEB.md |
| T07–T08 | 只读 UI、虚拟事件/公共日志/工具返回与资源面板已实现，未完整验收 | 真实 snapshot/SSE reducer、预算/分页/详情、虚拟窗口/锚点/键盘、日志、离线/身份隔离、closed工具metadata、真实HOST与worker来源/陈旧/版本屏障；Chrome QA通过；B1/真实完整闭环与M1 gate待完成 |
| T09–T17 | 未开始 | 合同、策略、受控 Runtime、单写、独立评审、预算、skill、控制与恢复 |
| T18–T20 | 未开始 | 本地与 fixture 实验 adapter、科研状态、证据页面 |
| T21–T22 | 未开始 | 资源隔离、故障/性能/24h 与 8h soak |
| T23–T25 | 未开始 | 安装/迁移、可信远程、历史回放 |

后续恢复应先读取本文件、Git、验收记录与实际测试输出。没有记录为已完成的条目不得推定完成。

最新进展：新增协议/观测回归、旧版本兼容修复及 High 独立审查的 MUST_FIX 已关闭。冻结最终代码后的全回归 **349 passed / 32 外部依赖 skipped / 109.97s**。报告与命令见 IMPLEMENTATION_VALIDATION.md，原始精简输出已纳入 `evidence/checkpoint-01-final-pytest.txt`。

本轮新增：认证与只读 API/SSE 基础候选已落盘；首轮全回归 366 passed / 32 skipped，追加 heartbeat 闭合合同检查后冻结回归发现既有 guardian teardown race（365 passed / 32 skipped / 1 failed）。未忽略失败：High 诊断同时揭示默认 command guard 落入角色可写 scratch 的控制隔离缺陷，现改 trusted 父进程外部私有目录、额外 scope 禁止覆盖控制目录、基于完整真实身份确认写入者 quiescence 后清理，并强化死亡测试。最终冻结 r3 **368 passed / 32 skipped / 115.80s**，编译/补丁/依赖检查通过；High 相关 MUST_FIX 全部关闭。证据见 CHECKPOINT_02.md 与 IMPLEMENTATION_VALIDATION.md。

High 独立 Web 复核的项目读源 TOCTOU、健康 backlog 误判/过量预取均已关闭；见 SECURITY_REVIEW_WEB_FOUNDATION.md。真实 loopback HTTP 事件提交与重连测试已通过。源码没有 scheduler/model/GPU 启动副作用。

最新 checkpoint 03：68 项 startup/protocol/observation 回归及独立 High 审查通过；冻结全回归 **399 passed / 32 skipped / 135.90s**。新启动观测不改 source status/phase/预算/批准，明确 CLI_RELEASE_ACK 不是模型 RUNNING。证据见 CHECKPOINT_03.md。

下一项：补T05工具metadata/资源、首次历史/error、动效/连接恢复与真实来源端到端，执行M1验收。虚拟窗口/公共日志不代表真实模型运行或8h soak。M1–M5与完整Goal仍未完成。

最新 checkpoint 04：冻结全回归 **402 passed / 32 skipped / 139.90s**，browser+reducer **9 passed / 0 skipped**，High 初始 UI 三项 MUST_FIX 全部关闭。实际登录/snapshot/SSE/详情/离线恢复/手机/身份隔离证明见 CHECKPOINT_04.md，未覆盖完整 M1。

Checkpoint05：geometry/reducer/browser **11 passed**，Web/CLI Python回归 **11 passed**。本轮未修改Python，不虚称全量重跑；见CHECKPOINT_05.md。下一项公共日志安全方案High复核中。

Checkpoint06：CORE_STATUS后端/API，目标80passed，独立High日志27passed，三项MUST_FIX关闭；r3最终冻结 **430 passed/32 skipped/143.61s**，浏览器回归11passed。详见CHECKPOINT_06.md与evidence/checkpoint-06-final-tests.txt。下一项日志UI，未声称完整T05/M1验收。

Checkpoint07：公共日志UI筛选/固定high-water分页/按需正文/虚拟窗口/覆盖说明已接入；最终Chrome/reducer/geometry/log-validator **13 passed/0 skipped/5.85s**，相关Python **39 passed/1 warning/5.21s**。High发现的详情残留与ref类型隐式转换已修复并独立复验，刷新失败保留同项目页及迟到响应隔离通过。见CHECKPOINT_07.md；后端未改，未虚称重跑430全量。下一项工具metadata/资源，完整Goal保持活跃。

Checkpoint08：worker新MCP config含closed request/generation指针，bound intent补scratch/memory与private fixed return fact，回放/崩溃不重复执行。目标68passed/1skipped，独立High31passed/1deselected范围无MUST_FIX；最终全回归 **455 passed/32 skipped/1 warning/145.80s**。见CHECKPOINT_08.md与evidence/checkpoint-08-final-tests.txt。公开工具collector尚未实现，UI保持未接入；下一项bounded发现/可信release核验/事务公共事实，然后资源。完整Goal仍活跃。

Checkpoint09：执行前durable REGISTER与closed bounded fd reader已实现，杜绝只依赖返回通知的漏发现窗口；登记时缺launch witness不事后升级。High父目录fsync MUST_FIX关闭，target56passed，独立54passed/1deselected；冻结全回归 **478 passed/32 skipped/1 warning/146.63s**。见CHECKPOINT_09.md/TOOL_DISCOVERY_PROTOCOL.md及evidence。下一项core indexed pending/事务cursor与receipt语义digest、完整release/permission核验及公共工具事实接入，然后资源；M1–M5/完整Goal仍未完成。

Checkpoint10：core private collector/ledger、同事务source cursor+receipt语义digest、indexed公平pending/global scan、完整request/release/startup/permissions/result绑定已接入engine。热view排除ledger、CLI audit/full replay完整保留；非法return隔离与Unicode byte-cap两项High finding关闭。最终target205passed，冻结全回归 **505passed/32skipped/1warning/172.21s**。见CHECKPOINT_10.md/evidence。下一项闭合公共tool projection/log模板/API/UI，再补资源与M1 gate；private VERIFIED不冒充供应商或启动事实，完整Goal仍活跃。

Checkpoint11：VERIFIED返回固定request.task_id，旧COLLECTED缺字段不追认，后续session换task不重写历史。target200passed，High独立4passed，冻结全回归 **507passed/32skipped/1warning/188.76s**；见CHECKPOINT_11.md/evidence。下一公共集成的闭合转换、live-only coverage、旧日志兼容/独立模板与refs筛选门槛记录PUBLIC_TOOL_IMPLEMENTATION_NOTES.md。公共tool/API/UI尚未启用，下一切片继续实施，完整Goal活跃。

Checkpoint12：closed工具公共projection/API/UI+独立TOOL_METADATA已接入，v2 task digest与显式live-only覆盖；旧CORE_STATUS原解释、任务/执行refs筛选、同事务rollback与旧ledger缺关联UNKNOWN。High三类finding关闭，独立23passed/31deselected；target166passed，最终protocol/tools43passed；Chrome+Node15passed/0skipped；冻结全回归 **532passed/32skipped/1warning/200.39s**。见CHECKPOINT_12.md/evidence和LOCAL_WEB.md。下一项真实资源telemetry/worker freshness与M1 gate（含性能证据），然后M2–M5；CPU backend与序列化browser Fixture各自证据不混为vendor/完整闭环，完整Goal活跃。

Checkpoint13：真实OS资源/loop heartbeat/独立latest slot及认证只读API已接入，非阻塞bounded fair sampling、持久counter witness与读时age/generation核验；定向98passed，High24passed/当前范围无MUST_FIX，Chrome+Node15passed；最终冻结 **556passed/32skipped/1warning/208.02s**。见CHECKPOINT_13.md/evidence。下一项telemetry独立SSE/资源UI与M1 gate，不把后端来源冒充完整实时资源Dashboard；M1–M5完整Goal保持active。

Checkpoint14：独立latest-only telemetry SSE/资源UI已接入，原采样source版本+snapshot/domain因果barrier、query/queue增龄、optional错误只drop、重复/迟到/退休epoch不续鲜，HOST/supervisor/GPU未知分域。target63passed，High33Python/5JSpassed，Chrome+Node20passed/0skipped；最终冻结 **562passed/32skipped/1warning/209.07s**，见CHECKPOINT_14.md/evidence。下一项M1 gate/B1历史规模与snapshot维护性能，然后M2–M5；资源UI不证明完整Hybrid/真实vendor/工程科研闭环，Goal保持active。

Checkpoint15：第1000次写只同事务标记due、单个可选线程锁外构造/非阻塞原子publish+ack、marker部分索引已实现；metadata损坏fail closed/实际正文与UTF8/解析前结构预算、真实线程并发与三处进程死亡恢复已验证。target108passed，High37passed/无新增MUST_FIX；冻结全回归 **586passed/32skipped/1warning/215.49s**，Chrome+Node20passed/0skipped/9.44s。小型单样本8MiB探针：手动快照writer hold43.238ms，新maintain15.825ms，但总耗时更高，非B1或硬RSS/时限达标。见CHECKPOINT_15.md/SNAPSHOT_MAINTENANCE.md/evidence。下一项历史/投影分轴性能测量、validator/map/active work热路径，然后完成M1 gate并继续M2–M5；Goal保持active。

Checkpoint16历史单轴已终态exit0：真实Store→public100k写、core100000/public100001、两个点projection14/usage1，ordinary p95 8.337045→8.682933ms、ratio1.041488≤2，100个千次边界max11.077177ms，最终recover==audit==replay、due(0,100000)、公共事实版本/值精确核对通过。驱动及相关回归40passed；生产源码未改，不虚称新增全量重跑。见HISTORY_PERFORMANCE.md及evidence；原session82782/PID已终态不重启。已补M1_ACCEPTANCE_REPORT.md明确gate尚未通过；下一项真实10k任务/活跃工作、B1并发/RSS/WAL/idle与长期证据，再按依赖继续M2–M5。Goal保持active。
