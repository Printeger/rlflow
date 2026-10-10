# 可信 Core 安装启动与重启

Checkpoint 75 交付原 Core 的安装态宿主入口：可信操作者显式登记已有项目和原角色后，目标 cwd 的 Agent 只提交建议，人类通过原 HTTP 登录接纳为未批准 DRAFT。正常关闭并用原登记重启后，原 ADOPTED 回执和 Core 版本保持不变，旧 token 失效。服务器与实际 console 均来自独立 wheel，不导入测试模块。

## 交付与使用

安装 rlflow wheel 及 pyproject 中固定依赖后，由可信宿主代码调用原 SDK；该入口不是新的 JSON 配置加载器或 serve CLI。项目仓库中的 project.yaml 只供 client 定位和校验项目，不提供宿主路径、凭据、角色或执行权。

```python
from rlflow.hybrid_core_host import CoreRegistration, create_core_host
from rlflow.web_auth import AuthStore, Credential, Principal

# existing_root、original_epoch、registered_registry 与口令由可信操作者提供。
# 根目录必须是同用户的既有规范绝对路径，根及 runtime 为 0700。
registration = CoreRegistration(
    existing_root, project_id, data_mode, original_epoch, registered_registry)
credential = Credential.create(
    Principal(human_id, 'human', {'operator'}, {project_id}), passphrase)
auth = AuthStore([credential])
app = create_core_host([registration], auth, origin='http://127.0.0.1:8765')
# 使用启用 lifespan 的原 uvicorn 启动 app；不要共享到 fork 后子进程。
# Agent 通过原 auth.issue_request_token 获取独立 request-only token；
# 原 AuthStore 限时约束不变，token 不写入仓库或命令行。
```

操作者须另行显式准备自己的隔离项目。serve 只使用原 Store.attach_existing，不调用 Store 初始化、恢复、DDL 或观察启用，不迁移生产状态。登记需要既有原 observation metadata；fixture/live、project、epoch 和原 Registry 范围必须精确一致。

最多三个项目先完成全部来源预检，再建立原 DraftService、ApprovalService 和 AgentRequestService。只接受原 Goal/Authority 对象及封闭合法空 marker，拒绝旧任务、执行、资源等领域事实，即使它们自称 FREE；不会从历史记录采纳进程、lease 或退还预算。新入口没有 finite/execution/report 服务；不得用 74 的安装 console 结果推断这个 Core-only 入口能启动有限执行。

## 生命周期验收

每个原根目录独立实例锁按稳定排序获取，数据库 devino 必须唯一且无硬链接，附着后复核原身份。同父进程只允许一次 lifespan；开始前和关闭后的新 HTTP 均拒绝。关闭先拒新请求，再等待原真实后台池 drain 完成，最后释放原 FD。关闭等待者取消不取消保留的 drain task；真实 drain 失败或取消保留未知所有者围栏，不宣称释放完成。

FD 关闭前核验捕获 inode，拒绝误关重用的无关 FD；单个关闭失败不阻止其他原 pin 的关闭，保留精确原 FD 重试。fork 子进程在接触 Auth/池前拒绝，只关闭自己的继承 FD，不 LOCK_UN 父锁。需要实际 event loop 持续运行到 drain 完成；该机制不声称进程死亡后任务仍能执行，也不证明跨进程运行接管。

## 实际证据与剩余缺口

新模块分轮最终受影响验证通过：16 项候选测试、后续生命周期门 3 项，以及补充关闭中重入断言的单项。原 client/inbox/control/auth/discovery 必要五模块 107 项通过。独立 High 只读关闭四项生命周期 MUST，未重复执行测试。详见 [测试与失败记录](evidence/checkpoint-75-tests.txt)。

最终 wheel SHA256 为 `9eaaeaf2731a0715c88c6088c482ef5d08cb79ac9509686fd636fe0ff6b03674`。发行包首次缺顶层 schema 的真实安装故障已修复：18 个原 schema 全部纳入 package data，安装库存和每文件字节精确匹配原来源，没有更改校验规则。随后探针的 CLI 错误文案断言已按原 generic error 合同修正，401 改用真实 HTTP 验证。

[安装态消费程序](evidence/checkpoint-75-installed-probe.py) 在 checkout 外运行，只导入已安装的 rlflow 和依赖，使用实际安装 console、TCP、原人类 HTTP 登录和转交。程序显式创建一次性 fixture 库，这不是启动入口隐式迁移。实际验收为 AWAITING_HUMAN→ADOPTED/DRAFT→完全关闭→重启→同原 ADOPTED、Core_version=1、旧 token HTTP401，worker/model/GPU 均为零。它使用原最小 client 配置；73 已通过的完整 YAML 契约没有重跑。

该交付解决 Core 建议链对测试装配的依赖，尚未解决有限执行宿主的安装装配、运行授权与恢复。下一切片须实现安装态原有限执行→可信结果→可靠 STOP 的真实消费链，不能只交付配置或测试组件。完整 T23、原 native/产品独立 Reviewer、严格 OS/quota、可信 invoice、B1、24h/8h 与 M0–M5 验收仍保留；付费模型、GPU、生产迁移和全局安装不获新授权。Goal 保持 active。
