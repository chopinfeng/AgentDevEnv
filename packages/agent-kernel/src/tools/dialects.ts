import type { DeviceToolSpec, ToolInputSchema } from "./types-device";

/**
 * 设备方言 —— 同一套设备工具层支持两种线协议。
 *
 * 背景（2026-08 核实）：
 *   - WebSocket **不是** MCP 官方 transport，且提案 SEP-1287/1288 已于 2026-06
 *     被关闭为 dormant，不会再进规范。所以任何"设备用 WebSocket 接 MCP"的做法，
 *     本质都是 MCP 规范允许的 **custom transport**，需要自己定义 framing。
 *   - MCP 规范建议：跑在可靠双向字节流上的 custom transport SHOULD 复用 stdio 的
 *     换行分隔 JSON-RPC framing。两种方言都按一帧一行 JSON 走，符合这条建议。
 *
 * 两种方言的取舍：
 *   min —— 自定义极简帧。ESP32 固件约 200 行，无需实现 JSON-RPC 与 schema 协商。
 *          代价是非标准，只能连本系统。适合传感器、执行器这类窄能力设备。
 *   mcp —— MCP JSON-RPC 包在信封里（xiaozhi-esp32 同款做法，也是目前唯一有
 *          数万台规模验证的形态）。设备是 MCP Server，云端是 MCP Client。
 *          适合已经在跑 Espressif mcp-c-sdk 或小智固件的设备。
 */

export type DialectName = "min" | "mcp";

/** 云端要发给设备的一次工具调用 */
export interface OutboundCall {
  callId: string;
  tool: string;
  args: Record<string, unknown>;
}

/** 从设备帧里解析出的事件 */
export type InboundEvent =
  | { kind: "tools"; tools: DeviceToolSpec[] }
  | { kind: "result"; callId: string; ok: boolean; data: unknown }
  | { kind: "event"; name: string; data: unknown }
  | { kind: "ignore" };

export interface DeviceDialect {
  readonly name: DialectName;
  /** 连接建立后要主动发的帧（mcp 方言需要发 tools/list 去拉清单） */
  onOpen(): string[];
  /** 把一次工具调用编码成设备帧 */
  encodeCall(call: OutboundCall): string;
  /** 解析设备发来的一帧 */
  decode(raw: string): InboundEvent;
}

// ── min：自定义极简方言 ──────────────────────────────────────

export const minDialect: DeviceDialect = {
  name: "min",
  onOpen: () => [], // 设备主动发 hello，云端不用问

  encodeCall: (call) =>
    JSON.stringify({ t: "invoke", id: call.callId, tool: call.tool, args: call.args }),

  decode(raw) {
    let m: Record<string, unknown>;
    try {
      m = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return { kind: "ignore" };
    }

    if (m.t === "hello") {
      return { kind: "tools", tools: (m.tools as DeviceToolSpec[]) ?? [] };
    }
    if (m.t === "result") {
      return { kind: "result", callId: String(m.id), ok: m.ok !== false, data: m.data };
    }
    if (m.t === "event") {
      return { kind: "event", name: String(m.name), data: m.data };
    }
    return { kind: "ignore" };
  },
};

// ── mcp：JSON-RPC 信封方言（xiaozhi 兼容） ───────────────────

/** 信封形状：{ type:"mcp", payload:{ jsonrpc:"2.0", ... } } */
function envelope(payload: Record<string, unknown>): string {
  return JSON.stringify({ type: "mcp", payload: { jsonrpc: "2.0", ...payload } });
}

/** tools/list 用固定 id，方便识别清单回执 */
const LIST_ID = "tools-list";

export const mcpDialect: DeviceDialect = {
  name: "mcp",

  // 云端是 MCP Client：连上就问设备有哪些工具。
  // 注意：现行 MCP 规范（2026-07-28）已移除 initialize 握手，
  // 所以这里直接发 tools/list，不做握手。
  onOpen: () => [envelope({ id: LIST_ID, method: "tools/list", params: {} })],

  encodeCall: (call) =>
    envelope({
      id: call.callId,
      method: "tools/call",
      params: { name: call.tool, arguments: call.args },
    }),

  decode(raw) {
    let outer: Record<string, unknown>;
    try {
      outer = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return { kind: "ignore" };
    }
    if (outer.type !== "mcp") return { kind: "ignore" };

    const p = outer.payload as Record<string, unknown> | undefined;
    if (!p) return { kind: "ignore" };

    // 设备主动发的通知（无 id）
    if (p.method === "notifications/message" || p.method === "notifications/event") {
      const params = (p.params ?? {}) as Record<string, unknown>;
      return { kind: "event", name: String(params.name ?? p.method), data: params.data };
    }

    const id = p.id === undefined ? undefined : String(p.id);
    if (id === undefined) return { kind: "ignore" };

    // tools/list 的回执 → 工具清单
    if (id === LIST_ID) {
      const result = (p.result ?? {}) as { tools?: Array<Record<string, unknown>> };
      const tools: DeviceToolSpec[] = (result.tools ?? []).map((t) => ({
        name: String(t.name),
        description: String(t.description ?? t.name),
        schema: (t.inputSchema as ToolInputSchema | undefined) ?? undefined,
      }));
      return { kind: "tools", tools };
    }

    // tools/call 的回执
    if (p.error) {
      const err = p.error as { message?: string };
      return { kind: "result", callId: id, ok: false, data: err.message ?? "device error" };
    }

    const result = (p.result ?? {}) as {
      content?: Array<{ type: string; text?: string }>;
      isError?: boolean;
    };
    const text = (result.content ?? [])
      .map((c) => (c.type === "text" ? (c.text ?? "") : `[${c.type}]`))
      .join("\n");
    return { kind: "result", callId: id, ok: result.isError !== true, data: text };
  },
};

export function resolveDialect(name: string | null | undefined): DeviceDialect {
  return name === "mcp" ? mcpDialect : minDialect;
}
