# Workspace transactional renewal：checkpoint39 设计，尚未实施

基于checkpoint38（root/High九modules各358pass，中央full原95667实际1621pass/32既有skip/1warning589.10s）。此文件是下一阶段设计，不是39新运行证据或权限。38服务renew继续拒绝，全部runtime门仍关闭。独立High只读设计已复核以下故障边界。

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

未实施39前不将此设计记作T12完成；runtime register/release、legacy fencing、共享host pool、可信usage与可靠STOP继续另行交付。
