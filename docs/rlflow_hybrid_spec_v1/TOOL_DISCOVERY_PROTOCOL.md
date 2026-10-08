# 可信工具事实发现协议（T05，当前private源）

2026-10-08。实现源：tool_journal.py、worker.prepare、persistent_cpu_exec。公开collector/pending ingestion尚未实现；这不是公开API或放行授权合同。

## 已实现的写入顺序

新bound命令目录及其commands/audit父目录先fsync，然后intent.json fsync并同步命令目录；在可信audit parent的tool-registers.jsonl追加REGISTER、fsync文件与parent，之后才可能调用CPU。result与private return fact延续checkpoint08顺序。REGISTER表示已登记待检查，不证明工具已启动；失败不会调用CPU。完整命令缓存回放不重复执行或重复登记。旧legacy/unregistered cached目录不隐式backfill，不借历史目录名字证明覆盖。

每条闭合REGISTER含schema_version/kind、context hash作为epoch、连续ordinal、previous_sha256、command_digest、intent_sha256、闭合context、nullable launch_witness、record_sha256。command_digest沿用现有commands目录ID映射；只作固定已知路径的key，不接收任意path。记录没有原始command ID、命令、输出、路径、模型消息或发生时间。单条最多4096 bytes，整个source最多64MiB；达到上限拒绝后续调用，不滚动删除历史或伪称覆盖完整。

登记当时可从worker传入的可信launch directory捕获已经存在的release/model-release/ACK摘要，有限检查session/generation/request/candidate与ACK/CLI identity关联。该witness不是完整验证，也不授权执行；collector仍需对照DB release、完整request、实际permission、startup proof及exact hashes。没有事实或读取失败时witness为null。之后出现release不能升级这条旧REGISTER。未经核验的记录保持private/unverified，不产生public STARTED/RUNNING。

## 已实现的有界读取

read_page只接受可信目录fd与固定文件名，NOFOLLOW/NONBLOCK、regular-file/容量检查；每次1–64条（默认32），readline最多4097 bytes，最多一个4097-byte检查点读取。无需glob、listdir或全历史扫描。

游标绑定context epoch、device/inode、offset、ordinal、record_sha256。非初始页重读上次结束的一个完整record，核验该checkpoint；后续严格ordinal+previous digest。拒绝替换、截断、错epoch、破损摘要、额外字段、超长record或链缺口，不自动offset=0。文件末尾partial record保持原offset，报告incomplete_tail/has_more；writer对partial tail拒绝，不在该路径自动truncate。可信修复/rollover未来需独立恢复合同。

此checkpoint witness只检测边界及后续链，不宣称每轮核验整个历史prefix；同权限恶意trusted writer可以改写journal和DB，需依赖已存在OS角色隔离及后续控制代码发布边界。恢复复制导致inode改变必须显式处理，不能静默归零。

## 后续collector必需合同

- 在core中添加indexed pending与receipt语义digest，不能无限累加session内map或每轮glob目录。
- 同一core事务提交journal offset/checkpoint、pending/receipt变更、观察event与public log；同key同digest重放，相同key不同digest拒绝，不能只依赖Store._existing的类型/object ID比较。
- 新REGISTER登记已知路径后，按分页且公平轮转的bounded pending query复验。没有RETURN通知也能发现result/fact；result先提交而fact缺失时只能确定性补证，绝不重跑CPU。
- 捕获nonnull witness仍须独立完整验证；null/malformed/事后release不得变成已授权执行事实。限定source/artifact目录，disk raw symlink模式未经验证明确unsupported。
- 覆盖范围与损坏源状态须持久化；Web GET不读取私有journal、修复源或创建表。公开材料只来自core已验证事务投影。
- 扩展closed tool observation/public log schema与builder，不把未知payload塞入仅理解legacy upsert/removed的CORE_STATUS模板。

下一阶段验收需覆盖core commit前后崩溃、语义duplicate/conflict、pending公平性和长期UNKNOWN、坏源隔离、跨generation/release/permission、原始文本不入公开body，以及真实model-free command→core→SSE→UI。资源telemetry、逐工具STOP授权边界、完整M1–M5另行保留。
