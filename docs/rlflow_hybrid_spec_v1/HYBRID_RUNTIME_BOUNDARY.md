# Runtime boundary：checkpoint40 已验证切片，非执行

父版本39 `d598233`。真实新fixture非执行安装/原INTENT/内核发布/READY与失败恢复已接线；root/High最终同21modules各534pass/8既有外部skip/1既有warning（345.80s/344.19s），22SHA一致，范围无剩余MUST。中央full原14894实际terminal exit0/chunkd5431d：1818pass/32既有外部H1skip/1既有warning678.02s，compileall/pipcheck/diffcheck均exit0，无live测试。真实失败与修复见evidence/checkpoint-40-development-tests.txt，冻结清单及终态见evidence/checkpoint-40-final-tests.txt。不把此切片称为既有安装迁移、完整T12/M1/M0–M5或运行验收。

## 已实现边界

`runtime_boundary_policy.py` 是强制release-local策略。源码默认是明确的 `LEGACY_UNBOUND`，不是从策略文件缺失推导“旧模式”。未来guarded fixture生成自身BOUND descriptor，固定catalog绝对路径、原SHA、inode及完整物理parent chain；HOME/CWD/env/HTTP/argv请求不能选择这个信任根。文件/父链/身份/权限/类型/闭合schema损坏均拒绝，不自动降级。

`hybrid_runtime_boundary.check_legacy` 先核固定安装策略与有限原catalog，再核保留路径和物理ancestor aliases。catalog读取保留原全链/parent dirfd，相对NOFOLLOW/NONBLOCK打开、单fd上限64KiB/hash/inode/nlink/owner私有权限，读后复核stamp与当前物理链。Linux仅支持本地ext4/xfs/btrfs/tmpfs、mount-root `/`，不从subtree bind/network/overlay推断不相交。最多16scope/128affected paths、闭合实际整数chain、绝对有限路径/NUL/穿越拒绝；没有可续期的“legacy permit token”。

`check_cold_entry()` 不接收请求参数。BOUND release冷worker、held-role、experiment worker、CPU raw `_supervised/_child`、fakejobs child/supervisor一律拒绝，包括请求声称另一root/scratch、另一boot/有效lease/legacy布尔值。检查在读取request/解析JSON/加载dispatcher/资源写入之前；父入口路径检查不能替代冷执行能力证明。CPU最终可信侧检查位于Landlock之前，绝不扩大模型/CPU对控制源码/catalog的读取权限。初次把此检查放在Landlock之后导致8项真实兼容失败，已按实际错误修复并保留原日志。

父派发/inner派发/schedule、原worker、startup协议1早返回、lifeguard新启动、资源预留、repairs、experiments submit/dispatcher exec/业务gate、CPU/MCP/native物料与fakejobs新启动已接入拒绝检查。原身份核验/回收、reconcile/status/lifeguard恢复不因拒绝新启动而被禁用。未启用的旧安装保留原行为，但这不证明某个已绑定scope可从另一UNBOUND release访问。

## 实际新fixture非执行安装（已实施、回归通过）

pure installation域闭合INTENT/READY原seal与完整原事件元数据/输入/tip-count；FixtureMaterialBuilder实际创建新私有Store/epoch与独立namespace，固定DB、runtime父链及writer/维护锁 inode并复制受控source。源遍历保留原目录FD图，文件相对打开须匹配captured stamp并读后核身份；最后复查原文件、目录和完整祖先链。Stage全量closed inventory拒根extra/cache/额外空目录/symlink/nonregular/非私有入口，最多1024代码文件、2048目录、4096枚举项、64深度、16MiB代码。fsync使用同一有限目录FD清单，不再rglob。一次30s合作式deadline贯穿copy/inventory/read/hash/fsync/catalog和最终owner检查；不承诺kernel阻塞IO timeout。重复prepare核原seal，单次失败仍保留原blocked attempt；冷执行测试使用 `-B` 防止字节码污染。Builder自身publish仍明确PermissionError，只有固定FixtureInstallationService能按原core proof发布，绝不把verify或自报磁盘manifest当许可。

仅支持实际新建的私有isolated fixture安装，不热迁移既有root/旧release/运行中或UNKNOWN进程。先预分配唯一INTENT key及accepted version，固定stage/catalog/release保留路径与原inode/chain；catalog引用 `(intent_key, accepted_state_version)`，不反向嵌入完整INTENT digest。

