# Native exec 准备组件（不可执行）

Checkpoint33 是 T11 的内部物料切片，不是完整 Runtime Adapter 或 Hybrid 执行验收。
没有 HTTP/CLI 接线、Store 准备记录、session、预算扣款、worker、START_ACK 或 release。
`start()` 无条件拒绝，即使传入条件批准、伪 lease 或旧系统审批。

## 固定配置与实际物料

`rlflow/execution_adapter.py` 仅接受保护控制端构造的不可变 Registry，以及已存在、
当前 UID 所有、0700 的非 symlink 控制目录。runtime_profile 使用闭合字段：
adapter=`codex-exec`、显式 model/effort、codex_version=`0.161.0`、
native_subagents=false、cpu_network=none、memory_bytes、command_seconds。
未知字段、其它 adapter/version、原生委派或 CPU allowlist 不降级接受。
注册 resource_profile 仍是不透明配置，不能当作实际 OS 强制证据。

`plan_preparation(packet, candidate=..., write_roots=...)` 绑定 packet、完整
Registry hash、受信 role TOML/schema、candidate/write-root 路径及 dev/inode。
这些路径由内部保护调用者提供，不是 HTTP 输入。Engineer 必须显式列出写目录；
其它 role 不得列写目录。控制目录与 candidate 不得互相包含，写目录必须在
candidate 内；最多128个具体 list/tuple 元素，在路径读取前拒绝超量与 generator。
输入是256KiB有界副本，最多缓存128个实际签发 plan；相同内容/路径返回同对象。
plan 对象身份是本 adapter 的内部能力，不是跨进程身份或 OS sandbox。

`materialize_preparation(plan)` 复用现有 `isolation.codex_command`，只允许
非生成的 `codex --version` 探测。它读取真实位置的模型 metadata 文件，不用
`_census_catalog` 作为账号缺失的 fallback，也不连接 provider。所选 model/effort
不在 catalog 时拒绝。测试使用显式临时 cache 和仅 --version 的 mock，不能证明
真实账号可用或真实 Codex 执行成功。

物料为 packet.json、result.schema.json、command-plan.json、受限 models.json、
CPU MCP 配置和 manifest.json；所有文件0600，封存目录/control/scratch 为0700。
command-plan 状态为 PREPARATION_ONLY、execution_enabled=false。复用原 masking
策略关闭 native shell/patch/web/delegation/goals 等，保留单个受控 cpu_exec；无
第二份 native 安全配置。JSON `-c` 参数先解码再迁移路径，支持引号、反斜线和 Unicode。
环境/代理/认证变量不持久化，产物不能当作无凭据运行包。

## 完整性与有限失败行为

根目录 inode 固定且使用非阻塞目录 flock，避免不同实例覆盖同一准备目录。
实际签发 plan 及原 in-memory manifest digest/文件集合/目录身份共同核验；不能
同时改文件和重算 manifest 获得信任。普通文件使用 NOFOLLOW/NONBLOCK 打开，
拒 FIFO/symlink/hardlink、不安全权限、超量字节；JSON 拒重复键/nonfinite/depth>64。
最终核验累计物料含 manifest 不超过16MiB，不重复读取 packet 来重复消耗预算。

正常异常仅清理本次创建且身份未变的 unpublished `.preparing-*`。已经 publish
的目录和其它目录不删除、不覆盖；失败或重启后没有实际 seal 的旧物料拒绝收养。
没有 crash reconcile/resume，崩溃可能留下 stage；留给下一持久准备服务处理，不能
以重新发起或读取本地 manifest 冒充安全恢复。16MiB 是最终物料/读取上界，**不是
临时磁盘硬配额**：现有 helper 可能先写序列化 catalog，再被累计物料界拒绝。

seal 只覆盖列举文件和固定目录身份，不覆盖 scratch 未知文件全集，不证明
candidate 实际内容 hash、binary/实现身份、内核资源/网络强制、账号权限或审批来源。
packet 的 source/hash/epoch/revision 标识只是声明，此阶段不验证其 Store 原始来源。
source_authority/model_access/actual_data/os_resources/controller_lease/writer_lease/
budget_reservation/stop_recovery 全部 UNVERIFIED，所有状态不可执行。

## 后续依赖与证据

下一步：固定 Store/Registry/project/mode/epoch 的 source-bound 持久准备服务，
完整原 GoalRecord 与 approval 事实证明、当前头与 expiry/revoke/config 校验、
私有 provisional staging→提交 immutable intent（包含预期 manifest/file seal）→
publish→完成记录，以及 audit/replay/snapshot/recover 闭合。只有 plan_hash 不能
恢复 publish 后、completion 前的崩溃窗口：不能用当前磁盘 manifest 自证。实际
candidate hash 来自保护端显式有限文件清单的副本/字节，而不是 packet 声明值。
现有 Git/SourceIndex helper 尚无完整目录/时间/总读取界，不能直接宣称有界。
不得将条件批准
翻译成 legacy RELEASE_COMMITTED。随后才实现统一 lease/budget/STOP admission，
精确 generation/fencing 身份及实际 worker release 再核验。

官方 [non-interactive 文档](https://learn.chatgpt.com/docs/non-interactive-mode)
说明 exec JSONL 与结果 schema 的接口形态；本地固定 CLI 兼容性是单独的证据。
[App Server 文档](https://learn.chatgpt.com/docs/app-server) 是另一个协议，不能把
其 schema hash 或 interrupt 响应当作 exec 事件合同或 OS 进程树回收证明。

冻结测试与独立复核见 `evidence/checkpoint-33-final-tests.txt`：root/High同4modules
各115passed，中央full原77231终态1003passed/32既有skips/1既有warning；所有exit0。
完整 T11/T12/T14/T17、M1/B1/NFR06、24h/8h、工程/科研和 M0–M5 未验收。
