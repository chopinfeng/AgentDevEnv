import { Agent, type Connection, type ConnectionContext, type WSMessage } from "agents";
import {
  DeviceRegistry,
  SkillProvider,
  bundledSkills,
  collectTools,
  invokeTool,
  renderSkillCatalog,
  resolveAdapter,
  resolveDialect,
  type DeviceDialect,
  type ToolDefinition,
  type ToolProvider,
} from "@agentdev/agent-kernel";
import { MAIN_AGENT_PROMPT_VERSION } from "@agentdev/prompts";
import type { AgentStateSnapshot, ChatMessage, ChatRequest, ChatResponse } from "@agentdev/shared";
import type { Env } from "./env";

/** 设备连接的标签 —— 用它把设备连接和普通客户端连接区分开 */
const DEVICE_TAG = "device";

/**
 * MainAgent = Durable Object + 内置 SQLite —— 这是**环境**，不随框架变。
 *
 * 三类职责，都属于环境侧，切换 AGENT_FRAMEWORK 时不动：
 *   1. 会话持久化与记忆读写
 *   2. 设备接入：ESP32 等 MCU 用 WebSocket 挂上来，能力暴露成工具
 *   3. 工具汇总：MCP 服务器 + 设备 + skills → 统一 ToolSet 交给适配器
 *
 * 设备连接支持 hibernation：ESP32 挂着长连接空闲时 DO 可休眠，不产生计算费用，
 * 有消息时自动唤醒。这是 MCU 常驻在线的关键 —— 否则一直挂着会一直计费。
 */
export class MainAgent extends Agent<Env, AgentStateSnapshot> {
  initialState: AgentStateSnapshot = { turns: 0, memory: "" };

  /** 设备注册表。transport 直接写回对应的 WebSocket 连接。 */
  private devices = new DeviceRegistry({
    send: (deviceId: string, frame: string) => {
      for (const conn of this.getConnections(DEVICE_TAG)) {
        if (this.connMeta(conn)?.deviceId === deviceId) {
          conn.send(frame);
          return;
        }
      }
    },
  });

  private skills = new SkillProvider([bundledSkills]);

  // ── 设备接入 ────────────────────────────────────────────────

  /**
   * 标签随连接持久化，DO 从休眠恢复后仍能认出这是设备连接。
   * 这点对 MCU 很关键：ESP32 挂着长连接空闲时 DO 可以休眠不计费，
   * 有帧到达时自动唤醒，连接和标签都还在。
   */
  getConnectionTags(_connection: Connection, context: ConnectionContext): string[] {
    const url = new URL(context.request.url);
    return url.searchParams.get("role") === "device" ? [DEVICE_TAG] : [];
  }

  private connMeta(conn: Connection): { deviceId?: string; dialect?: string } | null {
    return (conn.state as { deviceId?: string; dialect?: string } | null) ?? null;
  }

  private dialectOf(conn: Connection): DeviceDialect {
    return resolveDialect(this.connMeta(conn)?.dialect);
  }

  async onConnect(connection: Connection, context: ConnectionContext): Promise<void> {
    if (!connection.tags.includes(DEVICE_TAG)) return;

    const url = new URL(context.request.url);
    const deviceId = url.searchParams.get("device") ?? connection.id;
    const dialectName = url.searchParams.get("dialect") ?? "min";

    // 设备身份与方言存进连接状态，随 hibernation 一起持久化
    connection.setState({ deviceId, dialect: dialectName });

    // mcp 方言下云端是 MCP Client，连上就发 tools/list 拉能力清单；
    // min 方言下设备会主动发 hello，这里没有要发的帧。
    for (const frame of resolveDialect(dialectName).onOpen()) {
      connection.send(frame);
    }
  }

  async onMessage(connection: Connection, message: WSMessage): Promise<void> {
    if (!connection.tags.includes(DEVICE_TAG)) return;
    if (typeof message !== "string") return;

    const meta = this.connMeta(connection);
    if (!meta?.deviceId) return;

    const ev = this.devices.handleFrame(meta.deviceId, this.dialectOf(connection), message);

    if (ev.kind === "event") {
      // 设备主动上报（按钮、传感器越限）。落库供后续对话与进化管线取用。
      this.sql`CREATE TABLE IF NOT EXISTS device_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device TEXT NOT NULL, name TEXT NOT NULL, data TEXT, ts INTEGER NOT NULL
      )`;
      this.sql`INSERT INTO device_events (device, name, data, ts)
        VALUES (${meta.deviceId}, ${ev.name}, ${JSON.stringify(ev.data ?? null)}, ${Date.now()})`;
    }
  }

