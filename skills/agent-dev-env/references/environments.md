# 三环境与 CI/CD

## 环境矩阵

| 维度 | 本地 | 测试 | 生产 |
|---|---|---|---|
| 运行时 | 本地模拟器（`wrangler dev` / Miniflare） | 独立实例，`--env staging` | 独立实例，`--env production` |
| 触发 | 开发者手动 | 合并主干自动 | 打 tag / Release + 人工审批 |
| 数据库 | 本地容器（`supabase start`） | 独立项目或 PR 分支 | 独立项目 + 时间点恢复 |
| LLM 调用 | dev 网关（开缓存省钱） | staging 网关，全量日志 | prod 网关，限流 + 成本告警 |
| 密钥 | `.dev.vars`（gitignore） | CI 从 Environments 下发 | 同左 + 审批保护 |
| 可观测 | 本地日志 | 结构化日志 + trace | 同左 + 归档（喂评估与进化） |

## 同构原则

三个环境共用**同一份配置文件**，用环境块区分。Cloudflare 的形态：

```jsonc
{
  "name": "agent-core",
  "durable_objects": { "bindings": [{ "name": "MainAgent", "class_name": "MainAgent" }] },
  "migrations": [{ "tag": "v1", "new_sqlite_classes": ["MainAgent"] }],

  // 变量面 = 所有适配器所需变量的并集，一次性声明
  "vars": { "ENVIRONMENT": "local", "AGENT_FRAMEWORK": "cf-agents", "HEAVY_RUNNER_URL": "" },

  "env": {
    "staging":    { "vars": { "ENVIRONMENT": "staging",    /* 同上，值不同 */ },
                    "durable_objects": { "bindings": [/* 同一个类名 */] } },
    "production": { "vars": { "ENVIRONMENT": "production" },
                    "durable_objects": { "bindings": [/* 同一个类名 */] } }
  }
}
```

**关键点**：`durable_objects` 的 `class_name` 与 `migrations` 的 `tag` 三个环境完全一致。它们是有状态运行时的身份，改动会触发数据迁移。

## 密钥管理

- 本地：`.dev.vars`，必须在 `.gitignore` 里
- CI/线上：存 GitHub Environments（staging / production 两套），流水线里经 `wrangler secret put` 下发
- 部署 token 与管理 token 分开，按最小权限申请
- 任何密钥不进代码库——包括注释里的示例值

## 流水线

四条工作流，职责不重叠：

**`ci.yml`** —— PR 触发
- lint + 类型检查 + 单测
- `wrangler versions upload` 出预览 URL（上传但不接流量）
- 数据库 PR 分支：每个 PR 一个隔离库，自动跑迁移

**`deploy-staging.yml`** —— 合并主干触发
- 跑数据库迁移到 staging
- 部署 Worker
- 跑端到端评估集（见 `evaluation-and-evolution.md`），失败告警

**`deploy-prod.yml`** —— Release 触发
- GitHub Environment 保护规则要求人工审批
- 迁移 + 部署
- 用渐进式部署（gradual deployments）灰度放量

**`evolve.yml`** —— 定时/手动触发
- 跑离线优化管线
- 产物以 PR 形式提交，走同一套评估门禁

## 数据库变更纪律

只经迁移文件变更，CI 执行。禁止在管理后台手改 schema——手改的那一次会让三个环境永久分叉，而且没有任何记录能告诉你分叉在哪。

迁移文件进 Git，和代码一起评审。

## 单人项目的简化

三环境完整版对单人项目太重。可以先砍成两个：

- 本地 + 生产，跳过 staging
- 保留：同构配置、迁移纪律、密钥隔离
- 去掉：审批流、PR 预览环境、灰度

等到有第二个人加入、或者有真实用户之后再补 staging。**不要省掉迁移纪律**——那是唯一不可回退的部分。
