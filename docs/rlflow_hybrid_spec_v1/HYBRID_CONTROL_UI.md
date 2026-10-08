# 本地不可执行事实控制 UI（checkpoint32）

在既有 Dashboard 中增量接入 [Hybrid 读取桥](HYBRID_GOAL_READS.md) 与 [控制 API](HYBRID_CONTROL_API.md)，没有托管网站、scheduler、lease 或模型执行。Sites 技能采用 local-only 工作流，未注册、上传或发布。旧1.0配置/无 ControlServices 项目仍只读，接口404不隐式初始化 Store。

## 操作流程

按 [TRUSTED_WEB_CONFIG.md](TRUSTED_WEB_CONFIG.md) 显式配置1.1、角色与 Registry，按 [LOCAL_WEB.md](LOCAL_WEB.md) 启动本地服务并登录。viewer 仅见当前页 head 摘要（HEAD_ONLY），不可打开完整私有合同。

operator 可在“完整显式1.1 proposal JSON”粘贴与本项目/模式一致的 proposal，明确点击“提交不可执行 DRAFT”。不自动填政策、目录、数据绑定、身份或批准，不将 operator 升级 approver。服务器提交 DRAFT 负责完整 schema/CAS；prepare/approval 才核实际 Registry，不把 DRAFT 声明当注册证明。新的 revision 使用输入 revision-1，global CAS 绑定已读 core source version。

human operator 或 approver 可点击 head 或键盘 Enter 私有审阅完整 proposal、服务器 diff、来源覆盖与原提交版本。大 JSON 使用有限滚动块与 textContent，不解释 HTML，不存 localStorage/sessionStorage。旧无来源指针显示 PARTIAL_NO_SOURCE_POINTER，不能用列表 HEAD_ONLY 证明完整来源。超过 JavaScript safe integer 范围的合法服务端预算/变化不能精确展示，审阅/确认 fail closed，不显示舍入数字并据此批准。

approver 输入批准事实 TTL（1–86400秒），点击“准备精确确认视图”。页面显示实际 server proposal、changes、Registry binding、scope/config/view hash、nonce 与尚未验证的实际数据/OS限制。确认必须匹配当前审阅的 goal/revision/proposal hash/完整 proposal/diff/authority revision/epoch；不得将编辑器代替服务器视图。勾选明确同意后点击“记录条件批准”，只原样提交 nonce confirmation。结果为 LEASE_VALIDATION_PENDING，execution_enabled=false，不表示 READY、启动或完整执行授权。nonce 的真实120秒上界和 session 期限由服务器负责，UI 从请求发出起110秒保守拒绝，不自动续期。

撤销绑定当前审阅的 approval key、authority revision 与全局 as-of 版本，必须填写原因并明确点击。原批准事实、当前有效期、新合同适用性与撤销分开显示；撤销不销毁历史，EXPIRED/UNEXPIRED 不表示执行资格。

列表按需 keyset 翻页/手动刷新，不无限增长；成功写入后重新读取 head。原 public SSE、日志与资源流程保留，较新 domain source version 使准备好的 nonce 失效；heartbeat/telemetry 不续期。此切片不是完整公开脱敏合同详情/条件矩阵/Hybrid领域SSE映射或 STOP执行 UI，完整实时 Goal/预算/实验链仍待整合。

## 认证、意图与不确定提交

登录开始、身份/项目/epoch/快照切换、注销、认证失效清除私有 DOM、editor、review、nonce 与本地 pending body；独立 ticket 拒绝迟到响应。全局 request 的401副作用也核发出时 auth 与 observation generation，旧身份的迟到401不能注销新身份。仅公共最后快照可按既有行为保留。

输入 JSON 拒 decoded duplicate keys、非有限数、unsafe整数与过深结构；严格合法原 proposal 字节嵌入完整256KiB命令包络，避免 parse/stringify 消除歧义、舍入或改变数字拼写。客户端不声称 JSON.stringify 与 Python canonical hash 等价。

每次明确写入只保留一个内存中的固定 scope/action/body bytes/idempotency key。网络丢失、5xx、无效成功响应标“未确认”，不假设回滚。只有手动重试原 bytes/原 key；不自动新键、改 expected 或重放。400/409/422拒绝后停止，必须重新读取/审阅。清除本地意图不取消服务器提交；换身份后的丢弃也不能撤销在途服务器操作。已收回执显示原 accepted version 与事实，不假装当前状态，随后重新读 head。

## 验证范围

纯状态与异步测试覆盖 closed/scope/safe integer、合同/diff/nonce绑定、迟到 review/prepare/POST、输入歧义拒绝、编辑/刷新/时限/版本变化失效、固定重试、409停止和私有清理。

实际 owned loopback server + sandbox Chrome 覆盖 viewer/operator/approver 分离、原持久 DRAFT/条件批准/撤销、服务器已commit但浏览器丢response后的同键 duplicate receipt、旧身份 held401、新登录私有body不受影响、XSS、键盘、390px布局无横向溢出、TTL修改、合法服务端int64拒绝批准和正常关闭；每次 audit 无 task/session 执行。它是明确隔离 fixture，不是实际用户批准当前开发Goal、供应商模型、实际lease/STOP或工程科研执行证明。

原 browser screenshot 使用固定名的可覆写预览；本轮早期r2/r3重跑已更新这些 PNG，旧 hash/文字原文保留但不复用为新源码视觉证据。现改每run独占 artifacts/run-* 目录，不覆盖后续预览；原测试日志与源码SHA独立归档。最终测试终态与SHA见 evidence/checkpoint-32-final-tests.txt；完整 M1/B1/NFR06/24h/8h 与 M0–M5 Goal 未通过。
