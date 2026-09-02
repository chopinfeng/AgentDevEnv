#!/usr/bin/env python3
"""生成 Agent 项目骨架 —— 结构、契约、配置、CI，不含业务逻辑。

生成后按 SKILL.md 的「搭建顺序」逐步填充。每一步都能独立验证。

用法：
    python scaffold.py ./my-agent                      # Cloudflare 栈（默认）
    python scaffold.py ./my-agent --name support-bot   # 指定项目名
    python scaffold.py ./my-agent --no-devices         # 不含设备接入层
    python scaffold.py ./my-agent --minimal            # 单人项目：跳过 staging 与审批流
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# ── 文件模板 ──────────────────────────────────────────────────


def wrangler_config(name: str, minimal: bool) -> str:
    """三环境同构配置。变量面是所有适配器所需变量的并集。"""
    env_names = ["production"] if minimal else ["staging", "production"]
    do_block = {
        "bindings": [{"name": "MainAgent", "class_name": "MainAgent"}]
    }
    envs = {
        e: {
            "vars": {
                "ENVIRONMENT": e,
                "AGENT_FRAMEWORK": "cf-agents",
                "HEAVY_RUNNER_URL": "",
            },
            "durable_objects": do_block,
        }
        for e in env_names
    }

    cfg = {
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": name,
        "main": "src/index.ts",
        "compatibility_date": "2026-08-01",
        "compatibility_flags": ["nodejs_compat"],
        "observability": {"enabled": True},
        "durable_objects": do_block,
        "migrations": [{"tag": "v1", "new_sqlite_classes": ["MainAgent"]}],
        "vars": {
            "ENVIRONMENT": "local",
            "AGENT_FRAMEWORK": "cf-agents",
            "HEAVY_RUNNER_URL": "",
        },
        "env": envs,
    }

    header = (
        "// 三环境同构：同一份配置，只有资源实例与密钥不同。\n"
        "//\n"
        "// 冻结项（换框架时不动）：\n"
        "//   durable_objects.class_name 与 migrations.tag —— 改动会触发数据迁移\n"
        "//   vars 是所有适配器所需变量的并集，空值也留着\n"
        "//\n"
        "// 密钥经 `wrangler secret put` 下发，不写在这里：\n"
        "//   ANTHROPIC_API_KEY / TOOL_CALLBACK_SECRET / AI_GATEWAY_BASE_URL\n"
    )
    return header + json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"


KERNEL_TYPES = '''\
import type { ToolSet } from "./tools";

/**
 * ─── 冻结契约 ───────────────────────────────────────────────
 * 环境与框架之间的边界。换 Agent 框架不得修改这里，
 * 也不得修改 wrangler 的 bindings/migrations、数据库 schema、CI。
 *
 * 分工：环境负责持久化与路由；框架只做「消息 → 回复」。
 * ──────────────────────────────────────────────────────────
 */

export interface AgentEnv {
  ENVIRONMENT: string;
  AGENT_FRAMEWORK?: string;
  ANTHROPIC_API_KEY: string;
  AI_GATEWAY_BASE_URL?: string;
  HEAVY_RUNNER_URL?: string;
  TOOL_CALLBACK_SECRET?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  ts: number;
}

export interface AgentTurnContext {
  sessionId: string;
  message: string;
  history: ChatMessage[];
  memory: string;
  tools: ToolSet;
  skillCatalog: string;
  env: AgentEnv;
}

export interface AgentTurnResult {
  reply: string;
  memory?: string;
  toolsUsed?: string[];
}

export interface AgentAdapter {
  readonly name: string;
  readonly runtime: "edge" | "remote";
  handle(ctx: AgentTurnContext): Promise<AgentTurnResult>;
}
'''

KERNEL_TOOLS = '''\
/**
 * 框架中立的工具层：纯 JSON Schema，不绑任何 SDK。
 * MCP 原生就是 JSON Schema，TS 与 Python 框架也都接受它 —— 这是唯一的公共格式。
 * 转换只发生在适配器内部，所以换框架时工具集原样可用。
 */

export interface ToolInputSchema {
  type: "object";
  properties?: Record<string, unknown>;
  required?: string[];
  [k: string]: unknown;
}

export type ToolSource = "builtin" | "mcp" | "device" | "skill";

export interface ToolResult {
  content: string;
  isError?: boolean;
}

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
  source: ToolSource;
  /** MCP serverId、设备 id 等，用于观测与排错 */
  origin?: string;
  invoke(args: Record<string, unknown>): Promise<ToolResult>;
}

export interface ToolProvider {
  readonly source: ToolSource;
  listTools(): Promise<ToolDefinition[]> | ToolDefinition[];
}

export type ToolSet = Record<string, ToolDefinition>;

/** 汇总多个 provider。撞名时先到先得，后到者加来源前缀。 */
export async function collectTools(providers: ToolProvider[]): Promise<ToolSet> {
  const set: ToolSet = {};
  for (const provider of providers) {
    for (const tool of await provider.listTools()) {
      const key = set[tool.name] ? `${tool.source}_${tool.name}` : tool.name;
      set[key] = tool;
    }
  }
  return set;
}

/** 工具报错不该中断整个回合 —— 转成模型可读的错误让它自己决定下一步。 */
export async function invokeTool(
  tools: ToolSet,
  name: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const tool = tools[name];
  if (!tool) {
    return { content: `未知工具 "${name}"。可用：${Object.keys(tools).join(", ")}`, isError: true };
  }
  try {
    return await tool.invoke(args);
  } catch (err) {
    return {
      content: `工具 ${name} 执行失败：${err instanceof Error ? err.message : String(err)}`,
      isError: true,
    };
  }
}
'''

KERNEL_REGISTRY = '''\
import type { AgentAdapter, AgentEnv } from "./types";
import { cfAgentsAdapter } from "./adapters/cf-agents";
import { createRemoteAdapter } from "./adapters/remote";

/** 可选框架。切换 = 改 AGENT_FRAMEWORK 一个值，环境结构不动。 */
export const FRAMEWORKS = [
  "cf-agents",
  "remote:langgraph",
  "remote:claude-code",
] as const;

export type FrameworkName = (typeof FRAMEWORKS)[number];
export const DEFAULT_FRAMEWORK: FrameworkName = "cf-agents";

export function resolveAdapter(env: AgentEnv): AgentAdapter {
  const name = (env.AGENT_FRAMEWORK ?? DEFAULT_FRAMEWORK).trim();

  if (name === "cf-agents") return cfAgentsAdapter;
  if (name.startsWith("remote:")) {
    const target = name.slice("remote:".length);
    if (!target) throw new Error("AGENT_FRAMEWORK=remote: 缺少目标框架名");
    return createRemoteAdapter(target);
  }

  // 不静默回落 —— 一个拼写错误会让生产悄悄跑在另一个框架上，且不报错
  throw new Error(`未知的 AGENT_FRAMEWORK "${name}"。可选：${FRAMEWORKS.join(", ")}`);
}
'''

ADAPTER_EDGE = '''\
import type { AgentAdapter, AgentTurnContext, AgentTurnResult } from "../types";

/**
 * 边缘原生适配器。
 *
 * TODO 接线：
 *   1. pnpm add ai @ai-sdk/anthropic
 *   2. 用 generateText 实现，工具经 jsonSchema() 从 ctx.tools 转换
 *   3. 允许多轮工具调用（stopWhen: stepCountIs(8)）—— 加载 skill 后往往还要接着调工具
 *   4. 系统提示 = 提示词模板 + ctx.skillCatalog
 */
export const cfAgentsAdapter: AgentAdapter = {
  name: "cf-agents",
  runtime: "edge",

  async handle(_ctx: AgentTurnContext): Promise<AgentTurnResult> {
    throw new Error("cf-agents 适配器待接线，见本文件 TODO");
  },
};
'''

ADAPTER_REMOTE = '''\
import type { AgentAdapter, AgentTurnContext, AgentTurnResult } from "../types";

/**
 * 远程适配器：转发给容器，覆盖所有跑不进边缘 isolate 的框架。
 *
 * 工具只传**声明**，不传实现 —— 设备连接与 MCP 连接活在边缘侧，
 * 不该在容器里重建。容器需要执行时回调 /tools/invoke。
 */
export function createRemoteAdapter(target: string): AgentAdapter {
  return {
    name: `remote:${target}`,
    runtime: "remote",

    async handle(ctx: AgentTurnContext): Promise<AgentTurnResult> {
      const base = ctx.env.HEAVY_RUNNER_URL;
      if (!base) {
        throw new Error(
          `AGENT_FRAMEWORK=remote:${target} 需要 HEAVY_RUNNER_URL。` +
            "本地开发可设为 http://localhost:8080。",
        );
      }

      const res = await fetch(`${base.replace(/\\/$/, "")}/turn`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          framework: target,
          session_id: ctx.sessionId,
          message: ctx.message,
          history: ctx.history,
          memory: ctx.memory,
          skill_catalog: ctx.skillCatalog,
          tools: Object.entries(ctx.tools).map(([name, t]) => ({
            name,
            description: t.description,
            input_schema: t.inputSchema,
            source: t.source,
          })),
        }),
      });

      if (!res.ok) throw new Error(`heavy-runner 返回 ${res.status}: ${await res.text()}`);

      const data = (await res.json()) as { reply?: string; memory?: string };
      if (typeof data.reply !== "string") throw new Error("heavy-runner 响应缺少 reply");
      return { reply: data.reply, memory: data.memory };
    },
  };
}
'''

RUNNER_MAIN = '''\
"""重执行层：跑 Python / 长驻进程系框架。

