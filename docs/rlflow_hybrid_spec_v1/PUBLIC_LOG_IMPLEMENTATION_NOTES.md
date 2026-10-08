# 公共日志后续实现边界

2026-10-08，checkpoint06已实现CORE_STATUS同事务存储、闭合LogSummary/Body/Page与scoped API，checkpoint07已接入日志UI。以下方案保留设计来源，不本身作为验收；公开工具metadata/资源与完整日志仍待完成。

## 已核实的源风险

独立High只读复核现有worker/engine/cpu工具源：`events.jsonl`包含reasoning/agent_message/MCP args/results，stderr/supervisor有trace与私有路径，commands/intent/result包含command、stdout/stderr、cwd/checkpoint。public_text正则是辅助脱敏，不是将整段原文变成可公开内容的许可证。禁止Web请求直接tail这些文件。

原CPU命令intent/result缺session/generation/request哈希，不能凭目录名字认归属。checkpoint08的新worker为recovery_protocol>=2的MCP config加入闭合tool_context，含session/generation/request_sha256/candidate_sha256；新bound intent还绑定scratch/memory和既有role/candidate/permissions。正常返回后产生私有return-observation.json固定状态及intent/result摘要，不复制命令/输出/路径，不证明STARTED/RUNNING、release或授权。旧config不生成bound事实，历史不回填。

工具metadata collector仍必须先验证trusted request/release/DB session及startup proof，固定 `commands/<sha(command_id)>`映射并核对role/candidate/permissions与command/argv/cwd/checkpoint来源绑定；tool_context/hash本身不能当放行证明。resource.disk模式可能将role日志symlink到raw；初版拒绝follow并明确UNAVAILABLE，或只通过已校验resource record定位批准raw根，不把symlink当授权。逐工具STOP/授权marker属于受控runtime后续，当前private return记录不实现或取代该边界。

## 下一候选切片

先接入明确标为 `CORE_STATUS` 的真实状态日志：来源为已经校验、同事务提交的公共domain envelope，不读取raw模型文件；正文仅从kind/opaque ID/version/有限状态/seq生成固定模板，禁止复制description/reason/source任意文本。这是真正的core状态日志，不是stdout/stderr/工具日志替代，不宣称完整T05完成。

在同库增加append-only public-log summary/body与object-ref索引，保持事件、projection、日志同事务；log_id与domain event lineage绑定，body有界、摘要与正文分离。reader和lazy detail只查询已持久化的public材料，BEGIN内再次绑定project/data_mode/epoch/digest，绝不读取任意path。分页用索引keyset，过滤task/execution/experiment/severity不能扫整个事件历史，元数据和正文都要闭合schema、上限、恢复时floor/epoch规则。准备/迁移只能trusted显式CLI执行，Web GET不能创建表、回填或启动Store。

首次升级对历史日志必须明确策略：没有日志不冒充没有业务事件；如果从enable时开启则公开coverage开始点，后续离线backfill分批且不得修改原domain字节。未建立合同前不能偷偷让新核心写入在缺表旧库失败，不能隐式Web迁移。

测试至少包含同事务故障回滚/幂等、severity/ref分页与query plan、缺正文/哈希破损/epoch拒绝、跨项目源替换、私有reasoning/HTML/秘密/command/env完全不入固定正文、首次启用coverage、公共lazy详情/UI筛选与reading anchor、真实model-free核心事件到浏览器日志。随后继续工具metadata、资源telemetry与真实来源端到端，保留完整M1缺口。

独立High最终补充：每个entry绑定object kind/id/version、template_version并有唯一约束；未核实前后状态差异只能称“状态观测”，不能模板声称发生转换。日志pagination固定首次请求high-water mark并绑定epoch/筛选，日志游标不得混为SSE消费cursor。新LogSummary/LogBody/LogPage闭合合同，正文和entry-ref只指向同项目public event。generation/request仅取同次提交可信session元数据，没有request时明确无绑定；CORE_STATUS不重读启动文件、不证明CLI模型工具运行。UI必须区分CORE_STATUS可用、TOOL_METADATA待接入、raw logs PRIVATE_ONLY。
