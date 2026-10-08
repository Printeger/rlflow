# 可信 Web 控制配置（checkpoint30）

本切片把 checkpoint29 的不可执行 HTTP 控制桥接到实际 `rlflow.web serve`。不是执行授权、完整安装迁移或 M1/M2–M5 通过声明。checkpoint31 已新增 head 列表及 human private review 读桥，见 [HYBRID_GOAL_READS.md](HYBRID_GOAL_READS.md)；Dashboard 确认 UI 仍未接入。命令语义见 [HYBRID_CONTROL_API.md](HYBRID_CONTROL_API.md)。

## 默认与显式启用

`prepare` 仍创建 schema `1.0`、仅 human/viewer 的私有配置，仍是用户明确请求的观测迁移。`load_config(path)` 保留旧三元组 API，只接受 `1.0`；不能把 `1.1` 的 controls 静默丢弃。旧配置中出现 `controls` 也拒绝，不作为隐含开关。

新增 `load_server_config(path)` 返回 `(origin, projects, auth, controls)`，CLI `serve` 使用该入口。`1.0` 的 controls 总为空，绝不构造/attach Store。`1.1` 的 controls 为空时也不 attach Store；其项目只做注册观测的只读核验。

可信操作者可在受保护本地文件中显式声明 `1.1`。顶层必须且只能含：

| 字段 | 约束 |
|---|---|
| `schema_version` | `"1.1"` |
| `origin` | 明确 HTTP loopback IP/端口，无路径、userinfo、query、fragment |
| `projects` | 1–128 项，closed `{id, root, data_mode}`，ID 与 canonical root 不重复，已有 root |
| `credentials` | 1–128 项，closed `{principal_id, kind, roles, projects, salt, digest}`；只允许 human；scope 全属已配置项目 |
| `controls` | 0–128 项，键为项目 ID；值为完整 inline `Registry.CATALOG`，project/mode 与对应项目完全一致 |

`roles` 是明确的 viewer/operator/approver 集合，不自动添加 operator 或 approver。Salt/digest 必须保持既有 Credential 的有效十六进制格式；不把明文口令、Cookie、CSRF 或 Bearer 放进配置。Registry 完整字段以 `rlflow.hybrid_registry.CATALOG` 为准，不能用 capability 名称或占位 profile 冒充实际强制能力。配置、Registry、数据库路径和 credential 都不能经 HTTP 上传、替换或选择。

已有 `prepare` 的 `1.0` 文件可由可信操作者本地审阅后明确改成上述 `1.1` 格式，保留 origin/projects/credential 盐和摘要，明确修改所需 human roles 并加入完整 inline catalog。服务不提供自动升级，不能仅改 version 字符串或填写假 catalog。

## 文件与数据库边界

只打开当前 UID 拥有、其他用户无权限的 regular 配置文件，使用 NOFOLLOW/NONBLOCK/CLOEXEC。拒绝 symlink、FIFO、目录、权限过宽、重复 JSON 键、非有限数字（包括 `1e309`）、超深结构。共同读取/解析上界为 **2 MiB**，nesting 最多48；旧 `1.0` 的接受上界仍为 **64 KiB**，不是旧读取内存上界完全不变的声明。每个 Registry 另受已有256 KiB/节点预算约束。

controls 项目必须已有当前 UID 拥有且其他用户不可写的 canonical root、非 symlink runtime 目录、regular research.db 和既有 regular writer.lock。常规 Store 创建受进程 umask 影响，服务不会擅自 chmod；操作者应先明确保护这些实际路径，不能对 workspace 或 home 做宽泛递归权限修改。

`Store.attach_existing` 在只读一致事务中检查完整列顺序/类型/nullability、PK/UNIQUE、整数 rowid 主键语义、追加/不可变触发器、既有 WAL 模式、注册 project/mode/epoch、core/public projection 版本与尾序号、floor/flags 与 snapshot maintenance 元数据。缺迁移、未注册、损坏或版本不同步拒绝，需要明确离线 prepare/recovery；不调用 Store 初始化、audit 全历史、rebuild、enable 或 CREATE/ALTER。它不是全库历史完整性审计。

所有 catalog/身份先核验，所有项目数据库预检结束后才绑定服务。每个启用项目使用唯一 attached Store，两个 service 共享同一个 AuthStore、固定 Origin 与 Registry。后续业务连接用 `mode=rw`，不重建缺失数据库或切换 journal；数据库与 writer.lock 的 inode 变化会拒绝使用。这不是任意同 UID 进程/可信 OS 管理员的攻击沙箱。

启动没有业务 event、批准、version、观测注册、DDL、迁移或恢复写入；测试核对逻辑行、sqlite_master 与 SQL trace。**SQLite 可正常维护 WAL/SHM 侧文件**，不承诺绝对无文件变化，不使用 immutable 模式读取活跃 WAL，也不删除、复制或截断 sidecar。参见 [SQLite WAL read-only 说明](https://www.sqlite.org/wal.html#read_only_databases)。

## 运行

在既有、显式准备的项目及私有配置上运行：

```bash
.venv/bin/python -m rlflow.web serve --config /absolute/private/web.json
```

无公网/执行启用选项；关闭 proxy headers、access log、server header。配置错误统一 exit2，不输出文件名、Registry、credential、路径或 SQL 异常。加载不启动 scheduler、模型、lease 或 job。重启使登录会话失效。

加载实际配置后通过 ASGI TestClient 的 HTTP submit→confirmation→approve→original receipt 集成证明 DRAFT 与 LEASE_VALIDATION_PENDING 持久事实、`execution_enabled=false`。CLI 测试 mock uvicorn.run 核真实 loader 与监听选项，不冒充新增 TCP 安装测试；checkpoint29 的 owned socket 验证也不能自动重标为本加载器证据。未证明 UI 确认、实际用户批准当前开发 Goal、可用执行环境或真实模型闭环。
