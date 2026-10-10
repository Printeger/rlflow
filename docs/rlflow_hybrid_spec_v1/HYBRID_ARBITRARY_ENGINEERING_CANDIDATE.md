# 任意文本补丁与受管候选验收

96 交付真实行为而非新的固定答案：`hybrid_engineering_candidate.transform` 消费有限文本快照、批准文件清单及任意替换/新增/删除，产出 canonical 不可变候选；`verification_spec` 把该候选和外部冻结验收脚本封入已有配置 CPU spec。实际 Core 原批准→Pool→受管任务→另一个隔离 Python 子进程执行候选/验收→原结果→完整 STOP/SETTLED/FREE 已验证。没有修改旧 fixed add、诊断或 CPU 授权，没有在控制进程 `exec` 候选，没有写原项目。

## 接口和授权位置

`transform(files, patch, allowed_paths=...)`：patch 只含 `base_sha256`、`edits`；每个 edit 只含 `path`、`before_sha256`、`after`。修改/删除要求原 UTF-8 bytes 的 SHA256，新增要求 before null，删除 after null。基线哈希、允许路径、重复项、隐藏/绝对/穿越路径、文件/目录碰撞均拒绝；最长路径 200、32 files、原/新文本总量各 49152 bytes。它不解析或执行 shell/diff，不接受外部磁盘路径。

`Candidate` 的原始 bytes 与 output hash 校验、canonical 检查和副本返回防止调用者修改输入/取回值后改变既定候选。它明确是数据，不是模型 receipt；自行构造 dataclass 不产生权限。

`verification_spec(candidate, checks=..., stdout=..., seconds=..., limits=...)`：checks 最多 8192 UTF-8 bytes，候选、checks、验收规则和（三项声明）候选 hash 随完整 spec 审批绑定；改任一项要求新的原批准/预算/grant。checks/rule 必须来自外部验收合同，不能由 Engineer 的 patch 自选。将 spec 交给原 configured CPU 路径才能执行，函数本身不启动进程。现有单核、memory/pids、wall、network/GPU denied 和真实 scope STOP 保持；磁盘硬 quota 仍未证明。

候选物化仅发生在受管任务的私有 WORK/candidate 中；模型字节可含任意 Python/文本，不在父 Core 执行。执行子进程没有控制/审批能力。正例自然返回，非零子进程由包装层明确抛异常，保留原任务失败标准。原项目不会被 inplace 改写；真实完成后的受保护晋升/Working writer-CAS 仍未接线。

## 实际证据与限制

证据 `evidence/checkpoint-96-arbitrary-candidate/`：正例源 pytest779，任意 `package/normalize.py` 替换后实际导入/多输入检查、settings 原样；原 result `SUCCEEDED/wait=0` 与机器 PASS。负例源 pytest780，打印匹配 stdout 后断言失败；原 result `NONZERO_EXIT/wait=32000`、机器 FAIL。两次原 STOP 全 FD 关闭、SETTLED、Pool0。它们是明确合成的开发集成 fixture，不是用户要求的首个非预设真实模型工程任务。

checks 和候选仍共享验收子进程环境。恶意代码可主动退出、打印结果或干预 Python 测试语义，机器 PASS 不是抗恶意测试证明；必须有真实只读独立 Reviewer 消费原候选和原测试证据。现结果仍 `independent_review_status=NOT_PROVEN`、`condition_evidence=false`，不升级为 PASS 条件。受管物化工作目录不是已晋升的不可变项目副本；Reviewer 应读原 canonical 候选，不采信可变工作目录。

尚缺：真实 Engineer source/授权与用量结算、最终写门及候选晋升、真实独立 Evaluator、原条件 publisher/CAS/接续、安装态首个非预设任务。96 只关闭固定 AFTER/控制进程 exec 无法承接任意候选验收的直接缺口；不宣称完整自主工程/科研、通用大仓库验证或实机长跑准入。集中资源合同未答，不调用模型/GPU，不改 instinctRL/生产状态。
