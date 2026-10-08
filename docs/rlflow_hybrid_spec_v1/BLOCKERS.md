# 阻塞与证据缺口

目前仍可推进开发，没有需要终止完整 Goal 的外部阻塞。

Checkpoint08：private工具返回事实基础与全回归455/32通过，独立High范围无MUST_FIX。公开collector尚待开发而非外部阻塞；需要bounded发现、可信release/权限核验、事务幂等写入，不能将现private context/hash当放行证明。其余环境证据缺口如下保留。

Checkpoint09：执行前REGISTER/有界reader与全回归478/32通过，High父目录durability finding关闭。继续core pending/事务offset与公开collector，没有新的外部阻塞；partial尾修复、源恢复/历史coverage不能静默处理，仍属待实现恢复合同。

本切片故障不是外部阻塞：冻结全回归暴露 guardian teardown race 与角色可写 default guard 控制目录，已经按完整真实身份和控制文件隔离修复，最终 r3 368 passed / 32 skipped，High 范围内阻塞 finding 全部关闭。没有删除测试、延长业务终止门槛或忽略 cleanup 错误。

1. 原 Codex 版本不匹配已修复：0.161.0 的工具注册、隔离测试通过；使用独立空 HOME 的固定 census catalog 与本机 localhost 拒绝端点，零模型调用。真实 runtime 的供应商 usage/interrupt/恢复仍未验证，不能把 doctor 通过当作真实业务闭环通过。
2. cgroup v2 存在，但未证明本项目拥有可委派 subtree；严格任务拒绝执行。后续资源测试先验证能力，不能修改宿主安全配置绕过。
3. 真实模型、GPU、付费资源未获单独精确运行授权。可完成普通本地代码、模型无关测试、实验与故障验证；真实供应商闭环属于独立证据缺口。
4. 24h fixture / 8h 浏览器 soak、B1 性能、干净安装、迁移及最终审查未执行，不能用短测试替代。

pytest 默认加载宿主 ROS 插件时缺少 lark。已通过 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 使用项目隔离测试入口，不修改宿主包，也不删除项目测试。
