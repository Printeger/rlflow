# 固定应用共享三槽池（Checkpoint 42）

交付行为：同一个受保护 fixture 应用下的多个已发布项目、多个原进程共同使用三个实际目录 flock 槽。第四个占用拒绝；CLAIM/UNKNOWN/CLOSE_INTENT 均持续占额。进程死亡、TTL 到期、重启或空闲内核锁都不自动返还。原进程先提交不可逆 NO_HANDOFF 关闭事实，再关闭全部原描述符，最后用原关闭见证提交 FREE。重试保留原 attempt、原 FD 和原 TTL；历史 JSON、复制对象、历史占用或调用者路径不能恢复活能力。

受保护启动接口 `HostPoolOwner.create_fixture(parent)` 创建新的私有应用；`trusted_attach(application_root, descriptor_sha256, descriptor_identity)` 仅接收启动配置固定的原描述符哈希与 inode。应用内固定 `host_pool/` 与 `projects/`，项目注册不能选择池目录。注册要求实际 FixtureInstallationService 发布的原 material/BootstrapWitness；重新加入已注册项目只产生来源型 Membership，不接管旧 CLAIM。无 HTTP/env 池选择或 claim-adoption 接口。

运行接口：`register_project`、`join_registered`、`snapshot`、`claim`、`check`、`mark_unknown`、`request_close_no_handoff`、`close_original`、`complete_close`、`audit`、`shutdown`。写入要求原能力身份与 CAS；`start` 无条件拒绝。CLAIM 非 ExecutionLease，所有 `execution_enabled`/`release_enabled` 均 false。

持久事实存入原私有 SQLite（DELETE/FULL）、原 writer flock，最多 4096 facts/64 项目/每 fact 16384 bytes。查询槽位与 REGISTER 计数使用原 raw JSON 的表达式索引，不相信辅助 action/slot 列；每次操作核固定表/索引/trigger DDL，点读同时核原 raw、hash、所有 SQL headers。SQL 文本列通过 typeof/byte-length CASE 先限制，再进入 Python；head 必须与推导结果逐字节相同，不接受 int/float 等值替代。

Linux 固定 sqlite3 connector 前后做有限原生 RW FD census（最多 4096 FD），只接受唯一新打开、与原数据库 inode 一致的私有 CLOEXEC 描述符；不确定/并发额外 FD 一律拒绝，不退回路径 stat。该原生 FD 在首次 SQL 前和提交前核验。原 writer、路径、来源、slot FD 等所有 IO 后才检查原 UTC/monotonic TTL，紧接实际 COMMIT；不刷新 TTL。hot 操作保留 5 秒 cooperative envelope 与固定深度索引证明。启动/显式 audit 用固定 30 秒 envelope 全量有限重放历史和投影；正常操作不遍历全部历史。

原 slot 对象与原 CLAIM 强绑定，旧 FREE 重试不能触及同号槽的新 CLAIM。部分关闭失败保留未关闭 FD，不签发 all-closed 见证；原关闭可以继续重试。真实 fork 子进程关闭继承的池/slot/native SQLite/rollback journal 描述符，绝不 LOCK_UN 或调用继承 SQLite 清理；原父进程保持锁，子进程所有旧能力拒绝。继承 SQLite 对象在子进程隔离保留，避免析构误关复用 FD。

验收条件：跨项目/实际进程只能占用三个；第四个不追加；死亡/重启不返还；原关闭三步可重试且 all-FD 见证不可复制；实际 COMMIT 前/后丢返回不制造第二 attempt；损坏索引/header/head、原数据库换回、最后 IO 的 TTL/锁失败均拒绝；启动/显式 audit 能发现非当前历史损坏。证据见 [checkpoint-42-pool-tests.txt](evidence/checkpoint-42-pool-tests.txt)，当前最终审查/集成/提交状态以该文件与 PROGRESS 为准。

剩余缺口：只证明此受保护的 managed fixture 应用，不是任意安装、非合作同 UID 程序或整个主机的生产强隔离/全局限额。未迁移生产，未调用模型/GPU/provider。没有 Runtime/预算双库 REGISTER、可信 UsageOwner、执行 handoff、完整 process-tree STOP、OS/model/data 限制或 Dashboard 新运行验收。下一可信用量来源，然后最小安全端到端执行与可靠 STOP；不能以本池 primitive 的测试数量宣称这些需求完成。
