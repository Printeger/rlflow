# Hybrid v1 开发进度

Checkpoint28完整终态覆盖下述live过程：不可变条件性批准/撤销、实际human session确认、固定服务与核心事务gate、原receipt/fact/head三对象source核验及手动/周期snapshot+recover闭合完成；root/High9modules分别207passed12.82s/12.75s，无剩余范围MUST_FIX。冻结全量原38620 terminal exit0：795passed/32既有外部/H1skips/1既有Starlette warning/255.47s；compileall/pip/diff0。见HYBRID_APPROVAL_FACTS.md/evidence/checkpoint-28-final-tests.txt。目前没有live测试或负载。仍无HTTP/UI写桥、实际数据/OSpreflight、lease/STOP新执行闭环或真实用户批准；无新browser/性能证据。下一版本化DRAFT提交/查询与精确human确认HTTP桥，然后STOP/fencing/lease/runtime；完整T09/M1/B1/24h/8h及M0–M5 Goal active，用户package-lock不动不stage。

Checkpoint28全量原handle登记：session38620，audit/hybrid-v1/checkpoint-28-full-r1.log，当前live；源码/测试冻结，勿重复或并行测试/负载。后续终态记录覆盖此过程，旧762只绑定27。

Checkpoint28独立目标终态：High同9modules207passed12.75s，原4180exit0，四项MUST_FIX与新增负例闭合、无新MUST_FIX；独立log c073ab0b5ed524b84098802bf0a5a23defdb5ad3b2a707b3ae0185da6ad87985。root现在启动冻结全量 checkpoint-28-full-r1.log（见后续原handle登记），源码/测试冻结、不并行测试/benchmark；查原终态、不因观察timeout重起。仅私有条件性consent/revocation，不是完整T09或执行许可，Goal active。

Checkpoint28最新定向终态：root9modules207passed12.82s，原93936exit0，audit/hybrid-v1/checkpoint-28-authority-r5.log；compileall/diff0。r4未collect：shell环境自动加载ROS pytest插件缺lark，原命令exit1/log保留，r5使用既有PYTEST_DISABLE_PLUGIN_AUTOLOAD=1，未更改标准/跳过项目测试。High现在获准一次独立同9模块复验，root不并行launch full或benchmark；源码/测试冻结。HYBRID_APPROVAL_FACTS.md记录候选真实边界，仍无执行准入或HTTP写接口，完整Goal active。

Checkpoint28批准事实候选已接入（未提交）：固定Store/AuthStore/Registry/service owner、真实session+Origin/CSRF、session-bound nonce、有界互斥缓存、服务实际签发的request/fact上下文；私有immutable approval/revocation/head/originalreceipt及同事务CAS、rollback、历史恢复/周期snapshot原事件三对象摘要核验已实现。没有HTTP写路由/lease/执行权限，状态仅LEASE_VALIDATION_PENDING或REVOKED，DRAFT不改写。root r1兼容/fixture失败已修复，r2原65462终态107passed10.16s；安全review指出缓存并发、仅guard不足以证明明确确认、历史时间可平移及超长token先hash四项，候选修复均已落盘。r3原53750终态2failed/112passed11.00s，两处失败来自新增测试末尾误置断言（NameError），已修正；补纯nonce到期而session有效、四public表rollback、同human不同session拒绝、撤销后再批准及历史revoked_at篡改负例。尚无最终独立执行或新全量结果，旧762仅绑定27；接下来冻结目标回归、High独立复验与中央Store全量。用户package-lock保留，完整T09/M0–M5 Goal active。

Checkpoint28身份前置独立终态：root33passed2.97s（48685exit0），High33passed2.95s（70424exit0），范围无MUST_FIX，compileall/diff0；目前没有live测试/负载。web_auth SHA9bcb477595fcd599a48b5aa796f283f933577dbc686253a95f279de16f6b4803；newtest9cad4f9d955ff29d49f736f8c22499e03732633dafe60698c806af0cd8da90f7；rootlog52ec799528749373db88c6a84360013f863c96508f1a8b5dc5610c192395fa9c；Highlog7a6e9bee6d170ee008313243e57196669268e134f413023d14b19be7aa28f8e7。仍是未提交28前置（latest commitf6373f1），不是ApprovalService/通用live批准gate已经实现；762全量仅绑定27。下一直接实现批准事实服务与核心hooks，不需继续审查相同已通过identity helper或重复33测试：固定Store/Auth owner核实际guard，4 optional私有集合+有界private registry witness、nonce confirmation/CAS/currentepoch与有限期限、live拒绝伪JSON、历史只验closure/source、不因现在过期拒绝snapshot。完整Goal active，无外部阻塞；USER package-lock保留。

