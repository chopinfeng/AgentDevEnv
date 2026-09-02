# AgentDevEnv

Cloudflare 为主、阿里云兜底的 Agent 开发环境。框架可换、工具支持 MCP 与 Skills、可接 ESP32 等低算力设备。

设计取舍与依据见 `docs/` 的蓝图文档；本文只讲怎么用。

## 快速开始

```bash
pnpm install
cp apps/agent-core/.dev.vars.example apps/agent-core/.dev.vars   # 填 ANTHROPIC_API_KEY
supabase start          # 本地 Postgres（需 Docker，可选）
pnpm dev                # → http://localhost:8787
```

```bash
curl -X POST localhost:8787/agents/main-agent/demo -H 'content-type: application/json' -d '{"message":"你好"}'
```

响应里的 `framework` / `tools` / `devices` 字段可用来确认当前配置是否生效。

## 结构

```
apps/
  agent-core/     # 边缘执行：Workers + Agents SDK（DO + SQLite）
  heavy-runner/   # 重执行：Python 框架容器（Containers / 阿里云）
  console/        # 前端控制台（待建）
packages/
  agent-kernel/   # 框架 seam + 工具层 + Skills
  prompts/        # 版本化 prompt（进化产物经 PR 回写）
  shared/         # 共享类型
deploy/           # 目标机侧的拉取式部署代理 + systemd 单元
devices/
  esp32/          # ESP32 固件（Arduino）
  raspberry-pi/   # 树莓派 agent host
evolution/        # DSPy + GEPA 离线进化管线
supabase/         # 数据库迁移（唯一改库方式）
skills/
  agent-dev-env/  # 把本项目的架构决策抽成可复用的 skill
docs/             # 架构图与蓝图
```

> `skills/agent-dev-env/` 是这套架构的通用化版本 —— 换个项目也能用。
>
> - 脚手架：`python3 skills/agent-dev-env/scripts/scaffold.py <目录>`（产出可直接 `pnpm install && pnpm typecheck`）
> - 评测：`skills/agent-dev-env/evals/`——任务 eval（有/无 skill 对比产出）+ 触发 eval（description 准确率）

## 换 Agent 框架

改 `AGENT_FRAMEWORK` 一个值即可，环境结构不动：

```bash
wrangler deploy --env staging --var AGENT_FRAMEWORK:remote:langgraph
```

| 值 | 运行位置 |
|---|---|
| `cf-agents` | 边缘 isolate（默认） |
| `mastra` | 边缘 isolate（待接线） |
| `remote:langgraph` · `remote:claude-code` · `remote:pi` | heavy-runner 容器 |

框架名写错会立即 500 并列出可选值，不会静默回落。

**换框架时不动**：DO 类名与 `migrations`（所以不触发 DO 迁移）、路由与请求响应类型、环境变量面、Supabase schema、CI 工作流。

**加新框架**：边缘框架在 `packages/agent-kernel/src/adapters/` 实现 `AgentAdapter` 并在 `registry.ts` 注册；Python 框架不必写边缘适配器，用 `remote:<name>`，在 `apps/heavy-runner/main.py` 的 `FRAMEWORKS` 加一个同签名函数，两侧共用 `/turn` 契约。

## 工具

工具用纯 JSON Schema 描述，不绑 SDK，所以换框架时工具集原样可用。四种来源汇成一份 `ToolSet`：`mcp`（外部服务器，`addMcpServer()`）、`device`（现场设备）、`skill`（`load_skill`）、`builtin`（`list_devices` 等）。

**Skills** 遵循 [Agent Skills 规范](https://agentskills.io/specification)，渐进式披露（只有名字和描述常驻提示，正文按需加载）。稳定能力放 `packages/agent-kernel/src/skills/bundled.ts` 走 Git 评审；进化管线产出的候选先落 R2，验证后由 PR 固化。

**工具回调** —— `remote:*` 下 Agent 循环在容器里，设备与 MCP 连接却活在 DO 内，容器执行工具时回调：

```bash
curl -X POST $BASE/agents/main-agent/$SESSION/tools/invoke \
  -H "authorization: Bearer $TOOL_CALLBACK_SECRET" \
  -d '{"tool":"lamp-01__set_lamp","args":{"on":true}}'
```

> 该端点能驱动物理设备。生产环境未配 `TOOL_CALLBACK_SECRET` 会直接返回 503，避免忘配密钥裸奔。

## 接入设备

设备只做感知与执行，Agent 循环留在云端（ESP32 跑不动可用的模型）。连接串：

```
wss://<host>/agents/main-agent/<session>?role=device&dialect=<min|mcp>&device=<id>
```

| 方言 | 适用 |
|---|---|
| `min` | 自定义极简帧，固件约 200 行、不实现 JSON-RPC。见 `devices/esp32/` |
| `mcp` | JSON-RPC 包在信封里（xiaozhi 同款）。适合已在跑 Espressif `mcp-c-sdk` 或小智固件的设备 |

设备连接支持 hibernation：空闲时 DO 休眠不计费，有帧到达自动唤醒 —— 这是 MCU 常驻在线的前提。

> WebSocket **不是** MCP 官方 transport（SEP-1287/1288 已关闭为 dormant），两种方言都是规范允许的 custom transport，按一帧一行 JSON 走。MCP 规范 2026-07-28 版已移除 `initialize` 握手，故 `mcp` 方言连上直接发 `tools/list`。

## 部署

开发机、CI、部署目标可以是三台不同机器。边缘走推、容器走拉，见
[docs/deployment-topology.md](docs/deployment-topology.md)。

> ⚠️ 本仓库是公开的，**不要在目标机上装 self-hosted runner**——fork PR
> 能在你机器上执行任意代码。内网部署用 `deploy/pull-agent.sh` 主动拉。

| | Local | Staging | Production |
|---|---|---|---|
| 触发 | `pnpm dev` | 合并 `main` | Release + 审批 |
| Worker | Miniflare | `--env staging` | `--env production` |
| Supabase | `supabase start` | staging 项目 | production 项目（PITR） |

密钥放 GitHub Environments（staging / production 两套），CI 经 `wrangler secret put` 下发。
