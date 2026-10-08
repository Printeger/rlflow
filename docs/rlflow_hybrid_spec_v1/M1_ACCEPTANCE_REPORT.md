# M1 退出门槛审计（尚未通过）

2026-10-08，当前生产 checkpoint `4623b42`。此文件补齐 IMPLEMENTATION_PLAN §5 要求的 M1 报告；**不是 M1 完成声明**。M0–M5 的完整目标不变，剩余开发没有外部阻塞。

## 当前可运行范围

既有 Store 的真实事务经同事务 observation/outbox、closed public projection/counters、snapshot/keyset page、认证只读 HTTP/SSE 接入 Dashboard。当前 UI 支持真实业务事件的拓扑/状态/原因/预算未知、有限对象与虚拟事件窗口、公共日志、绑定 CPU 工具返回、HOST/磁盘与 worker loop/supervisor telemetry；未知不转0或模型 RUNNING。HTTP 不启动 scheduler 或调用模型，没有写命令或 artifact 路径。运行方式见 LOCAL_WEB.md。

生产源码冻结全回归：checkpoint15 **586 passed / 32既有外部依赖 skipped / 1既有警告 / 215.49s**，其中包括 Web/观测/telemetry/Store。现有 sandbox Chrome+Node **20 passed / 0 skipped / 9.44s**，用 owned loopback 与明确标记的业务 Fixture；HOST 资源来自实际 OS。source/log SHA 见 evidence/checkpoint-15-final-tests.txt。没有重新把这些测试跑成真实供应商闭环，也没有把节点心跳当作模型活动。

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
| A35 手机/键盘/减少动画 | 390px Chrome无横向溢出、虚拟事件键盘导航、reduced-motion/静止、文字状态通过 | Hybrid Web审批/STOP命令尚未接入，既有CLI/core批准/STOP不变；可信手机交互/T16/T24及完整可访问性验收未完成 |

对应测试源码：tests/test_hybrid_observation.py、test_web_api.py、test_web_local.py、test_live_stream.py、test_telemetry.py；web_checks/browser.test.mjs、reducer.test.mjs、virtual-list.test.mjs、log-view.test.mjs、telemetry-view.test.mjs。表格不使用“有测试名”代替完整场景；上述通过仅指已记录冻结执行的匹配范围。

## 当前结论及下一项

Checkpoint23实际100k历史+10k归档task的32s有限HTTP负载已终态exit0：计划/实际400写、128查询、两消费者各400完整公开事件/一次重连，核心100401/公开100451/session0/source不变。提交调用开始→完整HTTP帧p95=246.724ms、snapshot8.144ms/page10.167ms，分phase发行lag与全部raw保留；不是DOM可见/完整B1/NFR gate。见HTTP_PERFORMANCE.md。Root及独立High相关21tests通过，终态原始证据High独立逐项重算吻合、无剩余MUST_FIX，无新生产代码修改。

Checkpoint22新的同100k/10k归档档案daemon-only300.000624s实测单核CPU0.849998%，相较旧单对1.7733%下降，CPU子指标<1%；301采样RSS33.641MiB、核心/公共/任务/会话/来源不变，完整原始baseline可复算。见IDLE_PERFORMANCE.md/evidence。仍全控制仓库逐秒轮询、无API合计与完整B1/长期，所以NFR06/M1 gate依旧未通过，不拿局部CPU结果解除其它门槛。

M1 gate **未通过**，不是失败即停止整个Goal。真实历史固定单对象cardinality 10k→100k探针已终态exit0、ratio1.041488≤2与recover==audit==replay通过，见 HISTORY_PERFORMANCE.md；只证明该单轴，不代替完整B1。随后按证据测真实10k任务/活跃工作、B1读写与idle、维护RSS/WAL，并继续真实来源与长期场景。不能通过删除历史、放宽时限、编造counter或无说明跳过来通过。

M2–M5 待执行：GoalContract/可信authority/命令/STOP/lease/runtime/结算/独立评审、实验与科研状态、资源可靠性、安装迁移、可信远程与历史纯回放。可按依赖开展设计/静态探索，但可写闭环上线必须满足可信批准与可靠STOP，不由只读Dashboard通过代替。

Checkpoint18补测两轴组合：真实100k历史backup+10k归档任务，daemon-only 300.000899s单核CPU1.773328%，未达<1%；业务与来源不变、sessions0、采样RSS38.016MiB。原始证据见IDLE_PERFORMANCE.md；没有API/活跃工作/限定B1硬件，不宣称NFR06通过，且当前逐秒全控制仓库watch本身违反无全仓库轮询条件。下一项是保留安全不变量的空闲热路径优化，不降低验收门槛。