Checkpoint28批准事实服务开始（未提交）：27已提交f6373f1/完整762终态。High设计明确live通用写入也必须验证启动绑定AuthStore实际签发的guard，不能仅信human JSON/producer或任意check对象；replay/snapshot只验证历史事实/合同/有界private registry witness/原核心receipt，不使用当前session/clock/catalog。先实现AuthStore issuedguard identity（eq=False；实际issuer+ownerthread+project+active membership；copy/伪Access/foreignissuer拒绝、finally清理），root相关3modules33passed2.97s、原48685terminalexit0，compileall/diff通过；High此delta只读/独立复验待回，源码冻结，无新full结果。尚未Store绑定owner/批准四集合/nonce确认/ApprovalService，不能据identity函数声称通用批准门完成。下一实现固定服务+私有immutable approval/revocation/head/originalreceipt，同txn CAS当前revision/epoch/fullscope/globalversion、finiteexpiry/retry不续期、提交前nonce不永久consume、durable confirmation_id唯一与恢复闭合。无write route/lease/实际Goal批准或执行；完整T09/M1–M5继续，USER package-lock保留，Goal active。

Checkpoint27完整终态覆盖下述live过程：真实session认证与Store→Auth事务守卫、撤销/过期/幂等/rollback闭合，root112passed9.28s/独立112passed9.31s、范围无MUST_FIX，冻结全回归762passed/32既有外部/H1skips/1既有Starlette warning/247.08s，原62752terminal exit0，不再live。compileall/pip/diff通过，见HYBRID_APPROVAL_AUTH.md/evidence/checkpoint-27-final-tests.txt。仍无ApprovalService/批准事实/Origin桥/写路由或执行权限；无新browser/性能证据。下一不可变批准/撤销和receipt/snapshot/recovery，完整T09/M1/B1/长期与M2–M5继续开发，Goal active，用户package-lock保留。

Checkpoint27独立目标终态覆盖下述过程：root最终112passed9.28s（80475exit0），High112passed9.31s（62069exit0），范围无剩余MUST_FIX，compileall/diff通过。guarded duplicate commit顺序与四public表rollback直接核验闭合。当前中央Store变更冻结全回归原session62752 live，audit/hybrid-v1/checkpoint-27-full-r1.log；源码/测试冻结，无parallel tests/benchmark，恢复先查同handle，不因观察timeout另起。最新commit仍03891a9，守卫27未提交，见HYBRID_APPROVAL_AUTH.md。下一确认全量终态→SHA/证据/最终独立文档复核→commit，然后实现固定AuthStore/Origin/Registry/Store的不可变批准/撤销与原receipt、snapshot/recovery闭合。认证primitive不等于批准事实/路由/执行，完整T09/M1/B1/长期及M2–M5未完成，Goal active，USER package-lock保留。

Checkpoint27最新覆盖下述r3记录：r3原9294已terminal exit0，110passed9.11s。High静态无MUST_FIX，发现两个非阻塞证据/结构改进：guarded duplicate纯读事务亦显式commit后才退出Auth，新增lookup后过期及COMMIT-before-exit实际trace；_commit后过期回滚直接核对public meta/events/projection/counters完整行不变。r4原80475运行，日志checkpoint-27-guard-r4.log，源码测试冻结，High尚未启动独立pytest，勿重起/并行。批准事实与完整Guard/Store全量尚未完成；Goal active。

Checkpoint27认证事务守卫开发中（未提交）：26已提交03891a9。AuthStore.approval_guard在真实session下锁内核human/approver/project/CSRF，禁止guard跨线程或退出后复用；Store scoped事务可由固定服务传private guard factory，writer+BEGIN后才进入、涵盖幂等和全部提交、紧邻commit再查过期、配置guard缺失fail closed。没有批准事实/ApprovalService/Origin桥/写API/lease或执行权限。r1两处fixture错误（bearer默认TTL超过fixture10、objects是list）保留并修复，r2 107passed8.70s终态；新增SQLwriter等待与缺失guard负例后，最终r3原9294运行，audit/hybrid-v1/checkpoint-27-guard-r3.log，源码/测试冻结，High静态复核中，勿并行测试/超时重起。下一核对原终态→独立复验→中央Store变更全回归→批准事实与snapshot/recovery闭合。旧689全量仅绑定25；Goal active，USER package-lock保留。

