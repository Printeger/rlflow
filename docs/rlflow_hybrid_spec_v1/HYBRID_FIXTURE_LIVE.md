# 原持久事件驱动的固定 CPU Task 观察：Checkpoint 48

本切片仅扩展47既有 Dashboard 的只读观察行为，不改变44–46的执行能力、Task来源或人工命令接口。状态与原时间线来自真实45 GET；自动刷新不 poll 原 Runtime/Source、不写事实、不触发模型、GPU或新 Task。

## 行为与异步边界

已经验证的 snapshot/reducer `source_state_version` 构成当前身份/项目/模式/epoch/auth-generation scope 内的单调高水位。仅非重复 domain 事件通知变化；heartbeat/telemetry 不增加版本，不伪造 workerfresh/current运行。

面板显示连接状态、Task as-of、已接收持久版本和 STALE；旧详情不足当前高水位时不能创建新的 Start/Stop 请求。连接 LIVE 不等于当前执行已知，Task 原字段仍是 UNKNOWN/NOT_OBSERVED。版本必须先绑定完整 scope；clear 不吸旧 floor，同项目换epoch的 CONNECTING 回调也不能把旧版本带入新快照。

同scope最多一批只读请求在途。自动批次最多每秒一次（手动读取与命令后读取不是统一1Hz门）；先等待有限 page/profile 两GET都结束，再在同ticket读取保留选择的原timeline。请求期间的新 domain 仍更新高水位，不能用批次开始时的旧版本清 stale。没有固定轮询或无事件无限刷新。

人工命令在途只记 dirty，不更改其ticket或GET打断；回执后读取事实，原UNKNOWN/STOP意图始终保留确切body/key/selector。自动刷新不改CAS、不选择新Task、不自动写。读取在途则禁新命令和retry，避免读/写ticket混淆；身份scope清除仍立即生效、清定时器和选择，迟到响应不能回填。

HTTP/来源合同错误取消自动刷新，保留as-of/STALE，需要明确手动读取。只对实际fetch/network TypeError标记transport failure；由非活动连接状态实际恢复到 CATCHING UP/LIVE后才允许一次有dirty的只读恢复。连续相同LIVE心跳不重试失败GET，不重试命令。离线取消定时器；回调再次核scope、dirty、连接和blocked状态。

## 原时间线

选择保留不可变TaskID/AttemptID/reservation三元组，仅重读同selector。最多七个原Budget事件，闭合字段、唯一event_id、安全整数严格递增、不超过response as-of；以REGISTER_NO_HANDOFF为首，末phase/version与Task recorded值一致。

合法边与原ledger一致：登记→HANDOFF→PROCESS_REGISTERED→RELEASE_INTENT→STARTED_AS_OBSERVED，各未STOP阶段都可提前STOP，STOP→FIXTURE_SCOPE_STOPPED。不接受排序但跳过必要启动阶段的假链。时间是历史recorded_at，不是当前存活/资源释放/费用证明。

## 验收与当前记录

新增真实Chrome两身份：operator正常人工Start/Stop；viewer仅GET，断线时保留旧详情，真实SSE补发后自动恢复原五阶段，再自动观察原七阶段；实际producer reap/Pool0由可信原host检查，网页仍NOT_OBSERVED；心跳不增加GET/POST，注销清时间线。

开发中真实失败保留：原3837首次登录超时；随后原68025 DOM诊断显示Illegal invocation。另用独立Chrome最小检查证明原生setTimeout/clearTimeout作为Panel方法调用均失败、arrow wrapper通过，精确修复，没有提高超时。原95021及原75273断线恢复超时；完整owner/两页DOM诊断证明后端Start/G/ACK与operator时间线正确，viewer因离线fetch失败留autoBlocked；按上述实际重连只读恢复规则修复，不修改runtime/期限。Node r3的null/false单元失败只归一dirty为Boolean，不放宽断言。snapshotfloor及旧同项目epoch污染由独立High审查指出并精确关闭测试。

旧GET在SSE已经恢复后才报transport错误的交错，也由实际重连generation处理：ticket记发起generation，网络失败已经跨过一次恢复且当前active时只排一次有限只读恢复，同generation再次失败则blocked。scope清除重置generation，原Pending不改变。

原97698最终真实失败于host inspect的Pool native SQLite FD来源检查；Pool RLock只串同owner，无法阻止其他Project读连接同时创建RW WAL/SHM。原helper错误要求整个进程新增RW文件FD只有一个，因此外部无关inode造成生产并发误拒。精确修复仅计原Pool expected(dev,ino)的唯一新增候选；before已有目标、候选0/多个仍拒，4096 census和权限/owner/nlink/inherit/SQL前pin/COMMIT前再核不变。它只适用于固定可信connector、协作的私有应用；不宣称任意db参数或非合作sameUID raw连接隔离。

新增实际另一线程在Pool connect census期间打开并保持SQLite/WAL/SHM：Pool snapshot/claim成功；零/两个/旧目标及wrongDB+外部噪声负例均拒，5pass2.51s。Node16用例通过，包含完整scope floor、同项目换epoch与重连后旧GET才失败。原1109浏览器实际exit0、1pass29.755s：两身份真实断线补发5/7阶段、viewer无POST、原CPU reap/Pool0与心跳不GET均验证。

必要Pool/control/reads原49236实际52pass/3fail/3warning351.29s：三损坏注入夹具只结束SQLite事务而未关连接，先触发已有目标FD保护。最小实际实验确认根因，未放宽生产检查；注入连接以closing明确关闭，HostPool定向原3978实际31pass76.37s，包括原swap/restore拒绝。High找到的另一Runtime注入同修，精确source-corruption原35333实际1pass9.85s；已通过未改control/reads不重跑，也不虚称修复后fresh整套55pass。必要前端原26954实际53pass62.100s，含47真实STOP故障后原key续清；新live browser不重复。两夹具修复外236输入保持，最终238 SHA/编译/依赖/diff通过，无live测试。原失败与诊断全部归档见evidence/checkpoint-48-final-tests.txt与log-sha256。47 commit96517431950fe5c0ae46a3ca9c4763638a942630。

依旧不证明native/模型、候选修改、任意树STOP、真正工程科研、严格OS资源与invoice、24h/8h长期、安装迁移或完整Goal。未经授权不调用付费资源、不迁移生产状态。
