# Workspace transactional renewal：checkpoint39 已验证增量

基于checkpoint38 `fcfcb4f`，39实际实现与最终验证：root/High同十二modules各408pass（230.29s/228.66s），中央full原98257实际exit0，1671pass/32既有skip/1既有warning633.86s；24SHA一致、范围无剩余MUST、compileall/pipcheck/diff0。最终证据见evidence/checkpoint-39-final-tests.txt，阶段失败/修复保留在checkpoint-39-development-tests.txt。全部runtime门仍关闭；这是执行前协作hold续期，不是完整T12或M0–M5验收。

## 当前实际候选接口

WorkspaceService.prepare_renewal(actual_old, ttl_seconds)在writer/Service/Working锁外重新核验原准备物料并签发actual MaterialWitness，重核原actual slot后生成或找回同一原PendingRenewal；现存pending不重签、续时或换epoch。Working使用单一canonical registry附着/退休/abort，lost-return通过原actual current slot可达；所有非renew写同锁核Service与Working两层pending identity，避免Service挂接失返漏挡后续关闭。

record(renew request, actual Controller token, actual PendingRenewal)同writer核当前source/HELD/claim/原HEAD与原旧、新obs，再绑定实际写尝试request/fact；错误workspace/reservation/goal请求不得污染原pending。Controller内部held context覆盖实际COMMIT及memory-only激活；context不得吞异常导致SQLite外层自动提交。helper激活用原候选与绝对epoch，可修复每次字段赋值后的中间异常；Service交换原候选/实际fresh witness，保留原memory ACK重试。

ack_renewal(original_fact_key, actual_pending)核原完整事件、历史sources/current exactHEAD及实际Kernel，不要求今天human/material/workspace TTL有效；只对齐原候选cleanup lineage。单slot保留最后原ACK对象以支持重复ACK，不覆盖新的未决pending。abort_renewal(actual_pending)须确认未提交原事件及原HEAD（已绑定写尝试时），保留原FD。过期candidate的livecheck仍拒绝；关闭仍要求fresh实际Controller，绝不把ACK当权限刷新或refund。

开发阶段root helper121pass/0.81s、commit-context70pass/6.22s、服务r9 23pass/1既有warn31.22s只绑定各自版本；最终root原1676与High原31145同十二modules各408pass，中央full原98257亦已实际exit0，24SHA前后匹配。High阶段MUST（多字段异常、context吞异常、request污染、lostattach canonical gate）均按具体证据修复，范围无剩余MUST。不修改原T12/PRD验收门槛。服务Kernel案例是注入proof失败，foreignPending不是跨进程重启验证。

## 不先替换当前观察

WorkingCopyOwner.prepare_renewal(old, ttl)生成实际PendingRenewal，持有原slot/hold、old和预分配new原对象。epoch仅old+1；每slot至多一个、全局有界。身份先于raw解析。slot.current仍old，普通check(new)拒绝；未决pending阻继续renew、close_request和未来REGISTER。不得调用现有立即替换式helper renew完成持久续期。

Workspace私有pending绑定完整原request、priorHead、候选renew fact hash与两观察的原raw/期限。新候选不重新copy/flock、不替换FD、不退款。writer→Controller→Workspace→Working锁序，在COMMIT及内存activation期间保留Working锁。当前source/approval/material/Budget HELD/NOT_AUTHORIZED/claim/head与旧、新观察双UTC/mono最终期限均核验；旧观察到期不能续期复活。

锁必须覆盖Controller外层context退出时的实际COMMIT，不能仅在token_transaction内层with锁包yield（内层会先释放）。建议Controller内部commit-context factory/ExitStack在writer→Controller→BEGIN之后进入Workspace→Working上下文，覆盖body/finalchecks/COMMIT/activation，再逆序释放；不在writer前拿Working锁。ACK只需writer→Workspace→Working一致原点证明，不生成新的权威事实。

## COMMIT 与内存ACK分离

Controller新增internal post-success-COMMIT hook，只有db.commit正常返回后调用，与所有路径执行的_on_exit区别。activation只交换预生成原对象，不读取SQL/文件、不生成UUID/epoch/新期限。Working与Service两个slot必须一致切换。activation前或后故障保留原pending，可显式ACK。

COMMIT attempted后异常可能已durable，不能立即abort、关闭FD或重生成候选。WorkspaceService.ack_renewal(key, actual_pending)在同独占writer一致事务中核原renew event完整pointproof、历史sources、当前精确HEAD/tip/claim、私有pending与原old/new raw/hash、实际slot/hold当前Kernel/owner。当前slot可为原old或同一new以处理swap后异常；不采用caller JSON或磁盘candidate。

成功ACK仅同步两个slot到原new并退休pending；重复ACK不epoch+2。new即使已过期也仅恢复cleanup lineage，livecheck照常拒绝，绝不延长TTL或授执行许可。历史来源证明不要求今天approval有效或currentBudget仍HELD，避免阻止保守清理；后续live续期仍必须核全部当前门。

如果同独占writer确认原event不存在且旧HEAD/tip未变，才可显式abort原pending保留old FD。已知COMMIT成功却event消失、原proof损坏、别的HEAD、FD失锁或能力不可达均UNKNOWN/quarantine，不reopen/flock/adopt。重启或没有原pending只能返回历史回执，不能ACK能力。

## ACK后关闭

最小接口先阻止未ACK下游写，保证currentHEAD精确是原renew。ACK后的fresh Controller可绑定new HEAD/new raw提交CLOSE_REQUESTED，再实际关闭同FD并签发绑定new observation的close witness，再持久completion。关闭不要求旧human/观察TTL有效，不证明runtime已停止或可退款。

## 最低验证集合

- actual COMMIT前raise、真实commit后raise，分别确认未提交/未知返回的原pending处理。
- activation前后raise，原pending ACK可重复且同epoch、同FD。
- new过期后ACK，livecheck拒绝但new-lineage两阶段关闭成功。
- fake/copied/foreign pending先身份拒绝；缺原slot或重启不能adopt。
- commit后Kernel失锁拒绝，不重新flock。
- CANCEL/UNKNOWN/CLOSE_REQUESTED先赢CAS，renew不得提交；原能力仍可保守清理。
- writer等待期间old/new期限到期拒绝；未ACK并发close/REGISTER拒绝。
- 双线程只有一个续期胜出、无ABBA；rollback不丢原FD。
- 原renew历史audit/replay/manual/periodic snapshot/recover闭合。

39已实施并验证此增量，但不记作完整T12完成；runtime register/release、legacy fencing、共享host pool、可信usage与可靠STOP继续另行交付。
