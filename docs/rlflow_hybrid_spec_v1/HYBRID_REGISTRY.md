# 可信启动注册表核验（T09 增量，非批准）

Checkpoint26 新增 `rlflow.hybrid_registry.Registry`，只由受保护控制宿主从可信启动配置构造。不能将 HTTP/agent 提交的 JSON 当作 trusted_config，也不能接受调用者给出的 attestation 作为批准证据。当前没有路由、认证桥、执行 adapter 接线、Store 写入或模型调用；完整 T09 与 M1–M5 未完成。

## 冻结配置与内容绑定

构造时 canonical JSON 深拷贝到不可变 bytes，最大256KiB；闭合顶层配置，project_id/data_mode 固定。各 ID catalog 至多128项。工具描述绑定 adapter 与完整 definition；命令描述绑定 tool_id、静态 argv、parameter_schema、network 与 allowed_hosts；未知工具依赖拒绝。参数 schema 仅按 Draft202012 检查结构，不解析远程引用、不执行 argv、不导入 adapter，也不代表已经验证某次命令的参数或可执行性。

数据 catalog 使用 dataset ID、版本 SHA256、允许 purpose、精确 access 与 source 的 adapter/opaque reference；引用不是任意宿主路径。保护评价注册不能授予 training。评价规则定义与 requires_datasets 一起计算版本 hash；注册规则需要数据时，显式 NONE 拒绝；理论规则可以无需注册数据。

runtime_profile、resource_profile 为显式配置对象，不赋予缺省执行能力；project_policy 包含显式 network_access/allowed_hosts 与完整 configuration。Opaque configuration 只参加内容绑定，未知 enforceability 不解释为允许。后续批准/执行必须核验实际隔离和强制能力。

五个 proposal registry_bindings 由服务端计算，规范形式为：

```python
digest([binding_name, [project_id, data_mode], catalog_content])
# dataset_registry_hash 内容为 {datasets: ..., rules: ...}
# 其余分别 tools / commands / runtime_profile / resource_profile
```

空 catalog 亦带 project/mode 与不同域，不跨项目或模式复用。规则 version_hash 使用 `digest(完整注册rule对象)`，不只 hash 说明文字。project_policy 参加整个 config_hash 和 scope_hash，而不是五个字段之一；policy 变化即使不改变五个字段也会改变确认绑定，批准服务必须 fresh resolve 后比较整个 scope。

## 解析与下一批准门

`registry.resolve(proposal1_1)` 复用草案语义边界并校验固定项目/模式、五个内容 hash、全部允许工具/模板、工具依赖与数据版本/purpose/access/规则。联网满足 `command hosts ⊆ proposal hosts ⊆ project policy hosts`；none 不满足联网需求。任何不匹配均拒绝，不修改数据库或申请资源。

返回 detached private data：NOT_EXECUTABLE、project/mode、proposal_hash、config_hash、五个 registry_bindings 与 scope_hash。scope 的规范定义为：

```python
digest(['hybrid.confirmation.scope.v1', digest(完整proposal), digest(完整trusted_config)])
```

绑定整份合同（目标、条件、工具、数据、网络、预算、停止与风险），整份 catalog（包括未选择注册项）及 policy，不能只以 writable_paths 或选中 ID 作为确认 hash。更换 catalog 必须创建新 Registry 并重新确认；修改输入对象、bindings 或返回结果不改变冻结对象。

这是内容确认绑定，不是执行权限。下一 ApprovalService 必须持有自己的固定 AuthStore/Origin/项目/Registry/Store，在实际单写事务边界核验有效 human approver session、CSRF、精确 revision/hash/diff、有效期与当前注册事实，重新计算 binding；不能信 caller 的 Principal、approved_by、config_hash 或 NOT_EXECUTABLE 返回对象。批准事实与命令回执须不可变、撤销另 append；仍等待 lease/STOP/resource/OS gate，不自动 READY。

## 证据边界

Dataset version_hash 只证明匹配可信注册声明，**尚未打开或校验实际数据字节**。Profile hash 只证明配置绑定，**不是 cgroup/只读/硬 token 上限探测结果**。路径仍仅声明，未做 realpath/符号链接/保护控制域隔离；不能据本模块的成功返回运行任何工作。

Root 四模块130passed/3.45s（原96925终态exit0），compileall/diff通过。独立 High 四模块130passed/3.43s（原3366终态exit0），范围无剩余MUST_FIX。全量689/32/1仅绑定 checkpoint25，不把旧全量或旧性能重标为此源码已全测；本次新增独立纯核验模块、既有执行/HTTP/UI/Store入口未变，采用四模块针对性回归。命令/log/source hash见 evidence/checkpoint-26-final-tests.txt。
