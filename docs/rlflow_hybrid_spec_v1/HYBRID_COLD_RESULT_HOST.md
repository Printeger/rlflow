# 安装态原结果只读宿主

原有限执行完全关闭后，可以在新的安装态进程中读取 CPU 与工程结果，不恢复 Runtime、Pool、Controller、lease 或历史执行能力。只读宿主沿用原结果完整来源校验和 console 报告格式；当前执行保持 UNKNOWN，资源清理保持 NOT_OBSERVED，机器结果不能替代独立产品 Review 或条件证据。

## 可信启动

安装发行 wheel 与固定依赖后，使用 `rlflow.hybrid_cold_result_host.ColdResultRegistration` 和 `create_cold_result_host`。每项注册包含原 canonical 私有 Store 根、project_id、原 store_epoch、受保护启动配置中的原 Registry，以及 CPU_TRIAL 或 ENGINEERING 类型。最多三个不同项目，数据库必须是私有、普通、单链接原文件。不从产物、数据库批准 witness 或 HTTP 请求自动推导可信配置，不扫描或接管其他项目。

```python
import uvicorn
from rlflow.hybrid_cold_result_host import create_cold_result_host

def serve_original_history(registrations, auth, port):
    # registrations 和 auth 由可信部署入口显式提供，不读取用户产物。
    origin = f"http://127.0.0.1:{port}"
    app = create_cold_result_host(registrations, auth, origin=origin)
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=False)
```

`auth` 必须是新建的原 AuthStore，沿用原 Credential/Principal SDK 与项目范围。可以显式发放原 request-only agent viewer token，安装 console 通过既有 `rlflow client execution-report --kind ... --source ...` 消费相同只读接口。Token 仅通过受保护环境配置提供，不能放入 argv、仓库配置或日志。人类会话及普通 bearer viewer 也按原认证方法检查；前一进程的 token 不因原数据库存在而恢复有效。

所有注册先预检，再以 `Store.attach_existing` 只读附着。不创建 writer/owner lock、inbox、审批、调度或工具执行服务；RUN、STOP、approve、recover 和 Agent 请求写入口均不存在。若需要实际执行或紧急清理，应使用仍持有原能力的原有限宿主，不能把本入口当 STOP 接管器。

## 读取与关闭行为

读取使用原 CpuAssessmentReader、CandidateOutputReader 和 DeliveryEvidenceReader。共用原报告 DTO 校验函数，但不构造可写 discovery/inbox。根目录、数据库身份、Store 字段、epoch、Registry 和原 reader 绑定变化会拒绝；PID 和关闭门在认证与任何继承锁之前检查。Registry 合法配置差异、原批准到期只使结果成为 HISTORICAL_ONLY，不能激活执行。

两个真实读任务占满独立有界池时，第三个返回 429。取消 HTTP 等待者不释放仍运行任务的容量。读后再次检查身份与认证，关闭先拒新请求再排干真实任务；关闭等待者取消不丢失 drain。非法输入400，不存在或不可见404，认证无效401，来源损坏或不支持503，不用重新初始化或自动恢复来隐藏故障。

SQLite 只读连接可能维护 WAL/SHM。承诺是不新增业务事件、不结算或退款、不改变预算承诺、不重新执行；不是整个目录绝对零写，也不是只凭历史 STOP 回执证明当前资源状态。

## 验收与剩余缺口

安装态新进程实际消费先前正常 STOP 的 CPU384机器结果与工程3项原始结果/21项机器检查；首个只读宿主强制结束后，第二个新进程仍读到同一原来源、版本与 Review 缺口，旧 token401、跨项目范围404、写入口404，原业务表身份摘要不变，worker重启0。新数据损坏、认证晚撤销、真实读任务容量/关闭及实际数据库副本重绑定分别通过定向测试。[证据](evidence/checkpoint-77-tests.txt)保留所有失败与修复。

这项验收只证明原正常执行历史的冷读和只读宿主重开安全。执行启动超时、活动 worker/控制进程崩溃、预算 UNKNOWN 和批准状态的原 reconcile/恢复仍需另一个隔离切片验证；不根据本轮读取通过宣布 A22 或完整异常恢复完成。原 native、独立产品 Reviewer、严格 OS 配额、provider invoice、B1 与长期验收缺口保持。
