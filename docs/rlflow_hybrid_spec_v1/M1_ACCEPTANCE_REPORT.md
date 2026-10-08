# M1 退出门槛审计（尚未通过）

Checkpoint31 完整终态：root 原87433与独立High原56356均 terminal exit0，同13modules各347passed/1既有warning，41.81s/41.97s；范围MUST_FIX关闭。中央full原10588 terminal exit0：949passed/32既有外部H1 skips/1既有Starlette warning/282.61s；compileall、pip check、diff0，源SHA不变，当前无live测试。新增有界head/private review桥、完整原GoalRecord事件证明、安全snapshot/recover闭合，见 HYBRID_GOAL_READS.md 与 evidence/checkpoint-31-final-tests.txt。实际保护配置加载→owned TCP读写/正常关闭不是CLI main、UI/性能或执行证明；M1/B1/NFR06/24h/8h、确认UI、lease/STOP/runtime、工程科研闭环与M0–M5完整Goal仍未通过且保持active。下一直接接真实合同审阅/nonce确认UI；USER package-lock不动。

最新30终态：root/High各301定向，中央full原11956exit0，913passed/32既有skips/1warning274.16s，范围无MUST_FIX，compileall/pip/diff0。实际CLI私有1.1配置可启用不可执行事实控制，旧1.0配置仍只读；existing-only attach无迁移/恢复/业务写，不承诺绝对无SQLite sidecar变化。证据见checkpoint-30-final-tests.txt/TRUSTED_WEB_CONFIG.md；配置ASGI+CLI mock不是新TCP或browser/性能证据。确认UI、goal/head公共桥、真实执行工程科研、B1/NFR06/长期仍缺，M1/完整Goal未通过，下方旧段为各自源版本证据。

最新29终态：root/High各289定向，冻结full原10082exit0，867passed/32既有skips/1warning267.24s，范围无MUST_FIX。下方候选/pending段为过程；无新browser/性能或实际工程科研闭环，M1/完整Goal仍未通过。当前production代码含显式opt-in不可执行HTTP控制，默认CLI只读；证据见checkpoint-29-final-tests.txt。

最新29候选：内部持续operator认证与显式opt-in command1.1 HTTP桥已实现，root/High各289目标passed，实际owned loopback HTTP断连/容量/原重试/条件批准与正常回收；无新browser/性能/UI/安装开关/执行证据。中央full原10082仍运行，下列795全量仅绑定28，M1未通过、完整Goal active。

2026-10-09，最新 checkpoint28（新增内部条件性批准/撤销事实与原事件恢复核验，仍无HTTP/UI写路由、lease或执行）；root及独立定向各207passed，全量原38620终态795passed/32既有skips/1warning/255.47s，范围无剩余MUST_FIX。此前性能绑定 checkpoint21/旧源码，不自动推广到新代码。此文件补齐 IMPLEMENTATION_PLAN §5 要求的 M1 报告；**不是 M1 完成声明**。M0–M5 的完整目标不变，剩余开发没有外部阻塞。

## 当前可运行范围

既有 Store 的真实事务经同事务 observation/outbox、closed public projection/counters、snapshot/keyset page、认证只读 HTTP/SSE 接入 Dashboard。当前 UI 支持真实业务事件的拓扑/状态/原因/预算未知、有限对象与虚拟事件窗口、公共日志、绑定 CPU 工具返回、HOST/磁盘与 worker loop/supervisor telemetry；未知不转0或模型 RUNNING。默认1.0配置/只读应用仍无写命令或 artifact 路径；29可信宿主注入与30私有1.1配置可显式启用不可执行控制服务，见HYBRID_CONTROL_API.md/TRUSTED_WEB_CONFIG.md。均不启动 scheduler 或调用模型。运行方式见 LOCAL_WEB.md。

最新生产源码冻结全回归：checkpoint31 **949 passed / 32既有外部/H1 skipped / 1既有警告 / 282.61s**，包括原控制/观测/Web/telemetry/私有事实与实际socket回归，以及有界Goal读取/原事件与snapshot/recover证明。source/log SHA 见 evidence/checkpoint-31-final-tests.txt。现有 UI checkpoint15 sandbox Chrome+Node **20 passed / 0 skipped / 9.44s**，用 owned loopback 与明确标记的业务 Fixture；HOST 资源来自实际 OS，本轮未新增 browser 结果。没有重新把这些测试跑成真实供应商闭环，也没有把节点心跳当作模型活动。

## 场景到证据