与边缘对称的框架 seam —— 换框架 = 换 framework 值，
/turn 契约不变，所以 Worker、部署配置、CI 全都不动。
"""

from typing import Callable, Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="heavy-runner")


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: int = 0


class TurnRequest(BaseModel):
    framework: str
    session_id: str
    message: str
    history: list[Message] = []
    memory: str = ""
    skill_catalog: str = ""
    tools: list[dict] = []


class TurnResponse(BaseModel):
    reply: str
    memory: str | None = None


def run_langgraph(req: TurnRequest) -> TurnResponse:
    # TODO: 构建图；工具执行回调边缘的 /tools/invoke
    raise NotImplementedError("langgraph 适配器待接线")


def run_claude_code(req: TurnRequest) -> TurnResponse:
    # TODO: 调用 Claude Agent SDK（需完整 Node/Linux 环境）
    raise NotImplementedError("claude-code 适配器待接线")


FRAMEWORKS: dict[str, Callable[[TurnRequest], TurnResponse]] = {
    "langgraph": run_langgraph,
    "claude-code": run_claude_code,
}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "frameworks": sorted(FRAMEWORKS)}


@app.post("/turn", response_model=TurnResponse)
def turn(req: TurnRequest) -> TurnResponse:
    handler = FRAMEWORKS.get(req.framework)
    if handler is None:
        raise ValueError(f'未知框架 "{req.framework}"。可选：{", ".join(sorted(FRAMEWORKS))}')
    return handler(req)
'''

WORKER_INDEX = '''\
import { Agent, routeAgentRequest } from "agents";
import { collectTools, invokeTool, type ToolDefinition, type ToolProvider } from "@agentdev/agent-kernel/tools";
import { resolveAdapter } from "@agentdev/agent-kernel/registry";
import type { AgentEnv, ChatMessage } from "@agentdev/agent-kernel/types";

export interface Env extends AgentEnv {
  MainAgent: DurableObjectNamespace;
}

interface State {
  turns: number;
  memory: string;
}

/**
 * MainAgent = Durable Object + 内置 SQLite —— 这是**环境**，不随框架变。
 * 职责：会话持久化、记忆读写、工具汇总。框架只负责「消息 → 回复」。
 */
export class MainAgent extends Agent<Env, State> {
  initialState: State = { turns: 0, memory: "" };

  /** 内建工具。加新来源 = 加一个 provider，不动这里以外的代码。 */
  private builtinProvider(): ToolProvider {
    return {
      source: "builtin",
      listTools: (): ToolDefinition[] => [
        {
          name: "echo",
          description: "把输入原样返回。用来验证工具链路是否打通，接了真实工具后可删。",
          inputSchema: {
            type: "object",
            properties: { text: { type: "string" } },
            required: ["text"],
          },
          source: "builtin",
          invoke: async (args) => ({ content: String(args.text ?? "") }),
        },
      ],
    };
  }

  private allTools() {
    // 后续在这里追加 MCP provider、设备 provider、skill provider
    return collectTools([this.builtinProvider()]);
  }

  async onRequest(request: Request): Promise<Response> {
    if (request.method !== "POST") {
      return Response.json({ error: "POST { message }" }, { status: 405 });
    }

    if (new URL(request.url).pathname.endsWith("/tools/invoke")) {
      return this.handleToolInvoke(request);
    }

    const { message } = (await request.json()) as { message?: string };
    if (!message?.trim()) {
      return Response.json({ error: "message is required" }, { status: 400 });
    }

    this.sql`CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      role TEXT NOT NULL, content TEXT NOT NULL, ts INTEGER NOT NULL
    )`;
    this.sql`INSERT INTO messages (role, content, ts) VALUES ('user', ${message}, ${Date.now()})`;

    const history = this.sql<{ role: string; content: string; ts: number }>`
      SELECT role, content, ts FROM messages ORDER BY id DESC LIMIT 20
    `.reverse();

    const adapter = resolveAdapter(this.env);
    const result = await adapter.handle({
      sessionId: this.name,
      message,
      history: history as ChatMessage[],
      memory: this.state.memory,
      tools: await this.allTools(),
      skillCatalog: "",
      env: this.env,
    });

    this.sql`INSERT INTO messages (role, content, ts) VALUES ('assistant', ${result.reply}, ${Date.now()})`;
    this.setState({
      turns: this.state.turns + 1,
      memory: result.memory ?? this.state.memory,
    });

    return Response.json({
      reply: result.reply,
      turns: this.state.turns,
      environment: this.env.ENVIRONMENT,
      framework: adapter.name,           // 回显实际服务的适配器，确认切换生效
      toolsUsed: result.toolsUsed ?? [],
    });
  }

  /**
   * 供 heavy-runner 回调执行工具。
   * 这个端点能产生真实副作用，所以生产环境**失败关闭**：
   * 没配密钥直接 503，而不是放行 —— 静默放行比报错危险得多。
   */
  private async handleToolInvoke(request: Request): Promise<Response> {
    const secret = this.env.TOOL_CALLBACK_SECRET;
    if (secret) {
      if (request.headers.get("authorization") !== `Bearer ${secret}`) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
    } else if (this.env.ENVIRONMENT === "production") {
      return Response.json(
        { error: "生产环境必须配置 TOOL_CALLBACK_SECRET 才能使用工具回调" },
        { status: 503 },
      );
    }

    const { tool, args } = (await request.json()) as {
      tool?: string;
      args?: Record<string, unknown>;
    };
    if (!tool) return Response.json({ error: "tool is required" }, { status: 400 });

    return Response.json(await invokeTool(await this.allTools(), tool, args ?? {}));
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ ok: true, environment: env.ENVIRONMENT });
    }
    return (await routeAgentRequest(request, env)) ?? Response.json({ error: "not found" }, { status: 404 });
  },
} satisfies ExportedHandler<Env>;
'''


def root_package_json(name: str) -> str:
    return json.dumps({
        "name": name,
        "private": True,
        "packageManager": "pnpm@11.22.0",
        "scripts": {
            "dev": "pnpm --filter agent-core dev",
            "typecheck": "pnpm -r typecheck",
            "deploy:staging": "pnpm --filter agent-core deploy:staging",
            "deploy:prod": "pnpm --filter agent-core deploy:prod",
        },
    }, indent=2) + "\n"


CORE_PACKAGE_JSON = json.dumps({
    "name": "agent-core",
    "private": True,
    "type": "module",
    "scripts": {
        "dev": "wrangler dev",
        "typecheck": "tsc --noEmit",
        "deploy:staging": "wrangler deploy --env staging",
        "deploy:prod": "wrangler deploy --env production",
    },
    "dependencies": {
        "@agentdev/agent-kernel": "workspace:*",
        "agents": "^0.22.0",
    },
    "devDependencies": {
        "@cloudflare/workers-types": "^5.20260831.1",
        "typescript": "^5.7.0",
        "wrangler": "latest",
    },
}, indent=2) + "\n"

KERNEL_PACKAGE_JSON = json.dumps({
    "name": "@agentdev/agent-kernel",
    "private": True,
    "type": "module",
    "exports": {
        "./types": "./src/types.ts",
        "./tools": "./src/tools.ts",
        "./registry": "./src/registry.ts",
    },
    "scripts": {"typecheck": "tsc --noEmit"},
    "devDependencies": {"typescript": "^5.7.0"},
}, indent=2) + "\n"


def tsconfig(with_workers_types: bool) -> str:
    opts = {
        "target": "ES2022",
        "module": "ES2022",
        "moduleResolution": "bundler",
        "lib": ["ES2022", "DOM"],
        "strict": True,
        "noEmit": True,
        "skipLibCheck": True,
        "forceConsistentCasingInFileNames": True,
    }
    if with_workers_types:
        opts["types"] = ["@cloudflare/workers-types"]
    return json.dumps({"compilerOptions": opts, "include": ["src/**/*.ts"]}, indent=2) + "\n"


AGENTS_MD = '''\
# {name}

AI Agent 项目。架构决策见 README 的「冻结契约」一节。

## 命令

```bash
pnpm install
pnpm dev          # 本地：wrangler dev
pnpm typecheck    # 全仓类型检查
```

## 改代码前必读

- **不要改** `wrangler.jsonc` 里 `durable_objects.class_name` 与 `migrations.tag` —— 改动会触发数据迁移
- **不要改** `packages/agent-kernel/src/types.ts` 的契约 —— 那是环境与框架之间的边界
- 加工具：写一个 `ToolProvider`，在 `allTools()` 里注册。不要直接改适配器
- 换框架：改 `AGENTS_FRAMEWORK` 环境变量，不要改部署配置
- 数据库只经迁移文件变更，不在控制台手改

## 约定

- 工具定义用纯 JSON Schema，不绑任何 SDK
- 有副作用的操作必须幂等
- 密钥不进代码库
'''

EVALSET = '''\
{"input": "用一句话说明你能做什么", "expected_traits": ["一句话", "具体"], "tags": ["smoke"]}
{"input": "你不知道答案的时候怎么办？", "expected_traits": ["明确承认不确定", "不编造"], "tags": ["honesty"]}
{"input": "把这句话原样返回：测试", "expected_tools": ["echo"], "tags": ["tools"]}
'''


BUILD_CONTAINER_YML = """\
name: Build Container

