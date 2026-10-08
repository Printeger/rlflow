# 批准认证的事务守卫（T09/T16 增量，非批准事实服务）

Checkpoint27。新增 `AuthStore.approval_guard` 及 Store scoped事务私有 `_authorization` factory。这是可信服务使用的认证原语，不是批准事实、确认页面、HTTP写命令、租约或执行能力；还未实现完整 ApprovalService。所有新测试只向 disposable fixture 写 USAGE_OBSERVED，不伪造真实人类批准、也不调度开发Goal。

## 单宿主认证与提交顺序

固定批准服务必须自持 protected-startup AuthStore/Origin/Project/Registry/Store，不接受请求自带 Principal/Access/AuthStore/guard/attestation 作为凭据。`approval_guard` 接实际 session token、固定项目与 CSRF，锁内重新读取该 AuthStore session，校验有效期、method=session、human、对应项目 approver 与 CSRF。viewer/operator/bearer 不升为 approver；返回的内部 guard 只能在本 context 的拥有线程调用 check，退出后或别的线程拒绝。token/CSRF Unicode或错型均以固定 PermissionError拒绝，不回显秘密。

Store顺序是：writer文件锁 → SQLite BEGIN IMMEDIATE → Auth lock/重新认证 → 幂等/选定对象/mutation/验证/事件及public outbox准备 → 再认证 → SQLite commit → Auth unlock → writer unlock。等待文件锁或 SQL writer 时尚不持有 Auth lock，因此撤销可先完成；先行 `resolve` 返回的 Access 不保证等待结束后仍有效。

提交期间其他线程 revoke 与 Auth lock 序列化：若先撤销，拒绝事实；若事实已进入 guard 的线性化临界段，则提交完成后撤销。临提交前再次检查 clock，过期即抛错回滚整个 SQLite事务。guard exit 只释放锁，不在已经提交后才检查或吞异常。重复命令也必须新鲜认证，查到旧事实后再查过期，明确关闭只读事务后才退出 guard，不重新写事实或更新期限。

此锁只提供**同一个受保护进程、同一个 AuthStore owner** 内的撤销原子性，不能在多个独立 AuthStore/服务进程间替代持久化撤销。重启原session token失效，不允许重用旧Access作为认证。以后单控制writer与服务部署必须保持该owner关系。

## 受保护调用约束

`_authorization` 是可信控制代码参数，绝不能由 JSON/agent 构造。有配置factory但 context 未返回带 check 的guard时 fail closed；既有未使用该参数的 scoped事务保持原行为。此通用 Store 参数不是授权许可规则：未来 Hybrid批准记录的转换/不可变/恢复守卫仍须另实现，不能通过通用写入伪造批准。

持 Auth lock 时不得再调用 login/resolve/revoke 等重新获取同一非重入锁的方法，也不得反向获取 Store writer锁；固定服务在guard内仅用 check 读取真实身份、在既有事务里验证精确合同与 Registry binding。不能将 context 内 Access保存成下一命令的有效凭据。

Origin 必须由服务固定可信边界核验，本helper自身没有Origin参数，不能声称已交付SEC-04完整写路由。确认nonce、服务端diff、approval expiry/revoke事实、原receipt绑定、snapshot/recover/audit与lease/STOP/预算/实际隔离等门还待下一切片，认证成功也不能自动READY。

## 当前测试记录

Root最终五模块112passed/9.28s，原80475 terminal exit0。覆盖真实fixture passphrase/session、角色/项目/bearer/伪Principal与Access/CSRF、线程/生命周期、文件及SQLwriter等待中撤销/过期、并发撤销线性顺序、准备完核心事件与public outbox后过期整笔rollback（四个public表逐行不变）、重复lookup后过期及COMMIT-before-guard-exit trace、异常后锁恢复、配置但无guard拒绝。

首轮两处fixture错误保留日志并已修复（默认bearerTTL高于fixture TTL10、objects返回list）；r2/r3为中间证据，最终含全部delta的是r4。独立High五模块112passed/9.31s（62069终态exit0），范围无剩余MUST_FIX；冻结全回归762passed/32既有外部/H1skips/1既有Starlette warning/247.08s（原62752终态exit0）。命令和SHA见 evidence/checkpoint-27-final-tests.txt；不能把checkpoint25的689全量绑定到此变更。没有新增browser/性能/模型或GPU结果。
