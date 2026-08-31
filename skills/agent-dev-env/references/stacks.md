# 技术栈映射

边界的划法与栈无关，只是组件换名字。默认给 Cloudflare 方案（边缘 Agent 完成度最高，且 Agents SDK 是目前唯一为边缘有状态运行时设计的 Agent 框架）。

## 组件对应

| 职责 | Cloudflare | AWS | 阿里云 | 自建 |
|---|---|---|---|---|
| 边缘执行 | Workers | Lambda@Edge / Lambda | 函数计算 FC | Node/Deno + 反代 |
| 有状态 Agent | Durable Objects（内置 SQLite） | DynamoDB + Lambda | Tablestore + FC | Postgres + 粘性会话 |
| 长任务编排 | Workflows | Step Functions | Serverless 工作流 | Temporal |
| 异步解耦 | Queues | SQS | MNS | Redis / RabbitMQ |
| 对象存储 | R2（零出口费） | S3 | OSS | MinIO |
| 向量检索 | Vectorize | OpenSearch | 向量检索版 | pgvector |
| 容器 | Containers / Sandbox SDK | Fargate | ACK Serverless | Docker |
| LLM 网关 | AI Gateway | Bedrock | 百炼 | LiteLLM / Helicone |
| 业务数据库 | Supabase / Hyperdrive→PG | RDS / Aurora | RDS | Postgres |

## 有状态运行时是关键差异

Durable Objects 的特殊之处：**每个会话一个实例，状态与计算零距离，且支持 hibernation**。这带来两个别的栈难复制的性质：

1. 会话状态读写没有网络往返
2. 空闲连接不计费——这决定了 IoT 常驻设备方案能不能规模化

其他栈上要实现类似效果，通常是「粘性路由 + 外部状态存储」，需要自己处理并发与一致性。**如果项目重度依赖有状态会话或设备长连接，这是选 Cloudflare 的主要理由。**

## 混合部署

不必二选一。常见的合理组合：

- **边缘 + GPU 兜底**：Agent 循环在 Cloudflare，RL 训练类任务在阿里云/AWS 的 GPU 集群按需拉起，产物回传对象存储
- **边缘 + 长驻服务**：容器规格或时长不够时（如本地模型推理），用函数计算或 K8s 承接，Worker 经内部 API 调用
- **中国大陆接入**：目标用户在大陆时，海外边缘节点的延迟与连通性不可控。大陆入口用阿里云（需 ICP 备案）做反代，核心逻辑仍留边缘

纪律：跨云资源同样用 IaC 管理（Terraform / Pulumi），密钥同样走 CI 的 Environments，不允许控制台手工创建长期资源。

## 纯自建

没有云依赖也能落地，边界不变：

- 有状态 Agent：Postgres + 会话粘性路由
- 长任务：Temporal 或 Celery
- LLM 网关：LiteLLM（统一多模型接口 + 缓存 + 限流）
- 评估与进化：本地 Python 环境跑

代价是运维负担，收益是没有厂商锁定。**判断标准**：团队有没有人愿意长期维护这套基础设施。没有的话，托管方案的隐性成本更低。
