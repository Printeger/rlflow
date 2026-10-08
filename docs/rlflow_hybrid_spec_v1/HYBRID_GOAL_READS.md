# Hybrid 有界读取桥（checkpoint31）

本切片新增真实投影读取及原提交事件证明，不启用执行、lease 或 scheduler。仅显式启用 ControlServices 的项目安装以下路由；默认旧只读应用不安装它们。沿用固定 Store/Auth/project/mode/epoch、Origin 与有限 worker pool。

## HTTP 与权限

`GET /api/v1/projects/{project_id}/goals?after=<opaque goal_ref>&limit=30` 支持项目内 viewer session 或只读 Bearer。唯一可选参数为 after、limit；重复/未知参数拒绝，limit 为 1–50。按主键 keyset 取 limit+1，仅读 Goal/Authority head，不展开 proposal、历史、actor 或 Registry witness。列表 item 含 goal_ref、contract_revision、contract_hash、source_coverage=HEAD_ONLY、execution_enabled=false，以及可空 authority（recorded_state、authority_revision、HEAD_ONLY）。游标只是主键，不授予权限。

`GET /api/v1/projects/{project_id}/goals/{goal_ref}/review` 无 query 参数，要求实际 human Cookie session 且拥有 operator 或 approver 角色。viewer/Bearer 不可读完整 proposal。不存在返回404；源数据损坏返回固定、脱敏503，不把存储错误归为客户端400。每次读前/后及最后一次 DB 核验后重新认证；最终认证核验前已注销/到期则不返回私有 body，不承诺核验后到网络送达期间持有 Auth 锁或撤回已发送字节。

两种响应固定含 schema_version=1.1、project_id、data_mode、store_epoch、as_of_state_version 与 execution_enabled=false。列表另含 items、next_after。review 另含 goal_ref、实际 DRAFT contract、服务器 changes、submitted_by、submitted_at、previous_hash、source_coverage、submitted_state_version 和可空 authority。没有 token、source_command_key、Registry catalog/witness 或数据库/Registry 宿主路径等环境私有信息；proposal 声明的 writable_paths/protected_paths 仅在授权 human review 可见。

review authority 显示 recorded_state、authority_revision、fact_key、source_coverage、approved_contract_revision、approved_proposal_hash、applies_to_current_contract、approved_at、expires_at、lifetime_status、revoked_at、evaluated_at、execution_enabled=false。原批准事实、当前合同适用性与当前时钟期限分开；UNEXPIRED 不表示可执行，撤销也不改写原批准。

## 原事件覆盖，不回填旧数据

新私有 GoalRecord 由服务器持久化可选 source_command_key；proposal/request/旧 hash 与 receipt 协议不变。原核心事件须同时包含完整 record、原 receipt 和该提交 revision 的原 head，其三个完整对象摘要、producer、request hash、accepted version 都匹配。记录 actor、时间、diff、来源指针也在完整摘要内。不能用后来被更新的投影 version 或当前 head 代替原提交证明。

新记录成功核验标 ORIGINAL_EVENT_VERIFIED。没有指针的旧记录不扫描历史或补写，review 标 PARTIAL_NO_SOURCE_POINTER，submitted_state_version=null。安全 audit/snapshot/recover 对所有记录（含旧记录）仍经原事件 callback 核验完整对象；删掉新指针不能降级这些闭合校验。历史恢复不会因当前批准过期而拒绝原合法事实。

每个 GET 的一致只读事务核固定 epoch/注册、实际整数 source version 与 MAX(core seq)。响应是该投影快照，不是逐次全历史/完整 authority chain audit，更不能对同 UID OS 管理者提供防篡改沙箱。ORIGINAL_EVENT_VERIFIED 仅表示所读原事件对象证明；HEAD_ONLY 明确不作这种证明。另有最后的新事务核 epoch 与版本未倒退，不将旧响应版本说成最新。

## 有界资源

列表源预算256KiB、输出64KiB；review 与 prepare 共用 ReadBudget（实际读字节、结构节点、展开逻辑字节/节点分别有限，默认16MiB），review 输出2MiB。SQL 在传输前限制单行/blob长度；严格 JSON 拒重复键与非有限数，blob 核 SHA。缓存命中仍收费完整展开成本，防少量共享 blob 指针造成巨大逻辑展开；literal 数据不误解 marker-like 键。超限 fail closed，不读 Registry witness 给网页。

prepare 同预算核实际 head schema、head==draft_head(proposal)，再核新记录原来源；READY 或格式正确但 hash 不匹配的 stored head 返回503。手动/周期 snapshot 与 recovery 也核完整原提交，周期失败保留 due 与旧 snapshot，不冒充成功维护。

## 证据边界

测试涵盖权限分离、keyset、旧记录部分覆盖、多 revision 原 head、snapshot 篡改、展开预算、损坏源503、注销后响应拒绝、期限/新合同/撤销显示，以及保护配置加载器→实际 owned loopback TCP→提交/列表/private review→正常关闭。后者不是 CLI main 子进程启动、阻塞 writer 下线、浏览器确认交互、性能/B1 或真实模型执行证明。完整确认 UI、公开的脱敏合同细节/SSE 桥、lease/STOP/runtime、工程/科研闭环和长期验收仍待交付。
