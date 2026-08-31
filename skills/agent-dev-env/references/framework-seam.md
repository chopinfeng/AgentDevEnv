# 框架 seam：让 Agent 框架成为可换件

## 为什么需要这层

Agent 框架的迭代速度远快于部署底座。今天选的框架，半年后可能有更合适的；而 DO 绑定、数据库 schema、CI 流水线一旦定了就不该跟着晃。

没有这层的典型后果：换框架变成重写项目，于是没人敢换，最后被锁死在一个过时的框架上。

## 边界怎么划

**关键在于把持久化留在环境侧，框架只做纯计算。**

| 环境侧（不变） | 框架侧（可换） |
|---|---|
| 会话历史读写 | 组织提示词 |
| 长期记忆存取 | 调用模型 |
| 路由与鉴权 | 工具调用循环 |
| 工具集汇总 | 决定何时收敛 |
| 部署配置、数据库 schema | —— |

框架拿到的是「消息 + 历史 + 记忆 + 工具集」，返回「回复 + 可选的记忆更新」。它不碰存储，所以换掉它不影响任何持久化状态。

## 契约

```ts
export interface AgentTurnContext {
  sessionId: string;
  message: string;
  history: ChatMessage[];      // 时间正序
  memory: string;              // 长期记忆摘要
  tools: ToolSet;              // 已汇总，见 tools-and-mcp.md
  skillCatalog: string;        // 渲进提示的 skill 清单
  env: AgentEnv;
}

export interface AgentTurnResult {
  reply: string;
  memory?: string;             // 不返回则保持原值
  toolsUsed?: string[];        // 供观测与评估采样
}

export interface AgentAdapter {
  readonly name: string;
  readonly runtime: "edge" | "remote";
  handle(ctx: AgentTurnContext): Promise<AgentTurnResult>;
}
```

## 注册表

```ts
export const FRAMEWORKS = ["cf-agents", "mastra", "remote:langgraph", "remote:claude-code"] as const;

export function resolveAdapter(env: AgentEnv): AgentAdapter {
  const name = (env.AGENT_FRAMEWORK ?? DEFAULT_FRAMEWORK).trim();

  if (name === "cf-agents") return cfAgentsAdapter;
  if (name === "mastra") return mastraAdapter;
  if (name.startsWith("remote:")) return createRemoteAdapter(name.slice(7));

  // 不静默回落 —— 一个拼写错误会让生产悄悄跑在另一个框架上
  throw new Error(`未知的 AGENT_FRAMEWORK "${name}"。可选：${FRAMEWORKS.join(", ")}`);
}
```

**响应体回显实际服务的适配器名**，用来确认切换生效。没有这个字段，"切换了但没生效"很难发现。

## 冻结清单

换框架时以下内容一律不动。把它写进 README，让后来的人知道边界在哪：

- 有状态运行时的类名与迁移标签（改了会触发数据迁移）
- 路由形状与请求/响应类型
- 环境变量面——**声明所有适配器所需变量的并集**，即使当前框架用不到也留着空值。否则换框架时还得改配置，seam 就白留了
- 数据库 schema、CI 工作流、密钥名

## 跑不进边缘的框架

Python 框架和长驻进程进不了边缘 isolate。**不必为它们写边缘适配器**——用一个 `remote` 适配器转发到容器，容器内再按名字分发：

```
边缘 Worker                     容器
  remote:langgraph  ──POST /turn──►  FRAMEWORKS["langgraph"]
  remote:claude-code ─────────────►  FRAMEWORKS["claude-code"]
```

两侧共用同一份 `/turn` 契约。这样从边缘框架切到 Python 框架，部署配置同样不动。

**工具怎么办**：设备连接和 MCP 连接活在边缘侧，不该在容器里重建。做法是边缘把工具**声明**（名字 + 描述 + JSON Schema）传给容器，容器需要执行时回调边缘的工具端点。见 `tools-and-mcp.md` 的「工具回调」。

## 什么时候可以跳过这层

- 一次性 demo、POC
- 明确只用一个框架且不打算换

但注意：事后补这层的成本远高于一开始就留。判断标准是「这个项目会活过三个月吗」——会的话就留着。