  async onClose(connection: Connection): Promise<void> {
    const deviceId = this.connMeta(connection)?.deviceId;
    if (deviceId) this.devices.unregister(deviceId);
  }

  // ── 工具汇总 ────────────────────────────────────────────────

  /** MCP 服务器的工具：从已连接的 MCP 连接读清单，调用时转发 */
  private mcpProvider(): ToolProvider {
    return {
      source: "mcp",
      listTools: (): ToolDefinition[] =>
        this.mcp.listTools().map((t) => ({
          name: t.name,
          description: t.description ?? t.name,
          inputSchema: (t.inputSchema ?? { type: "object", properties: {} }) as ToolDefinition["inputSchema"],
          source: "mcp" as const,
          origin: t.serverId,
          invoke: async (args) => {
            const res = (await this.mcp.callTool({
              name: t.name,
              arguments: args,
              serverId: t.serverId,
            })) as { content?: Array<{ type: string; text?: string }>; isError?: boolean };
            const text = (res.content ?? [])
              .map((c) => (c.type === "text" ? (c.text ?? "") : `[${c.type}]`))
              .join("\n");
            return { content: text, isError: res.isError === true };
          },
        })),
    };
  }

  /** 内建工具：查看当前挂了哪些设备 */
  private builtinProvider(): ToolProvider {
    return {
      source: "builtin",
      listTools: (): ToolDefinition[] => [
        {
          name: "list_devices",
          description: "列出当前在线的设备及其可用能力。设备相关的问题先调它确认在线状态。",
          inputSchema: { type: "object", properties: {} },
          source: "builtin",
          invoke: async () => {
            const ids = this.devices.listDevices();
            return {
              content: ids.length ? `在线设备：${ids.join(", ")}` : "当前没有设备在线。",
            };
          },
        },
      ],
    };
  }

  /** 汇总当前全部可用工具 —— 对话与工具回调共用同一份来源 */
  private allTools() {
    return collectTools([
      this.builtinProvider(),
      this.mcpProvider(),
      this.devices,
      this.skills,
    ]);
  }

  /**
   * 供 heavy-runner 回调执行工具。
   *
   * 鉴权：容器是内网服务但不能默认可信 —— 这个端点能驱动物理设备。
   * 配置了 TOOL_CALLBACK_SECRET 就强制校验；没配置则只在非生产环境放行，
   * 避免生产上因为忘了配密钥而裸奔。
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

    const result = await invokeTool(await this.allTools(), tool, args ?? {});
    return Response.json(result);
  }

  // ── 对话 ────────────────────────────────────────────────────

  async onRequest(request: Request): Promise<Response> {
    if (request.method !== "POST") {
      return Response.json({ error: "POST { message } to chat" }, { status: 405 });
    }

    // 工具回调：remote 适配器下 Agent 循环在容器里，需要执行工具时回调这里。
    // 设备连接与 MCP 连接都活在 DO 内，不必也不该在容器里重建。
    if (new URL(request.url).pathname.endsWith("/tools/invoke")) {
      return this.handleToolInvoke(request);
    }

    const { message } = (await request.json()) as ChatRequest;
    if (!message?.trim()) {
      return Response.json({ error: "message is required" }, { status: 400 });
    }

    this.sql`CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      ts INTEGER NOT NULL
    )`;
    this.sql`INSERT INTO messages (role, content, ts) VALUES ('user', ${message}, ${Date.now()})`;

    const history = this.sql<{ role: string; content: string; ts: number }>`
      SELECT role, content, ts FROM messages ORDER BY id DESC LIMIT 20
    `.reverse();

    const tools = await this.allTools();

    const adapter = resolveAdapter(this.env);
    const result = await adapter.handle({
      sessionId: this.name,
      message,
      history: history as ChatMessage[],
      memory: this.state.memory,
      tools,
      skillCatalog: renderSkillCatalog(await this.skills.catalog()),
      env: this.env,
    });

    this.sql`INSERT INTO messages (role, content, ts) VALUES ('assistant', ${result.reply}, ${Date.now()})`;
    this.setState({
      turns: this.state.turns + 1,
      memory: result.memory ?? this.state.memory,
    });

    const body: ChatResponse = {
      reply: result.reply,
      turns: this.state.turns,
      environment: this.env.ENVIRONMENT,
      framework: adapter.name,
      promptVersion: MAIN_AGENT_PROMPT_VERSION,
      tools: Object.keys(tools),
      toolsUsed: result.toolsUsed ?? [],
      devices: this.devices.listDevices(),
    };
    return Response.json(body);
  }
}