| PRD 场景 | 当前证据与范围 | 剩余门槛 |
|---|---|---|
| A10 兼容 adapter 不可观测 | hybrid observation 的缺usage/无有效startup proof、telemetry generation/旧槽UNKNOWN、closed工具metadata、UI Fixture/UNKNOWN通过；checkpoint08–14 | T11 Hybrid执行adapter及真实vendor event/usage/interrupt证据未完整接入；不能标完整A10通过 |
| A14 snapshot C→SSE | test_snapshot_stream_seam_and_idempotency、实际ASGI seam/reconnect、真实loopback及Chrome追平；checkpoint23真实100k/10k单项目HTTP双SSE/重连与400写入outbox核对 | 完整B1、维护并发与浏览器端到端延迟未测；HTTP探针不新增强制seam竞态证据 |
| A15 断连/重复/乱序 | reducer去重/版本、实际SSE断连追平、项目身份generation、事件缺口触发resync通过；静止不重复脉冲 | B1与8h断连长期一致性未证；当前没有新增Hybrid usage结算，不能推广为T14父子账款验收 |
| A16 旧cursor/epoch | retention floor、缺event/projection drift、rotate_epoch保留history且旧cursor拒绝、队列溢出/slow socket重建通过 | 可信备份/恢复演练与安全epoch切换/repair CLI需T23交付，不能据显式测试rotate宣布真实restore完成 |
| A17 没真实事件不增加业务数 | browser heartbeat/资源不推进业务cursor/counts、不调用app RAF、reducer重复不续动效；telemetry独立sample因果age通过 | B1长时idle/时钟扰动完整矩阵未测；短范围通过 |
| A18 浏览器失联不冒充GPU停止 | Chrome offline显示/停止脉冲、资源FRESH/STALE分域；GPU当前UNKNOWN | 未运行真实GPU，运行中GPU断网场景未证；不能为验收启用昂贵训练。受管CPU负载/后续批准GPU证据分开 |
| A32 100k/8h | Store增量事务/marker索引、周期维护锁外、虚拟窗口geometry/缓存；100k单对象历史ratio1.041488、10k归档task；组合daemon300s与checkpoint23单项目HTTP计划10/s+50/s完整400写入/双SSE | 活跃任务/3项目/限定硬件/浏览器双端完整B1、合计RSS/WAL/无全仓库poll及8h页面/24h fixture未完成 |
| A35 手机/键盘/减少动画 | 390px Chrome无横向溢出、虚拟事件键盘导航、reduced-motion/静止、文字状态通过 | Hybrid Dashboard审批/STOP交互尚未接入，29/30 HTTP条件批准已有但无STOP执行桥，既有CLI/core批准/STOP不变；可信手机交互/T16/T24及完整可访问性验收未完成 |

对应测试源码：tests/test_hybrid_observation.py、test_web_api.py、test_web_local.py、test_live_stream.py、test_telemetry.py；web_checks/browser.test.mjs、reducer.test.mjs、virtual-list.test.mjs、log-view.test.mjs、telemetry-view.test.mjs。表格不使用“有测试名”代替完整场景；上述通过仅指已记录冻结执行的匹配范围。

## 当前结论及下一项

Checkpoint23实际100k历史+10k归档task的32s有限HTTP负载已终态exit0：计划/实际400写、128查询、两消费者各400完整公开事件/一次重连，核心100401/公开100451/session0/source不变。提交调用开始→完整HTTP帧p95=246.724ms、snapshot8.144ms/page10.167ms，分phase发行lag与全部raw保留；不是DOM可见/完整B1/NFR gate。见HTTP_PERFORMANCE.md。Root及独立High相关21tests通过，终态原始证据High独立逐项重算吻合、无剩余MUST_FIX，无新生产代码修改。

Checkpoint22新的同100k/10k归档档案daemon-only300.000624s实测单核CPU0.849998%，相较旧单对1.7733%下降，CPU子指标<1%；301采样RSS33.641MiB、核心/公共/任务/会话/来源不变，完整原始baseline可复算。见IDLE_PERFORMANCE.md/evidence。仍全控制仓库逐秒轮询、无API合计与完整B1/长期，所以NFR06/M1 gate依旧未通过，不拿局部CPU结果解除其它门槛。

M1 gate **未通过**，不是失败即停止整个Goal。真实历史固定单对象cardinality 10k→100k探针已终态exit0、ratio1.041488≤2与recover==audit==replay通过，见 HISTORY_PERFORMANCE.md；只证明该单轴，不代替完整B1。随后按证据测真实10k任务/活跃工作、B1读写与idle、维护RSS/WAL，并继续真实来源与长期场景。不能通过删除历史、放宽时限、编造counter或无说明跳过来通过。

M2–M5 未完整交付：T09私有持久DRAFT基础按T01/T03前置实施，immutable合同/receipt与CAS head不授予权限；见HYBRID_GOAL_DRAFTS.md。可信authority/命令/STOP/lease/runtime/结算/独立评审、实验与科研状态、资源可靠性、安装迁移、可信远程与历史纯回放仍待执行。按显式依赖推进，但可写闭环上线必须满足可信批准与可靠STOP，不由只读Dashboard或草案持久化代替。

Checkpoint18补测两轴组合：真实100k历史backup+10k归档任务，daemon-only 300.000899s单核CPU1.773328%，未达<1%；业务与来源不变、sessions0、采样RSS38.016MiB。原始证据见IDLE_PERFORMANCE.md；没有API/活跃工作/限定B1硬件，不宣称NFR06通过，且当前逐秒全控制仓库watch本身违反无全仓库轮询条件。下一项是保留安全不变量的空闲热路径优化，不降低验收门槛。
