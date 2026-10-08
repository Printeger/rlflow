# 实际 BLOCKED 准入观察

Checkpoint36 增量，基于 checkpoint35 `b320daa`。root/独立 High 同六模块各263passed，中央全量1393passed/32既有skip/1warning；这不是 execution lease、workspace 排他权或 T11/T12 完成声明。

## 保护端与提交

AdmissionService 固定实际 Store、Registry、ControllerService 和 PreparationService，要求一致的 project、data mode、observation epoch 与 Registry。调用方持有实际发行的 ControllerToken；复制、JSON、另一 owner 或磁盘重建不能取得权限。新的准入请求固定预期全局版本和原 preparation intent，事实只能追加，幂等键不能换请求。

真实材料文件核验在 writer 外由 PreparationService 完成，发行内存 MaterialWitness；固定 owner 的 weak-reference cache 仅识别原对象。witness 同时受 UTC 和本 boot monotonic 30 秒期限约束，时钟回退拒绝。它证明一次顺序核验的 as-of 观察，不证明多个可变目录的联合原子冻结，也不授予候选写入权。

实际提交采用 Store writer → Controller owner 锁序及 owned `BEGIN IMMEDIATE`，不接受调用方 read transaction 或外部连接。写入前校验全局 CAS、当前 controller head/tip、原 fact/direct predecessor source、Goal/approval 当前条件与原事件、实际 witness。Admission guard 在 Store 写入后仍保留到 Controller 最终 token 检查、Admission 最终 callback 和 owned COMMIT；任一期限或身份校验失败回滚整个事实。材料文件 IO 与 Preparation owner 大锁不在这个 writer 内。

当前 Controller point proof 只验证固定 head/tip、原 fact 和直接 predecessor，读点数初始为一、后续为二；远祖 corruption 由完整历史审计拒绝，不能把单次 current check 描述为全远祖审计或 NFR 性能证明。

## 不可执行事实

`hybrid_admission_facts` 的唯一事件为 `HYBRID_ADMISSION_BLOCKED`：status=BLOCKED，reason=EXECUTION_GATES_UNVERIFIED；candidate_write_enabled、release_enabled、execution_enabled 均为 false。controller 当前点、来源当前条件和材料 as-of 观察单独记为已核查；legacy_exclusion、model_access、actual_data、os_resources、writer_lease、budget_reservation、stop_recovery 保持 UNVERIFIED。

没有 HTTP、worker、模型会话或 release API；也不把此事实接到旧 dispatcher 的 READY→RUNNING 路径。重复请求只返回原 BLOCKED 事实，不能续期、重新核验材料或恢复丢失 token/witness。

## 历史闭合

Store 新写与 replay 均要求 closed 单事实事件；只有首个事件包含空 collection marker。原事件 proof 核 event type、producer、object hash、version、SHA、精确 descriptor 与 marker，拒绝额外 mutation、delete、details、重复对象和浮点 format。读取有 raw/decoded envelope；这不是整个 legacy SQL/JSON 预读取的全局内存界。

audit、manual snapshot、periodic snapshot 和 recover 同时核原 preparation/controller/Goal/approval proof、历史引用以及 `seq <= state.version` 的原 Admission tip 和事件数量。数量可发现非最新事实遗漏；重算快照 hash 后删掉整个域或清空域也不得通过。旧版本合法快照加新 tail 按该版本的历史 summary 验证；后续 controller renewal、当前期限已过或临时内存 witness 已消失不废除原 BLOCKED 事实。

## 验证与范围

定向夹具只使用隔离的真实 SQLite、真实准备副本和当前进程身份，不启动 paid model/GPU。原事件损坏夹具临时移除 disposable DB 的 append-only trigger，注入后必须先恢复原 trigger，再调用产品；生产保护不放宽。root原50623与独立原41876真实terminalexit0，各263passed/1既有warning，81.63s/82.57s；中央full原11991真实terminalexit0，1393passed/32既有skip/1warning，408.56s。15 SHA前后一致、独立范围无MUST、compileall/pipcheck/diff0；当前无live测试。精确 source/log hashes、早期失败和修复见 evidence/checkpoint-36-final-tests.txt；这些早期日志不能重标为最终版本。

完整统一执行准入仍缺工作区 legacy 排除、预算 reservation/settlement、跨项目资源池、实际 OS/model/data 门、可靠 STOP/lease lifeguard、restart material adoption 和工程/科研执行闭环。M0–M5 Goal 保持 active。