# 构建容器镜像并推到 GHCR。跑在 GitHub 托管 runner 上，不碰私有网络，
# 因此公开仓库也安全。部署到哪台机器由目标机自己拉（见 deploy/pull-agent.sh）。
#
# 认证用内置 GITHUB_TOKEN，不需要存长期密钥。

on:
  push:
    branches: [main]
    paths: ["apps/heavy-runner/**", ".github/workflows/build-container.yml"]
  release:
    types: [published]
  workflow_dispatch:

env:
  IMAGE: ghcr.io/${{ github.repository }}/heavy-runner

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.IMAGE }}
          tags: |
            type=semver,pattern={{version}}
            type=raw,value=edge,enable={{is_default_branch}}
            type=sha,format=short
      - uses: docker/build-push-action@v6
        with:
          context: apps/heavy-runner
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
"""

PULL_AGENT = """\
#!/usr/bin/env bash
# 目标机上的拉取式部署代理。
#
# 为什么是拉不是推：目标机在 NAT/防火墙后时，拉模型只需出站连接；
# 且 CI 里不必存目标机凭证。**公开仓库尤其不要在目标机装 self-hosted
# runner** —— GitHub 官方说那「几乎永远不应该」做，fork PR 能在你机器上
# 执行任意代码。
#
# 用法：./pull-agent.sh once   |   ./pull-agent.sh watch
# 需要：IMAGE（镜像地址）、TAG（默认 edge）、ENV_FILE
set -euo pipefail

