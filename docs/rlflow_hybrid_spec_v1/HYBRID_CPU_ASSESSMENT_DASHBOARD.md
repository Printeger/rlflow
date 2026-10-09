# Checkpoint 52：真实 CPU 研究证据只读 Dashboard

51 已提交 `a3b17ff2cf5cd16e1d865f0703e0509c9f683d44`。本切片把既有默认关闭的 authenticated CPU appraisal API 接入现有 Dashboard，而不增加执行、模型、GPU、候选写或生产迁移权限。

## 交付行为与验收

- 单独 CPU 数值试验面板：执行状态 / 科学有效性 / 假设结论三个独立轴，原 experiment/attempt 与评估记录 ID，不把同一试验的新评估当新试验执行。
- 选取详情显示原 384 点、计数、估计、误差、baseline、来源/输入/程序/evaluator SHA、CPU 和 wall 的原 emit-as-of 范围；以 textContent 显示闭合 DTO，不提供路径或执行按钮。
- 固定三个种子、partial 资源强制、独立评审 NOT_PERFORMED、条件覆盖空、Goal false；当前运行 UNKNOWN、释放 NOT_OBSERVED、成本 UNKNOWN。EXPERIMENT_CURRENT_AS_OF 仅服务器 checked_at 时刻的有限激活，不是浏览器此刻权限。
- 原持久 domain 的非重复版本触发只读刷新；一批最多一页加所选详情，限频一秒。心跳不读、不刷新权限；离线保留 as-of/STALE；来源失败锁止自动读取，手动恢复。
- 完整 principal/authGeneration/project/mode/epoch 和 serial 票据；切身份/项目、logout、401 清空；晚返回不重填原私有内容。旧 stream 错误先检查 generation，不能清掉新 scope。
- 读接口未安装的 404 明示未安装，不等于没有试验。闭合 schema、版本、安全标志、三轴结论、原 evidence 布尔的一致性检查拒绝矛盾结论，不在 JS 冒充 Python evaluator 或重新建立执行权限。

## 实际开发证据

日志在 `audit/hybrid-v1/checkpoint-52-*.log`，最终索引另见 evidence/checkpoint-52-final-tests.txt。

- 纯面板 r1 原 ab34ee exit1：3 pass / 1 fail，dirty 返回 null 而非 boolean；生产精确改 Boolean。仅受影响 durable case r2 原 e49eec exit0 1 pass，其他通过项不重跑。
- 独立只读审查发现 generation 清理位置与结论对应两个 MUST 类别；实码修复。新矛盾 DTO 用例及受影响闭合 validator r3 原 ec0f45 exit0 2 pass / 3 未选用例，不虚称五项新 fresh suite。
- 实际 browser r1 原25466终d85da3 exit1，18.754s：已经过原384样本、指标、三轴和列表刷新，但详情等待直接解析过渡空内容失败；只修新测试等待条件。
- r2 原32528终807a1a exit1，42.953s：详情版本刷新通过后，新夹具关闭 owner 又调用受保护 _issued 被正确拒绝；改关闭前保存的历史 attempt 引用用于旧观察，未放宽生产权限。
- r3 原6369终1bd280 exit0：1 pass，19.803s。实际私有 loopback/Python 原固定 CPU、原 appraisal、冷 Store HTTP、Chrome viewer、持久 domain 刷新原选择、owner 关闭只读和 logout 清理均通过，零非登录/退出写请求，零 pageerror。第二 appraisal 是原试验新评估，未重算 CPU。
- 独立窄静态复查 SHA `8c6bda2caabff97cd009940b95117213aefd6583ba7e7b7bef2969d9a7fea60f` 确认三条结论对应 MUST 关闭；无新写/测试，无重复51后端审查。

必要回归限定 app 接线的既有主 Dashboard 身份/SSE、Hybrid human 权限、固定 CPU Start/STOP 三浏览器链路，串行唯一原53887终da140c exit0：3 pass，60.360s。268最终输入 SHA 全匹配（manifest 327af2341d72dd307b2a362c1663dfda30628cc843836468b01b159eb5cba825），JS syntax/Python compile/pip check/diff check通过；无live测试，无运行中代码变更或并行测试。

## 剩余缺口与下一切片

本切片关闭实际有限研究证据的页面接线，不是完整科研闭环。下一交付真正原证据独立验证／有限决定的持久行为，明确 verifier 身份、原合同绑定和结论作用域；不从自由文本推断条件完成，不把新组件或建议当 Goal 完成。真正工程候选执行、native、严格 OS/network/data/任意树 STOP、供应商 invoice、安装/迁移及24h/8h验收仍待，原权限边界保留。当前没有新增需用户决定的外部阻塞。