Checkpoint26：可信启动immutable Registry纯核验实现，整proposal+整catalog（含policy/rules）scope绑定，工具/命令依赖、网络三层subset、数据version/purpose/access与冻结rule逐项拒绝。root130passed3.45s、独立High130passed3.43s，原96925/3366皆terminal exit0，范围无MUST_FIX。见HYBRID_REGISTRY.md/evidence/checkpoint-26-final-tests.txt。结果NOT_EXECUTABLE，无auth/approve/routes/Store写入/执行/数据文件或资源能力探测；既有源码入口未变，此次针对性回归，全量689仅绑定25。下一自持Registry/AuthStore的真实session批准事实与单写恢复闭合，不能信caller attestation。完整T09/M1/B1/长期/M2–M5仍待开发，Goal active，无新增外部阻塞，USER package-lock保留。

Checkpoint25终态：schema1.1 显式工具/registry-profile hash/评价数据与冻结规则声明兼容旧1.0不可变版本；仍仅UNAPPROVED DRAFT。root/独立High三模块80passed，冻结全量689passed/32既有skips/1既有warning/238.29s，原83613已terminal exit0，不再live。范围MUST_FIX关闭，见HYBRID_GOAL_DRAFTS.md/evidence/checkpoint-25-final-tests.txt。无1.1 command/HTTP/MCP/skill桥、实际registry核验或审批/lease/执行；无新增browser/性能证据，完整T09/M1/B1/长期与M2–M5继续开发，Goal active，无新增外部阻塞，用户package-lock保留。

Checkpoint25独立目标回归已终态：范围MUST_FIX（研究强制dataset）关闭，root最终3modules80passed2.75s，High80passed3.31s、原84196/8520皆exit0；旧1.0字节保持、1.1只是显式未批准声明，不构成授权。当前新一次全量pytest原session83613 live，日志audit/hybrid-v1/checkpoint-25-full-r1.log；源码/测试/schema冻结，无parallel tests或benchmark，恢复只查同handle，不因观察timeout重启。最新已提交仍4f48e68（663结果绑定24），schema25未提交。下一核对全量终态/归档与commit，再按High方案实现固定AuthStore/Origin/project service的真实human session批准事实；未实现1.1 command/HTTP/MCP提交、实际registry核验、审批/lease/闭环，不虚称T09/M1/M2–M5完成。Goal active，用户package-lock保持。

Checkpoint25范围复核后更新：High确认PRD未要求每research都有dataset，已移除额外收窄，不逼理论/生成输入研究伪造数据引用。任意Goal可显式NONE（datasets=[]+冻结rule ID/hash），REGISTERED仍必须非空；未来具体method需数据时由可信approval/adapter拒绝NONE，不能拿NONE作metric证据。r2源码67passed3.08s已终态；补5registry必填、rule/dataset子字段必填、REG空集、同DSid不同版本/access实际propose原子拒绝，以及research NONE真实DRAFT恢复正例。当前r3原84196运行/源冻结，独立delta复核中，不因观察timeout重起。仍无approve/routes/lease，command.submit_goal1.0未变，不声称HTTP/skill已支持新1.1。旧schema三份字节SHA44e607d0…30a1不变。Goal active，全T09/M1–M5及长期仍缺。

Checkpoint25/schema1.1开始（未提交）：checkpoint24已提交4f48e68。新增goal_v1_1.schema.json独立urn与版本判别，显式allowed_tools/5个registry-runtime-resource hash/closed evaluation_data（dataset ID/version/purpose/access+rule ID/hash），GoalContract/request兼容1.0/1.1 oneOf；旧goal.schema字节SHA与HEAD4f48精确一致、旧proposal/hash不回填。root相关3modules **67passed/3.65s**，原76191 terminalexit0，compileall/diff通过；High只读新协议复核中，特别核research必须dataset是否超出PRD（理论/生成输入可能合法显式NONE，尚待基于需求取舍）。无approve service/routes/lease/model，registryhash只是未批准声明，完整T09仍待真实session/Origin/CSRF/human approver与trustedregistry/fencing等；663全量只绑定checkpoint24，不冒充新source全测。新源冻结待review建议再修改；USER package-lock保留，Goal active。

Checkpoint24独立/完整终态覆盖下述过程：新私有DRAFT persistence/不可变revision+原receipt/CAS head/事务项目与内容绑定/手动周期snapshot+recover闭合完成；四项High MUST_FIX与producer tuple增量均关闭。最终root新模块36passed2.79s、High7模块161passed9.91s，冻结全回归 **663passed/32既有外部/H1skips/1既有warning/234.49s**，原66508 terminal exit0（30841/27011亦已终态），compileall/pip/diff通过。见HYBRID_GOAL_DRAFTS.md/evidence/checkpoint-24-final-tests.txt；无browser/性能重跑，不把旧0.85%或HTTP246.7ms归到新代码。仅T09草案首切片，完整可信批准/工具与评价数据/schema1.1、STOP/lease/runtime/M1/B1/长期及M0–M5 Goal仍未完成；下一继续1.1精确边界和真实human认证批准，独立设计进行中。用户package-lock保留不stage，Goal active。