依赖顺序：catalog bytes/SHA → BOUND descriptor → guarded release manifest/treeID → 核心INTENT保存完整原expected seal → 按原seal发布/目录fsync → 同writer CAS核心READY。这样避免catalog/INTENT/release hash成环，也避免以当前磁盘自报manifest替代原核心seal。

INTENT与READY分别是不可变原事件/原metadata/sourceproof；两次CAS核固定Store/project/fixture/epoch、完整physical roots/DB identity/bootstrap来源及唯一publication。重型哈希在writer外，短期原held inventory witness保留FD/stamp；Store writer→Service→Builder原锁覆盖同DB BEGIN、原全point校验及实际COMMIT。最后原sourceproof后再witness+deadline，COMMIT紧前再期限检查。对installation域/事件的通用回调、foreign guard及复制物料均拒；其它合法核心写入仍可推进version，从而使未完成READY的fresh CAS拒绝。私有域不会在普通Store.view展开，完整历史通过replay/audit或有界原point读取。

发布只用原parent FD的 Linux `renameat2(RENAME_NOREPLACE)`，不支持就拒绝，不用普通rename覆盖fallback（[Linux manual](https://man7.org/linux/man-pages/man2/rename.2.html)）。parent fsync、原目录inode/chain和当前core proof后，原Service才能留存publication witness。caller自行move目录不能直接READY；显式原owner reconcile必须重新核原issued material/core seal并fsync。失去COMMIT/publish/fsync返回不当作回滚：保留原INTENT、原stage或published物料及UNKNOWN，不换ID/路径/epoch，不删除tombstone或回退UNBOUND。显式原proof reconcile只可对齐原sealed物料并补非执行READY；历史receipt不能签发Controller/Working/FD能力。原process退出后不能从DTO重建这些内存能力。

手工snapshot/recover/audit及自动maintenance均核两phase原source和实际tip/COUNT；自动维护在同readtxn捕获、writer外完整闭合，坏projection/原事件/缺失域不会清due。实际故障证据含源file/directory swap-read-restore、extra/cache/type/count、竞争目标的内核NOREPLACE不覆盖、rename/fsync/READY COMMIT前后丢返回、最终sourceproof超期和已发布code BOUND冷入口拒绝。

受保护开发期启动API示例（只创建新的私有非执行fixture，不启动worker/daemon；返回路径供核验保留）：

```python
import tempfile
from rlflow.hybrid_fixture_materials import FixtureMaterialBuilder
from rlflow.hybrid_installation_service import FixtureInstallationService

parent = tempfile.mkdtemp(prefix='rlflow-fixture-bootstrap-')
builder = FixtureMaterialBuilder(parent, project_id='isolated_installation')
owner = FixtureInstallationService(builder)
material = builder.prepare()
owner.persist_intent(material)
owner.publish(material)  # READY remains execution_enabled=False/release_enabled=False.
print(builder.root, material.release_path)
```

未来升级必须保留全部历史deny tombstones与前catalog lineage；不得原地改catalog/策略，也不得因root重建/缺marker解除保护。已有old binary/cached process仍须OPS04安全STOP及完整身份核验，此轮不能以“新DB无sessions”证明所有OS进程不存在。

WorkingExecutionPlan后续从已ACQUIRED/已ACK的实际Working slot构造，固定当前HEAD/claim、原Prep/预算/currentGoal/approval/Registry、Controller双期限与actual Kernel hold。旧snapshot plan不能改path冒充working plan；可写路径只能由原批准scope受控映射，不默认授整copy写权限。物料与两次CAS分离，所有execution/release仍false；其它hostpool/UsageOwner/REGISTER/STOP门仍未实现。

## 不宣称

默认source/旧scope未迁移；新私有fixture安装不代表生产部署/既有upgrade或迁移。没有实际WorkingPlan、runtime注册/授权/release、可信usage/退款、共享主机pool或可靠STOP；不是防同UID非合作改源码/任意写的OS安全证明。没有新增browser/NFR06/B1/24hfixture/8hUI证据或完整T12/M1/M0–M5验收。Goal持续活跃。
