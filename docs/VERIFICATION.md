# 验证结果

独立副本于 2026-09-15 在 Python 3.12 环境完成以下离线检查：

- 264 项测试通过，0 项失败。
- 32 项依赖外部项目 Runner 的测试明确跳过，不计作通过。
- 独立 CLI 帮助、全新状态目录初始化和旧项目迁移入口拒绝行为通过冒烟检查。
- Python 依赖检查通过。
- 已确认副本不与来源共享 hardlink，也没有在可执行源码中保留来源工作区绝对路径。
- 测试过程没有真实模型调用或 GPU 运行。

已知限制：worker 仍保留 10 秒启动放行等待；项目 Runner 未配置；离线结果不能证明真实模型长期任务或 GPU 执行具备生产可靠性；当前按源码树运行，尚未验证 wheel 中角色和 schema 数据的打包。

原始日志、逐文件来源哈希及复制差异只保存在创建机器的 Git 忽略目录中，不属于远程发布内容。

## 2026-09-16 reliability synchronization

The independent `bin/rlflow ... self-test` run passed **309 tests**, with **32
external project/H1 adapter exclusions** reported as skipped (not passed).
Exact executable identity:
`7539a8e97b5de6c8bad4151ead9648f6317d28eb949c35f450df13e8cef936e6`.
Raw report: `audit/reliability-release/runtime/self-test.json` (local evidence).
No real model or GPU calls. Actual disk-quota acceptance was cancelled by the
user and is unverified. Strict resource admission remains fail-closed.