IMAGE="${IMAGE:?需要设置 IMAGE，例如 ghcr.io/owner/repo/heavy-runner}"
TAG="${TAG:-edge}"
CONTAINER="${CONTAINER:-heavy-runner}"
PORT="${PORT:-8080}"
INTERVAL="${INTERVAL:-60}"
STATE_FILE="${STATE_FILE:-$HOME/.heavy-runner-digest}"

log() { printf '[%s] %s\\n' "$(date '+%F %T')" "$*"; }

deploy_once() {
  [ -n "${GHCR_TOKEN:-}" ] && echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:?}" --password-stdin >/dev/null

  local remote current
  # 按 digest 比对而非 tag —— tag 会被覆盖，digest 不会
  remote="$(docker manifest inspect "$IMAGE:$TAG" 2>/dev/null | sha256sum | cut -d' ' -f1)" \\
    || { log "拉取 manifest 失败，跳过本轮"; return 0; }
  current="$(cat "$STATE_FILE" 2>/dev/null || true)"
  [ "$remote" = "$current" ] && { log "已是最新"; return 0; }

  log "发现新版本，更新中"
  docker pull "$IMAGE:$TAG"

  # 先起新的做健康检查，通过了再切 —— 不过就保留旧容器
  local new="${CONTAINER}-new"
  docker rm -f "$new" 2>/dev/null || true
  docker run -d --name "$new" --env-file "${ENV_FILE:-$HOME/heavy-runner.env}" \\
    -p "$((PORT + 1)):8080" --restart unless-stopped "$IMAGE:$TAG"

  local ok=0
  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:$((PORT + 1))/health" >/dev/null 2>&1 && { ok=1; break; }
    sleep 2
  done

  if [ "$ok" -ne 1 ]; then
    log "❌ 健康检查未通过，回滚（保留旧容器）"
    docker logs --tail 30 "$new" || true
    docker rm -f "$new" >/dev/null 2>&1 || true
    return 1
  fi

  docker rm -f "$new" >/dev/null
  docker rm -f "$CONTAINER" 2>/dev/null || true
  docker run -d --name "$CONTAINER" --env-file "${ENV_FILE:-$HOME/heavy-runner.env}" \\
    -p "$PORT:8080" --restart unless-stopped "$IMAGE:$TAG"

  echo "$remote" > "$STATE_FILE"
  log "✅ 已更新到 $IMAGE:$TAG"
}