Checkpoint24冻结全回归进行中：四项High MUST_FIX及重试producer一致性补齐；root最终goal模块36passed/2.79s，独立最终7模块161passed/9.91s，30841/27011已终态exit0。当前全量pytest原66508 live，日志audit/hybrid-v1/checkpoint-24-full-r1.log；源码/测试/schema冻结，不因观察timeout另起suite。compileall/pip check/diff已通过，无browser/benchmark新结果（旧性能证据只绑定旧源码）。HYBRID_GOAL_DRAFTS.md记录draft无批准边界与完整T09待办；下一真实human审批/schema1.1独立设计只读并行，不执行approve/模型/调度。Goal active，用户package-lock保留。

Checkpoint24/T09 draft代码实现中（未提交）：新增hybrid_goals.py，同Store三个optional private-hot集合（immutable contracts/commands、CAS heads），内容namespace eventkey+requesthash object_id、原receipt/coreevent version返回、canonical hash/服务端JSONpointerdiff；DRAFT/UNAPPROVED/approval与outcome null，无HTTP write/approve/调度/legacy authority改动。不改initial；RuntimeState/runtime validator、commit同事务registration/不可变转换、audit/recover/manual+periodic snapshot完整closure+indexed原事件核验已接入。High指出capacity入口绕过、周期snapshot漏closure、恢复receipt错原版本及重复marker导致SQL/replay分歧，已分别补守卫/真实负例，静态再复核中。root r1 23passed1.72s、r2相关148passed8.52s、r3 155passed9.08s、r4 157passed9.26s；当前r5原session77671运行源码冻结、不能因观察timeout重启。尚未独立测试/full回归，不声称T09/M1/Goal完成。旧schema1.0缺evaluation-data/tools仍仅存不完整草案，未来批准必需补齐新版本再确认。用户package-lock保留不stage。

Checkpoint24/T09开始（仅调查、尚未代码修改）：checkpoint23已提交a9c6155。已重读PRD§5/§14/命令合同、GoalContract/Approval/proposal schema、legacy contracts/Store/RuntimeState/web_auth；legacy goals由packages写ACTIVE/DONE，不能冒充Hybrid合同，Store._existing不绑定payload，新的幂等必须显式内容绑定。考虑独立optional私有合同revision/head，复用同一Store事件+projection事务/恢复，不新增初始marker破坏旧fixture，不启动HTTP写路由/调度；High独立架构探索进行中。evaluation-data/tool范围在原proposal尚未完整，需要版本兼容设计；持久draft不等于可信approve/完整T09/A01/A02/A29通过。下一闭合设计→实现draft切片/确定性负例，再按依赖可信批准/STOP/执行闭环。完整M1 gate/B1/长期及M2–M5仍缺，Goal active；无新live进程，用户package-lock保留。

Checkpoint23独立终态覆盖下述过程记录：原79247已exit0/API1198582 TERM-15/reaped/ownsfalse；100k+10k归档档案真实32秒400写、两SSE各400事件/各一次重连、128查询全部完成，core100401/public100451/task10000 exact/session0/source不变。submit-call→HTTP完整帧p95 246.724ms、snapshot8.144/page10.167ms；全计划/发行lag/raw/digest/核心来源与hash独立逐项重算精确吻合，无剩余MUST_FIX。Root21passed/10.21s、High21passed/10.65s；生产源码未改，未新增full/browser重跑。见HTTP_PERFORMANCE.md/evidence。仅单项目归档HTTP子证据，非DOM/B1/NFR/M1通过。下一按前置T01/T03推进T09合同与可信主体基础（不提前启用可写闭环），并保留完整B1/无全仓库poll/长期等M1缺口；Goal active，用户package-lock保留。

Checkpoint23进行中（未提交）：新增有限HTTP并发驱动，生产默认SSE参数、两条独立连接各真实Last-Event-ID重连、并发snapshot/page、绝对计划30s×10/s+2s×50/s共400次真实Store写。保存全部计划/发行lag/调用返回/完整收帧并按最终outbox+digest核对；分phase统计，不把commit-return负差冒充真实commit latency；完整core/task/session/source不变量、最终校验失败raw与owned API回收均覆盖。相关r4 **16passed/5.66s**，30731终态exit0；High完整驱动只读复核中，尚未100k/10k负载。默认pytest受到全局ROS插件缺lark影响，沿用禁用第三方plugin自动加载的既有测试环境；r3文件名错误无测试执行亦保留。生产源码未改，用户package-lock不stage；完整B1/NFR06/M1–M5仍未完成，Goal active。

