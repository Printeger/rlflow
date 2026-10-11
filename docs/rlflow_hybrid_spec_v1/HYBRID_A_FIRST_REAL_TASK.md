# 首个真实仓库工程任务：Dashboard token 输入拒绝

本任务不是固定加法/π/parser 演示，也没有预置修复。来源是本仓库 `761862fab6ef0cbbc403da8f9799371dc8511e6f` 的实际 `rlflow/web_auth.py`；文件与只读 `rlflow/__init__.py` 的精确 SHA-256、任务文本、外部 checks 哈希和机器范围位于 [任务输入](/home/mint/rl_dev/rlflow_standalone/validation/a_dashboard_auth_task.json)。该文件是非权威输入，`execution_consent=UNAPPROVED`，不是完整 Goal proposal、Registry 或批准事实。

实际发现：`AuthStore.resolve('a'*20 + chr(0xd800), 'bearer')` 在 `_key` 的 UTF-8 编码抛 `UnicodeEncodeError`，没有返回拒绝结果。只读复现 exit1；未修改源码。这里证明 Python API 缺陷，不声称真实 HTTP 可以传入此字符。

Engineer 的实际任务是修复 malformed bearer token 拒绝行为，同时保留同一 Store 中合法 bearer/session/request token、角色/项目、用途隔离、撤销与过期行为；不得改外部 checks、阈值或源码来源。唯一允许候选写路径 `rlflow/web_auth.py`。Engineer 必须自行形成实际 patch，不能把开发期诊断或测试替作其结果。

## 外部验收与实际基线

[外部 checks](/home/mint/rl_dev/rlflow_standalone/validation/a_dashboard_auth_checks.py) 从操作方输入冻结，不放入 Engineer 可写文件。现有 JSON_METRICS_RANGE 支持配置，当前固定规则：`cases=27, passed=27, failed=0, stderr_empty=true`，managed CPU 10s；不得由模型减分母或改范围。

每次 malformed 输入后检查原合法 bearer/request/session 仍返回同 Access，roles/projects 保持。独立审查发现初版只在输入前检查存活，清空所有会话也可过关，已修；该清空实现的反例被外部规则拒绝。此反例不是模拟 Engineer 成功，也不证明对恶意候选的全面隔离。

实际原文件在现有受管 CPU 中运行，最新测试从 JSON 读取 checks 与规则：`cases=27, passed=25, failed=2`、进程 SUCCEEDED、机器验收 FAIL、条件证据不发行；完整 STOP、SETTLED、Pool0、FD 全关闭、audit=replay。执行两项失败由 surrogate 引起，合法行为基线其余通过。没有为了获得 PASS 实现修复或改产品。原源码 hash 在测试前后未变。

本轮必要原始证据见 [基线证据](evidence/a-real-task-baseline-20261011.txt)。末 actual JSON 接线复验 1 passed / 2 deselected / 21.00s；纯冻结协议与反清空验收 2 passed / 1 deselected / 0.26s。历史17项初版与27项修复版结果原样披露，不相加作资格，也不重复原 A 条件/接续全链。

## 条件、接续和统一交付要求

原批准必须包含两项 required 条件：实际受管 CPU 原规则 PASS；不同原模型会话的只读 Reviewer ACCEPT，检查同候选、上述行为及未解决 MUST。完整 condition 内容/hash→ORIGINAL_CPU_CHECKS_V1、ORIGINAL_INDEPENDENT_REVIEW_V1 进入原 spec；旧批准不得升级。Source、原可信 usage、完整 STOP、三父原事件和当前 A 窗口由现有 protected APIs 验证。

明确一次接续需求已放入任务输入：接纳后为同模块 `resolve` 补齐用途/拒绝结果/保留会话的文档，不改变行为或扩展功能。接续只是一次原任务运行；没有第二次 CPU/Reviewer/条件 CAS 时不得宣称第二任务已接纳。

最终交付包必须关联：原仓库来源与任务、Engineer 原会话/用量/实际修改、CPU 实测与完整 STOP、不同 Reviewer 原会话/评审、原三父条件接纳、明确接续原会话/结果，且标明剩余缺口。开发期独立审查不是产品 Reviewer。

## 当前最小剩余

1. 将冻结任务来源及外部规则接入真实 fresh-live 安装/原批准材料和有限总入口，统一输出原事实交付包；不凭此 task JSON 或调用方 DATA 发运行权。
2. 按已提出的小额 A 合同取得批准后，运行首个真实 Engineer→CPU→Reviewer→条件接纳→接续；若 FAIL/REVISE 明确未接纳，不自动修复/重复调用。
3. 用实际结果核对任务修改、测试、独立评审、接纳和接续，不以准备组件或测试数宣布完成。

首任务状态仍 NOT_EXECUTED：当前修改、真实模型评审、条件接纳、接续均无实际任务证据。小额 A 合同未批准只阻实际模型调用，不阻本地实现；GPU/B/C/instinctRL HOLD 和完整科研/长跑目标保持。其他恢复增强后置。
