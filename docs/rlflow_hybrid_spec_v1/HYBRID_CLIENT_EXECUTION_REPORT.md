# 目标目录的原执行结果报告

Checkpoint74 将原固定 CPU 实验、工程单写结果与未完成验收条件接到 request-only 客户端。报告只读，不接受调用方的 PASS，不创建 reader/owner、不派发、不写 Core，也不提升预算或审批权限。不是原配置 loader、通用 native runtime 或完整 Goal 完成门。

## 接口与行为

```bash
rlflow client execution-report --kind CPU_TRIAL --source cpu_assessment_<original-id>
rlflow client execution-report --kind ENGINEERING --source candidate_output_result_<original-id>
```

对应 `GET /api/v1/projects/{project_id}/execution-report/{kind}/{source_id}`。source ID 必须由用户或可信 operator 明确提供，客户端不扫描目录、推导授权或自动运行。既有普通 bearer 不升级为 request-only；人类仍保留原会话权限。没有注册原 delivery reader 返回409；缺原记录404，来源损坏/绑定或epoch异常503，读取中撤权403。封闭查询/重复安全头保持原规则。

可信安装装配显式传入原 DeliveryEvidenceReader，绑定同项目原 inbox/Auth/Store/Registry/mode/epoch。inspect 在原只读事务及 ReadBudget 中证明原结果、当前合同、原审批与条件；新接口仅投影该已证明 DTO。来源读取、闭合摘要校验、末元数据及授权复核在同一有界任务中完成，复用独立 discovery 读池，不占原直接 STOP 清理槽。waiter取消不会释放仍在运行的读容量。

报告给出原事实、机器结果、配置与原/现合同哈希，机器状态、原始组数、机器验收案例数、条件ID/required/verification hash及真实分母、原缺口。不是完整 proposal 或完整原事实导出；摘要不能本地重算未返回的事实哈希。条件至少1、最多200，至少一个required；CPU缺结果可保留null结果哈希，工程必须原hash。客户端核scope、计数、状态和blocker关系，拒绝机器PASS变成独立Review/条件满足/Goal完成。

`as_of_state_version` 与 `checked_at` 标识原读取快照；末 `check_current` 拒绝版本倒退/epoch异常，不承诺版本未推进，也不证明返回瞬间仍有执行权。`CURRENT_SOURCE_AS_OF` 仅为该快照来源匹配。`current_execution_status=UNKNOWN`、`resource_release_status=NOT_OBSERVED` 始终保持；durable FREE和机器结果不替代当前物理探测。

## 实际验收与剩余缺口

双项目原有限执行已产生 CPU 384点、工程3个worker测试组和21个AST机器案例；目标cwd SDK/CLI读取零Core写入、明确MISSING_CONDITION_EVIDENCE/MISSING_INDEPENDENT_REVIEW，跨项目读取拒绝，随后原直接STOP完成并Pool0。首轮测试错误地期待工程raw21，依原来源纠正为3，不改执行结果。

原来源损坏503、读取中撤权403、缺记录404、两阻塞报告waiter取消后第三429与原独立STOP通过。必要最终回归91pass/1既有warning46.17s。先前实际双项目与codec19pass67.71s，运行输入末仅新增一致性校验和对应负例；最终安装包实证单列于证据，不能将早期测试当全库重跑。CPU nullable/max200正例为合成codec边界，不冒充实际缺结果或200条件执行。

随包skill说明何时读取、来源hash限制、as-of及机器/独立Review区别，由skill-creator作窄更新；没有全局安装。原A01自动自然语言、全Goal/任意树STOP、native/产品Reviewer合同与额度、严格OS委派/quota/invoice、B1/T22/T23与24h/8h/M5仍未完成。下一优先新安装的可信装配/原角色启动链路，让文档用户无需测试模块才能使用既有已交付行为，不新增运行权限。

最终wheel SHA256 `c6cc7df4fc86ffbbee1e09022507f16c474f242d8f8a1ee21204736cc5923bf1`，实际安装后checkout外导入、两完整yaml目标目录console、原CPU/工程执行后报告及原STOP、packagedskill通过。服务器测试装配未成为发行用户启动接口，不能据此关闭T23。命令/失败诊断/终态见 [checkpoint-74-tests.txt](evidence/checkpoint-74-tests.txt)，337最终输入见 [checkpoint-74-inputs.sha256](evidence/checkpoint-74-inputs.sha256)，实际探针见 [checkpoint-74-installed-probe.py](evidence/checkpoint-74-installed-probe.py)。High四项MUST已关闭，无live测试。
