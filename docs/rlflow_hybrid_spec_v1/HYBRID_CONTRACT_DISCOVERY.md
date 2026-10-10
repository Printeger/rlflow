# 原注册提案合同发现（Checkpoint73）

## 交付与验收

目标项目可使用原 `examples/project.example.yaml` 的完整闭合静态 profile，保留旧三字段 profile。客户端仅提取项目 ID、loopback origin 和 mode；项目根须匹配 cwd，state_dir 在工作区外。配置递归拒绝重复键、credential 字段、aliases、过深/过多节点和未知结构。运行器、模型、资源额度、policy、retention 仍是非权威元数据，不创建 Store、读取数据目录、重置预算或配置可信执行服务。

`rlflow client describe` 调用认证的 `GET /api/v1/projects/{project_id}/proposal-contract`，从原 ApprovalService 的唯一 Registry、原 Store/mode/epoch 和原 Auth 读取并末次复核。输出原配置 hash、五组 bindings、tool/command ID、安全参数结构、dataset用途/访问/hash、evaluation规则hash、network边界与随包Goal1.1 schema/hash。目录无执行权限；它不是批准、资源委派或自动生成用户需求。

只公开结构参数 schema：type、properties、required、additionalProperties、items、min/maxItems、minimum/maximum、min/maxLength、uniqueItems。任何不支持关键字（包括注释、default/example、$ref、enum/const/pattern）整体返回409 UNSUPPORTED_CAPABILITY，不联网、不静默改写执行合同。opaque argv、数据位置、runtime/resource配置和definition不返回。支持更广 schema 是剩余缺口，不以调整既有 Registry 校验绕过。

读池独立且最多2个真实作业；HTTP waiter取消不释放尚在运行的容量。目录读不依赖 inbox 文件健康，不占原 STOP 执行槽。晚撤权、原registry/epoch改变、实际读取raw被替换均拒绝返回；返回schema与缓存深拷贝隔离。完整配置mode不匹配在POST前拒绝；旧flat行为保持。

实际完整配置→describe→原schema验证用户显式Goal1.1→Agent建议→human原Draft→report证明 Core恰好一个未批准不可执行DRAFT，无任务/worker/model/approval。实际两个阻塞目录读取时第三429，取消waiter容量仍保留，两个原有限scope直接STOP完成并Pool0。这是route coroutine取消证明，不是浏览器TCP断连或任意树/整个GoalSTOP证明。

## 证据与失败

最终受影响四module67pass + 单项fixture method修后1pass合成证据；不是一次68全绿。两个探索失败均为新增测试接线：成功dict被当HTTP响应、SDK认证method误用GET；分别仅修测试并定向复验，未原样重复。High来源闭包与缓存污染两MUST关闭，无剩余MUST。未变UI及Checkpoint72运行CPU清理证据复用，不另跑。

离线wheel SHA256 `e16140b61761777d13d3ee5fcd0d2c1c7657356c5aecf45b45467a446b01ff28` 实际安装console、checkout外导入、完整配置发现至原humanDRAFT和report、packagedskill通过。skill-creator使随包指引明确先describe、目录不授权和不支持schema拒绝；未全局安装。记录见 [checkpoint-73-tests.txt](evidence/checkpoint-73-tests.txt)，333最终输入见 [checkpoint-73-inputs.sha256](evidence/checkpoint-73-inputs.sha256)。这是最终身份记录而非全输入事前冻结；不称新全库/T23完整验收。

## 剩余缺口与下一项

非完整runtime配置loader、任意schema、自然语言自动调用/全局skill、整个Goal/任意树STOP、native产品Reviewer或完整M0–M5验收。原审批、模型预算、GPU/生产状态及OS委派边界不变。

下一74先让目标cwd报告原有限执行能力与缺失可信gate，区分DRAFT、不可执行和具体缺口；仅使用原注册来源，不从YAML推导权限。不凭目录绿色宣布可RUN，实际runtime授权与严格OS/Reviewer依赖仍保持原缺口。
