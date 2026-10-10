# 安装态固定工程与实验执行

## 新原生诊断入口（Checkpoint82 安装态已实测）

在同样的全新隔离私有父目录，可运行 `python -m rlflow.isolated_native_diagnostic --parent "$isolated_parent" --approve-isolated-local-diagnostic`。命令标志只允许准备；展示 proposal 后必须输入本次精确 `APPROVE <scope_hash>`。不要在生产目录运行，不接受旧 lease/PID/任意程序。固定本机原生 ELF 必须满足原路径/root-owned/hash 身份规则，Linux x86_64 必须实际支持 seccomp 与 Landlock，缺能力直接拒绝。

此入口通过原 SDK 启动真实 native CLI，但使用无凭据、零模型/GPU额度、本地不生成模型的 HTTP 接收器。原 stdout 与沙箱 receipt 分离，随后原 STOP/reap/FD关闭/PoolFREE并原账本冷读。token/cost UNKNOWN，网络 `PARTIAL`；不是产品 Reviewer、真实模型执行或通用 native RUN。82 当前 sdist→wheel→私有 site 共346payload与源码逐字节相等；checkout 外安装态 public CLI、原进程 STOP/FREE 与 SDK 退出后的独立冷读均已实测。精确 stdin 使用 synthetic fixture 确认，不冒称真人模型授权；证据见 evidence/checkpoint-82-installed-output.txt、checkpoint-82-tests.txt。原全量4失败与后续必要受影响复验分别保存，未把全库结果重标全绿。

本入口让安装后的 rlflow 用原 SDK 建立两个全新隔离 fixture 项目，经分别确认原批准范围，运行原固定 CPU 实验与加法修补，通过真实 HTTP 和已安装 console 读取结果，再调用原有限全集 STOP。它不导入仓库测试模块，不伪造时钟、版本或模型目录，也不启动 Codex 模型执行。

## 安装与运行

使用 Python 3.12 和 pyproject 中的固定依赖，在新的隔离环境安装发行 wheel。Codex CLI 必须已是原支持的 0.161.0，本地真实 models_cache.json 须声明示例准备策略 gpt-6.1-sol/medium。这里只读取该元数据，原 adapter 只执行 --version；缺失、版本不符或时限过期会拒绝，不安装/登录账号、不调用 exec、doctor、census 或外部服务。

```bash
python3.12 -m venv /chosen/new/venv
/chosen/new/venv/bin/python -m pip install /path/to/rlflow_standalone-0.2.0-py3-none-any.whl
isolated_parent=$(mktemp -d /tmp/rlflow-isolated-XXXXXX)
/chosen/new/venv/bin/python -m rlflow.isolated_finite_example \
  --parent "$isolated_parent" --approve-isolated-fixed-fixture
```

两个项目都显示完整 proposal、原 approval scope hash 和本次明确请求的 300 秒批准期限。逐个检查后输入对应的 `APPROVE sha256:...`。命令标志仅允许准备一次性 fixture，不代替这两个原 scope 确认；输入不匹配、确认过期或缺权限均拒绝执行。该期限来自这次新提案的原 300 秒 wall budget，不续期任何已有批准，也不替换原 AuthStore 或 request-only token 时限。请不要在生产或既有业务项目父目录运行。

所有新的 Store、Pool 与材料均在原创建的私有随机子目录中；入口不接受历史 lease、进程 PID、JSON capability、已有项目根或任意命令。退出后保留隔离目录与账本供检查，不自动迁移、删除或重新采纳它们。这个示例不是通用 Dashboard 部署器：内部原 human fixture 凭据随机产生且不输出，scope 确认走原 SDK；实际 RUN、结果及 STOP 使用原 HTTP/console。生产角色装配仍使用 [可信 Core SDK 说明](HYBRID_CORE_HOST.md)。

## 实际执行与收尾

两个原 fixture 安装和昂贵准备先完成，再创建短生命周期 Controller、Workspace 和 Pool claim，使用原默认 UTC/monotonic 时钟。Controller/Workspace/Pool 原上限保持 60 秒；原 observation 与登记 TTL 一致，不以冻结时钟或自动续租绕过期限。

每个项目使用同一原 AuthStore、原 FixtureInstallation/WorkingPlan/Registry、同一主机 Pool 和精确注册的固定程序。CPU 实验独立核对 384 个原始坐标；工程 worker 提出固定修补，由原 Core 在 worker STOP 后应用，机器 AST 核对 21 项。工程原 source 保持 BEFORE，working copy 为 AFTER。选择结果按原 recorded_at_state_version，而非 hash 顺序；原 console 报告必须明确 CPU MACHINE_VERIFIED 和工程 MACHINE_ACCEPTED_PENDING_REVIEW。

原有限全集 STOP 的响应与物理证据分别校验：每个原 Popen 的 returncode 已存在，不用 poll 来补做 reap；全部 source FD/pidfd、Pool slot FD、工程输入和候选写 FD 已关闭，Pool 占槽为零。关闭路径先对所有原 unit latch，再独立尝试 server drain、每个 Runtime 的 normal/safety、各 working owner 和 Pool。单个异常不跳过其他项目；错误最终报告 UNKNOWN，安全关闭不是退款，也不能伪造 FREE。HTTP 返回 202 本身不是 worker 或机器验收通过证明。

## 发行与验收范围

wheel 保留原完整控制发行域：rlflow、schemas、roles、tests，以及 model_policy.yaml、bootstrap.py、pyproject.toml、requirements.lock。测试文件只作为原封存输入，不在消费者中导入。build_support 仅在构建时复制四个顶层原文件；MANIFEST.in 同时保证源码发行能构建 wheel。原封闭 inventory、策略替换、校验规则和运行批准层没有简化。

安装验证使用单个新的独立 target/site 与现有固定依赖，支持该隔离组合；不推广为任意混装 system site-packages、全新依赖解析或完整发行认证。实际执行命令、所有开发失败、最终 wheel 身份和终态见 [验收记录](evidence/checkpoint-76-tests.txt)。未修改的 UI、原 Runtime 与 STOP 审查和已通过证据复用，不宣称新全库或新浏览器验收。

机器结果仍是 PENDING_REVIEW，条件证据不自动满足，费用没有 provider invoice 时保持 UNKNOWN。原模型/GPU预算为零，只有固定 model-free 程序；这不是 provider 零费用账单证明。原严格 cgroup/quota、native 产品执行、独立产品 Reviewer、B1、24h/8h、异常恢复及完整 T22/T23/M0–M5 验收仍保留。下一切片应验证安装态关闭后的可信历史读取、异常状态和不重复执行，不凭旧记录重建运行权限。