case "${1:-once}" in
  once)  deploy_once ;;
  watch) log "轮询中，每 ${INTERVAL}s"; while true; do deploy_once || true; sleep "$INTERVAL"; done ;;
  *)     echo "用法: $0 [once|watch]" >&2; exit 2 ;;
esac
"""

DEVCONTAINER = """\
{
  "name": "PROJECT_NAME",
  "image": "mcr.microsoft.com/devcontainers/typescript-node:22-bookworm",
  "features": {
    "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "postCreateCommand": "corepack enable && pnpm install && pnpm typecheck",
  "forwardPorts": [8787, 8080],
  "remoteEnv": {
    "ANTHROPIC_API_KEY": "${localEnv:ANTHROPIC_API_KEY}"
  }
}
"""

CI_YML = '''\
name: CI
on:
  pull_request:
  push:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm typecheck
'''


def deploy_yml(env: str, on_block: str, needs_approval: bool) -> str:
    approval = f"    environment: {env}\n" if needs_approval else ""
    return f'''\
name: Deploy {env.title()}
on:
{on_block}
jobs:
  deploy:
    runs-on: ubuntu-latest
{approval}    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: {{ node-version: 22, cache: pnpm }}
      - run: pnpm install --frozen-lockfile

      - name: Deploy Worker
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{{{ secrets.CLOUDFLARE_API_TOKEN }}}}
          accountId: ${{{{ secrets.CLOUDFLARE_ACCOUNT_ID }}}}
          command: deploy --env {env}

      # TODO: 部署后跑评估集，硬指标失败则拦截
'''


# ── 生成 ──────────────────────────────────────────────────────


def write(root: pathlib.Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  {rel}")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 Agent 项目骨架")
    ap.add_argument("target", help="项目目录")
    ap.add_argument("--name", help="项目名（默认取目录名）")
    ap.add_argument("--stack", default="cloudflare", choices=["cloudflare"],
                    help="技术栈；其他栈的映射见 references/stacks.md")
    ap.add_argument("--no-devices", action="store_true", help="不生成设备接入层")
    ap.add_argument("--minimal", action="store_true",
                    help="单人项目：跳过 staging 与审批流，保留同构配置与迁移纪律")
    args = ap.parse_args()

    root = pathlib.Path(args.target).resolve()
    if root.exists() and any(root.iterdir()):
        sys.exit(f"目录非空：{root}\n请指定空目录，避免覆盖已有文件。")
    name = args.name or root.name

    print(f"生成 {name} → {root}\n")

    # 工作区
    write(root, "package.json", root_package_json(name))
    # allowBuilds 预先放行 wrangler 的原生依赖，否则首次 install 会中断要求确认
    write(root, "pnpm-workspace.yaml",
          'packages:\n  - "apps/*"\n  - "packages/*"\n\n'
          "allowBuilds:\n  esbuild: true\n  workerd: true\n  core-js-pure: true\n")

    # 契约层 —— 这是 seam 的核心，先立起来
    write(root, "packages/agent-kernel/package.json", KERNEL_PACKAGE_JSON)
    write(root, "packages/agent-kernel/tsconfig.json", tsconfig(False))
    write(root, "packages/agent-kernel/src/types.ts", KERNEL_TYPES)
    write(root, "packages/agent-kernel/src/tools.ts", KERNEL_TOOLS)
    write(root, "packages/agent-kernel/src/registry.ts", KERNEL_REGISTRY)
    write(root, "packages/agent-kernel/src/adapters/cf-agents.ts", ADAPTER_EDGE)
    write(root, "packages/agent-kernel/src/adapters/remote.ts", ADAPTER_REMOTE)

    # 边缘执行层 —— 含可运行的 DO 实现与失败关闭的工具回调
    write(root, "apps/agent-core/package.json", CORE_PACKAGE_JSON)
    write(root, "apps/agent-core/tsconfig.json", tsconfig(True))
    write(root, "apps/agent-core/src/index.ts", WORKER_INDEX)
    write(root, "apps/agent-core/wrangler.jsonc", wrangler_config(name, args.minimal))
    write(root, "apps/agent-core/.dev.vars.example",
          "ANTHROPIC_API_KEY=sk-ant-...\n"
          "# AGENT_FRAMEWORK=cf-agents\n"
          "# HEAVY_RUNNER_URL=http://localhost:8080\n"
          "# TOOL_CALLBACK_SECRET=...\n")

    # AGENTS.md 为主，CLAUDE.md 导入它 —— 同时兼容两套生态
    write(root, "AGENTS.md", AGENTS_MD.format(name=name))
    write(root, "CLAUDE.md", "@AGENTS.md\n")

    # 重执行层
    write(root, "apps/heavy-runner/main.py", RUNNER_MAIN)
    write(root, "apps/heavy-runner/requirements.txt", "fastapi>=0.115\nuvicorn>=0.32\n")

    # 评估集 —— 先于进化管线存在
    write(root, "evals/seed.jsonl", EVALSET)

    # CI
    write(root, ".github/workflows/ci.yml", CI_YML)
    if not args.minimal:
        write(root, ".github/workflows/deploy-staging.yml",
              deploy_yml("staging", "  push:\n    branches: [main]\n", False))
    write(root, ".github/workflows/deploy-prod.yml",
          deploy_yml("production", "  release:\n    types: [published]\n", not args.minimal))

    if not args.no_devices:
        write(root, "devices/README.md",
              "# 设备接入\n\n"
              "设备只做感知与执行，Agent 循环留在云端。\n"
              "连接串：`?role=device&dialect=<min|mcp>&device=<id>`\n\n"
              "协议与固件写法见 skill 的 references/edge-devices.md。\n")

    # 多主机部署：容器层的交付路径（边缘之外最容易被漏掉的一层）
    write(root, ".github/workflows/build-container.yml", BUILD_CONTAINER_YML)
    write(root, "deploy/pull-agent.sh", PULL_AGENT)
    (root / "deploy/pull-agent.sh").chmod(0o755)

    # 开发环境可移植：换机器不用重配
    write(root, ".devcontainer/devcontainer.json", DEVCONTAINER.replace("PROJECT_NAME", name))

    write(root, ".gitignore", "node_modules/\ndist/\n.wrangler/\n.dev.vars\n.env\n__pycache__/\n.venv/\n")

    print(f"\n完成。骨架可直接构建：")
    print(f"  cd {root} && pnpm install && pnpm typecheck")
    print("\n下一步（见 SKILL.md 的「搭建顺序」）：")
    print("  1. 部署到各环境跑通 CI —— 此时 Agent 还不会说话，但链路是通的")
    print("  2. 接线 packages/agent-kernel/src/adapters/cf-agents.ts（文件内有 TODO）")
    print("  3. 加工具：在 apps/agent-core/src/index.ts 的 allTools() 里加 provider")
    print("  4. 用真实 trace 替换 evals/seed.jsonl —— 内置的是占位样例，必须换成你的场景")
    print("\n未生成（需自行决定）：业务逻辑、数据库 schema、前端、生产资源 ID")


if __name__ == "__main__":
    main()
