# 工具层与 MCP

Skills 相关内容独立在 `skills.md`，本文只讲工具层与 MCP 接入。

## 为什么用纯 JSON Schema

工具定义不绑任何 SDK，用纯 JSON Schema 描述。这不是洁癖，是唯一可行解：

- MCP 协议原生就用 JSON Schema
- Vercel AI SDK 经 `jsonSchema()` 接收
- Python 框架（LangGraph 等）直接吃 JSON Schema

绑了某个 SDK 的工具定义，换框架时要全部重写——工具往往是项目里最厚的一层，重写代价极高。

```ts
export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: { type: "object"; properties?: Record<string, unknown>; required?: string[] };
  source: "builtin" | "mcp" | "device" | "skill";
  origin?: string;                                    // MCP serverId / 设备 id，用于排错
  invoke(args: Record<string, unknown>): Promise<{ content: string; isError?: boolean }>;
}

export interface ToolProvider {
  readonly source: ToolSource;
  listTools(): Promise<ToolDefinition[]> | ToolDefinition[];
}
```

转换只发生在适配器内部（比如 AI SDK 适配器把它转成 `tool()`）。**加一类工具来源 = 加一个 provider，不动适配器，也不动 Agent 代码。**

## 汇总与容错

多个 provider 的工具合并时会撞名。策略：先到先得，后到者加来源前缀。设备工具还要加设备 id 前缀（`lamp-01__set_lamp`），否则两台同型号设备必然冲突。

工具执行失败**不应中断整个回合**——把异常转成模型可读的错误结果返回，让模型自己决定是重试还是换路径。

## MCP 接入

Cloudflare Agents SDK 自带多服务器 MCP 客户端：

```ts
async onStart() {                    // 冷启动与休眠恢复都会跑，连接放这里
  const result = await this.addMcpServer(name, url, {
    callbackHost: "https://your-worker.example.com",   // OAuth 回调地址，见下
    transport: { headers: { Authorization: "Bearer ..." } },
    retry: { maxAttempts: 3, baseDelayMs: 500 },
  });
}

this.mcp.listTools();     // 返回 MCP 原生 Tool，inputSchema 就是 JSON Schema
this.mcp.callTool({ name, arguments: args, serverId });
```

**用 `listTools()` 而不是 `getAITools()`** —— 后者已经绑成 AI SDK 形态，会把工具层锁死在一个 SDK 上，违背上面的分层。

### OAuth：接入外部 MCP 的第一个阻塞点

多数托管 MCP 服务器要求 OAuth。`addMcpServer` 会返回：

```ts
if (result.state === "authenticating") {
  // 服务端无法静默完成授权 —— 必须把 authUrl 交给用户去点
  return { needsAuth: true, authUrl: result.authUrl };
}
```

**这是架构决策，不是 API 细节**：授权流要有一侧承接。做无人值守的后台 Agent 时尤其要提前想清楚——没有用户在场点授权链接，就只能用长期 token 或改用不需要 OAuth 的服务器。

`callbackHost` 必须是外部可达的地址。**填 localhost 会让回调打不回来**，这个错误在本地开发时很常见且现象隐蔽。

### 传输层现状（2026-08 核实，出处见 sources.md）

- 标准 transport 只有 **stdio** 和 **Streamable HTTP**
- HTTP+SSE 双端点那套已废弃
- **WebSocket 不是官方 transport**，提案 SEP-1287/1288 已于 2026-06 关闭为 dormant，不会进规范
- 规范 2026-07-28 版**移除了 `initialize` 握手与协议级 session**，协议版本改为逐请求在 `params._meta` 里携带

接外部 MCP 服务器时用 Streamable HTTP 就对了。要在自有字节流上跑 MCP 是允许的（custom transport），但规范建议**复用 stdio 的换行分隔 JSON-RPC framing**，别自创一套。

## 工具回调

`remote:*` 框架下 Agent 循环在容器里，但设备连接与 MCP 连接活在边缘侧。容器执行工具时回调边缘：

```
POST /agents/<agent>/<session>/tools/invoke
Authorization: Bearer $TOOL_CALLBACK_SECRET
{ "tool": "lamp-01__set_lamp", "args": { "on": true } }
```

**鉴权是必须的**：这个端点能驱动物理设备、产生真实副作用。容器是内网服务但不能默认可信。

**生产环境未配密钥时应当直接拒绝服务（503），而不是放行。** 静默放行比报错危险得多——你不会发现它裸奔，直到出事。

```ts
if (secret) {
  if (auth !== `Bearer ${secret}`) return json({ error: "unauthorized" }, 401);
} else if (env.ENVIRONMENT === "production") {
  return json({ error: "生产环境必须配置 TOOL_CALLBACK_SECRET" }, 503);   // 失败关闭
}
```

同样的原则适用于设备接入端点，见 `edge-devices.md` 的「鉴权」。