Checkpoint23基础：22已提交49f709b/CPU子指标独立确认0.849998%，完整NFR06/B1/M1仍缺。新增tests/acceptance_http_v1.py父-owned loopback readonly API child基础：复用完整parent guard、PDEATHSIG改SIGKILL避免uvicorn graceful父死亡延存、父预绑127 socket传fd、privatepipe传token不入argv/log、正常TERM/kill/reap及失败fd关闭；child仅ObservationReader/create_app，不Store/daemon。r6相关11passed/2.77s、compileall/diff通过，原98336终态exit0、无live child；High只读基础无MUST_FIX（未独立跑测试）。r1测试head独立store_epoch字段不存在失败保留，改head cursor精确核验epoch后passed；模板仅两个sentinel唯一检查非整段SHA锁定。生产源码未改，用户package-lock保留不stage。

下一实现有限HTTP/SSE并发driver（尚无负载证据）：严格100k history只读backup+10kDONE/allfalse；生产默认SSE参数、两个独立receivers、唯一trusted writer绝对发行计划10/s30s+50/s2s，保存全部发行delay/提交前后monotonic/完整frame接收时间/状态/错误/吞吐分母，真正并发bounded snapshot/page。实际SQLite outbox序列核对seam/顺序/无重复缺口/Last-Event-ID重连，heartbeat不计domain。launch后立即finally覆盖print/readiness/client，证据strip token；先真实认证snapshot核验项目/fixture/epoch/cursor。只测单项目归档HTTP/transport，不冒充浏览器NFR01、API+daemon idle、3projects/activeGoal/限定硬件或fullB1。继续安全sourceguard局限设计及完整M0–M5，不在checkpoint终止Goal。

Checkpoint22独立终态核验完成：High逐float精确重算baseline/CPU/elapsed、RSS/301单调样本/allfalse DONE任务与core/public/epoch/session/sourceDB+WAL/identity/generation/log/退出/归档SHA全部匹配，无剩余证据/安全MUST_FIX。生产仍7be43b8，未新增full/browser/test或benchmark重跑；见IDLE_PERFORMANCE.md/evidence/checkpoint-22-final-tests.txt。仅daemon-onlyCPU子指标0.849998%通过，无全仓库轮询/B1/M1/完整M0–M5仍待实现，Goal active。

Checkpoint22终态exit0覆盖下述live记录：原53811已结束/child1197221 TERM-reap/ownsfalse，100k+10k同档案实际300.000624s单核CPU0.849998%（daemon-only CPU子指标<1%）、sampled RSS35274752B、301样本；baseline原始重算精确一致，core100001/public100051/task10000/session0/source保持不变，telemetryfinalseq300仅辅助。见IDLE_PERFORMANCE.md与evidence/checkpoint-22-idle.jsonl，独立终态核验待补。旧1.7733%失败保留；本对仅合计观察不做单项因果，仍全仓库watch/API+B1/长期/完整M1 gate及M2–M5未满足，Goal active。

Checkpoint22长测live：checkpoint21已提交7be43b8，原full614/32/1与High86终态且新probe启动前安全无阻塞。当前新一次同100k/10k档案300s真实daemon测量，父原工具session53811、daemon PID1197221/PGID1197221/starttime142347570/boot fa257cc3-1204-4e6f-88a5-a8a2ea7743aa；audit/hybrid-v1/checkpoint-22-idle-r1.log，core100001/public100051、新epoch store_351132e5203548729d858cdae0dd729a。source SHA仍bb148ad0b22bfbe27632915e3985b1a643bcf3fb1836f6fa84e045ad3756db4c，仅只读backup，没有活跃Goal/model/API。源码/测试/配置冻结，无并行测试；恢复先查同handle、不能因观察timeout另起probe。仅测三项view-elision合计CPU收益，结果待终态；全仓库watch与generation未改，不能宣称完整NFR06/B1/M1通过。Goal active。

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
| T09 | DRAFT/1.1/Registry与内部条件性批准事实已实现，完整任务未完成 | 私有immutable revision/批准撤销事实/原receipt、CAS head、恢复原事件核验；fixture真实human session认证确认但无HTTP/UI桥或执行；实际数据来源与能力核验、lease仍待实现 |
| T10–T17 | 未开始 | 策略、受控 Runtime、单写、独立评审、预算、skill、控制与恢复 |
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
