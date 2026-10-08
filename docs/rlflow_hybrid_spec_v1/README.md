# rlflow Hybrid 需求开发包 v1.0

日期：2026-10-07。主文档是 `PRD.md`；浏览器阅读版是 `PRD.html`。这是需求、接口起稿和测试样例，不是已经运行的 Dashboard 或 rlflow 实现。

## 文件

| 文件 | 用途 |
|---|---|
| `PRD.md` | 25 个编号章节：产品边界、架构、状态、预算、实验、Dashboard、实时协议、安全、迁移和验收 |
| `PRD.html` | 同一需求的独立浏览器阅读版，内嵌样式，无外部脚本/字体依赖 |
| `IMPLEMENTATION_PLAN.md` | M0–M5、T00–T25 共 26 个开发任务、依赖与质量门槛 |
| `CODEX_START.md` | 可交给 Codex 的首阶段开发指令；默认只授权 M0/M1 的文档范围，不批准真实运行 |
| `SOURCES.md` | 已读取的源码文档与官方技术依据、基线指纹、核验限制 |
| `openapi.yaml` | OpenAPI 3.1 接口起稿；不是现有服务生成的接口 |
| `schemas/` | 事件 envelope、未批准目标、命令请求、首批事件 payload 的 JSON Schema |
| `examples/` | 禁用执行的配置模板、未批准目标、暂停命令、明确标识的 fixture 事件 |
| `validate_spec.py` | 离线校验脚本：schema、正反例、事件顺序、文档编号和本地引用 |
| `VALIDATION_REPORT.md` | 本包实际执行的静态/离线检查结果，不是系统集成报告 |

## 推荐使用顺序

先读 PRD 第 1–7 节与第 18 节，再按实施计划选择当前里程碑。将目录放在仓库 `docs/hybrid-v1/`，使用 `CODEX_START.md` 中的指令开始 M0/M1。Schema 和 API 是 T03 的合同起点，需补齐生产实体读模型和所有事件 payload 后才上线；禁止以泛型 object 直接承载未验证的权限或状态转换。

## 样例安全边界

`project.example.yaml` 默认 `execution_enabled: false`、`adapter: fixture`；所有真实模型别名与路径未配置。`goal.fixture.json` 是 UNAPPROVED 提案，预算不允许模型/GPU；事件 fixture 是独立合成的已运行片段，用于 reducer/UI 测试，不表示这份未批准提案曾获授权，也不是完整审批生命周期。

本包没有真实密钥、账户、训练数据或生产状态。不要把 fixtures 挂到 live endpoint；不要根据文档自行扩大网络、GPU、付费模型或生产迁移权限。

## 离线校验

校验脚本需要开发环境中安装 `jsonschema` 与 `PyYAML`，不会联网读取 schema 或启动模型：

```bash
python validate_spec.py
```

校验通过只说明需求包的指定结构和样例自洽。OpenAPI 为初始合同，校验不替代完整 API 类型设计、服务端认证、运行时隔离、真实模型协议测试、科学有效性和性能压测。
