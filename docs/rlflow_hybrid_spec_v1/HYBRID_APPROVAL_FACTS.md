# Hybrid 不可变批准事实

Checkpoint28 实现；定向 root 与独立 High 各 207 项通过，冻结全量原 session38620 终态 exit0：795 passed、32 既有 skipped、1 既有 warning，255.47 秒。证据见 `evidence/checkpoint-28-final-tests.txt`。这里只记录内部服务，不是 HTTP 写接口或执行准入。

## 保存的事实与边界

`ApprovalService` 由可信启动代码固定绑定 Store、AuthStore、Registry、项目、数据模式和 Origin。同一个 Store 对象不接受另一套 owner。它不接收 caller Principal/Access 或 JSON `human` 声明作为批准凭据；真实 session 必须具备 human/approver/project 权限和正确 CSRF。Agent Bearer 不可批准。

四个 optional private-hot 集合不进入旧公共 view：`hybrid_approval_facts`、`hybrid_approval_revocations`、`hybrid_approval_heads`、`hybrid_approval_commands`。批准和撤销事实、原命令回执不可变，head 只指向同一目标的最新完整链。批准不改写原 DRAFT，也不创建 legacy approval、task、model session 或 lease。

状态只可能是 `LEASE_VALIDATION_PENDING` 或 `REVOKED`，所有返回均为 `execution_enabled=false`。可信配置内容核验不是实际数据字节、OS 隔离或资源能力证明；确认视图明确列出这些未验证限制。已知无法保证 hard-required token 约束时拒绝；UNKNOWN 不得升级成可执行。

## 明确确认与提交

prepare 在一致只读事务中读取精确 DRAFT、服务端 diff、Registry 全内容 scope/config hash、epoch、全局版本和 authority revision。服务端生成随机 nonce，完整视图 hash 绑定这些内容及请求期限（1–86400 秒）。确认缓存最多 128 项，所有容量门、插入、清理和读取共享互斥锁；nonce 不超过 120 秒且不超过实际 session 寿命，并绑定 token hash，而非仅 human ID。

approve 重新认证，并在 writer/BEGIN 后进入真实 AuthStore 签发的 guard。Auth 锁覆盖提交前最后一次检查及 commit。Store 同时要求服务本次实际签发的 request/fact 摘要上下文：单有真实 guard 和 nonce 也不能通过 generic writer 伪造批准时间或事实。服务活动上下文和 guard 在成功、异常及 rollback 后均清理。

epoch、全局版本、DRAFT revision/hash、完整注册配置和 authority revision 在实际核心事务中核对。相同确认 ID 有持久唯一 fact key，换 idempotency key 不得再次消费。nonce 只在成功提交后清理；失败提交可在仍有效时重试。最后提交检查同时核 session、nonce 和绝对批准到期时间，过期回滚核心及同事务公共观测写入。

原 idempotency key 的合法重试仍需新鲜认证，但返回原 receipt、原 approved/expires 时间和原 accepted version；缓存丢失、当前配置变更、当前到期或 head 前进不延长或改写历史。撤销必须明确指定当前批准 key、全局版本、authority revision 和 reason，另追加事实，不回写批准。

## 历史真实性与恢复

回放使用历史 transition 校验，不使用当前 session、clock 或当前 Registry。audit、recover、手动和周期 snapshot 校验完整项目/模式、不可变合同和注册 witness、唯一版本链、predecessor hash、最新 head、每个 fact 的唯一原 receipt 及源事件顺序。

原事件 witness 不只比较 request hash：它比较实际原核心事件中 fact、receipt 和当时 head 的三个对象摘要及 event type/producer/request hash/accepted version。即使同时平移批准/到期或撤销时间并重算快照内部所有摘要，也必须与原事件不符。读取按事件 key 索引，实际 payload 与 blob 有界且核摘要；周期维护沿用其解析、节点、字节及时间预算，失败不清除 due 或覆盖旧 snapshot。

这不是对可同时任意改写整个数据库和所有核心事件的攻击提供外部签名证明，也不是多进程 AuthStore 一致性协议。凭据不进入事实；private registry witness 为绑定内容，不作为公共 API 数据发布。

## 尚未完成

后续 checkpoint29 已新增固定 operator 服务与显式 opt-in 的 command1.1 HTTP 桥，见 HYBRID_CONTROL_API.md；不是默认 CLI 开启写入，也未交付确认 UI。下段保留 checkpoint28 当时边界，28 的回归不能替代29验证。

暂无 proposal1.1 HTTP/MCP/skill 提交桥、确认 UI 或写路由；未创建用户真实批准，也未启动模型、GPU 或本开发 Goal。实际 adapter 数据校验、能力 preflight、STOP/fencing、lease、调度和工程/科研闭环仍需后续实现。T09、M1/B1、长期测试及完整 M0–M5 目标没有因内部服务测试而完成。
