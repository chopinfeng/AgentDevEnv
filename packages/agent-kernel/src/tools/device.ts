import type { ToolDefinition, ToolProvider, ToolResult } from "./types";
import type { DeviceToolSpec } from "./types-device";
import type { DeviceDialect, InboundEvent } from "./dialects";

/**
 * 设备工具层 —— 让 ESP32 这类 MCU 成为 Agent 的"手和眼"。
 *
 * 核心取舍：**MCU 不做 Agent host。** 实测证据：ESP32-S3 上跑 260K 参数模型
 * 约 19 tok/s，作者自评"能跑但没什么用"；29M 参数约 9.5 tok/s。这个量级的模型
 * 没有指令跟随与工具调用能力。所以设备负责感知与执行，Agent 循环留在云端 ——
 * 这也是 xiaozhi-esp32（29.5k stars，目前唯一数万台规模验证的形态）的做法。
 *
 * 设备通过 WebSocket 挂到自己的 DO 实例上，能力暴露成工具。
 * 支持两种方言，见 dialects.ts。
 */

interface DeviceEntry {
  tools: DeviceToolSpec[];
  dialect: DeviceDialect;
}

interface Pending {
  resolve(r: ToolResult): void;
  timer: ReturnType<typeof setTimeout>;
}

/** 由 DO 外壳实现：把一帧文本发给指定设备 */
export interface DeviceTransport {
  send(deviceId: string, frame: string): void;
}

/**
 * 设备注册表：持有已连接设备的工具清单，并做调用/回执的配对。
 * 一个 DO 实例内可以挂多台设备，各自方言可以不同。
 */
export class DeviceRegistry implements ToolProvider {
  readonly source = "device" as const;

  private devices = new Map<string, DeviceEntry>();
  private pending = new Map<string, Pending>();
  private seq = 0;

  constructor(
    private transport: DeviceTransport,
    /** 设备无响应的超时，毫秒。MCU 可能在睡眠或掉线。 */
    private timeoutMs = 15_000,
  ) {}

  /** 设备上线或更新能力清单 */
  register(deviceId: string, tools: DeviceToolSpec[], dialect: DeviceDialect): void {
    this.devices.set(deviceId, { tools, dialect });
  }

  /** 设备掉线：清理并让所有在途调用立即失败，避免挂到超时 */
  unregister(deviceId: string): void {
    this.devices.delete(deviceId);
    for (const [key, p] of this.pending) {
      if (key.startsWith(`${deviceId}:`)) {
        clearTimeout(p.timer);
        p.resolve({ content: `设备 ${deviceId} 已断开`, isError: true });
        this.pending.delete(key);
      }
    }
  }

  /** 处理一条设备来帧。返回解析结果供外壳做落库等额外处理。 */
  handleFrame(deviceId: string, dialect: DeviceDialect, raw: string): InboundEvent {
    const ev = dialect.decode(raw);

    if (ev.kind === "tools") {
      this.register(deviceId, ev.tools, dialect);
    } else if (ev.kind === "result") {
      this.settle(deviceId, ev.callId, ev.ok, ev.data);
    }

    return ev;
  }

  private settle(deviceId: string, callId: string, ok: boolean, data: unknown): void {
    const key = `${deviceId}:${callId}`;
    const p = this.pending.get(key);
    if (!p) return; // 迟到的回执，已超时
    clearTimeout(p.timer);
    this.pending.delete(key);
    p.resolve({
      content: typeof data === "string" ? data : JSON.stringify(data ?? (ok ? "ok" : "failed")),
      isError: !ok,
    });
  }

  listDevices(): string[] {
    return [...this.devices.keys()];
  }

  listTools(): ToolDefinition[] {
    const out: ToolDefinition[] = [];
    for (const [deviceId, entry] of this.devices) {
      for (const spec of entry.tools) {
        out.push({
          // 设备名进工具名，避免两台同型号设备撞名
          name: `${deviceId}__${spec.name}`,
          description: `[设备 ${deviceId}] ${spec.description}`,
          inputSchema: spec.schema ?? { type: "object", properties: {} },
          source: "device",
          origin: deviceId,
          invoke: (args) => this.call(deviceId, spec.name, args),
        });
      }
    }
    return out;
  }

  private call(deviceId: string, tool: string, args: Record<string, unknown>): Promise<ToolResult> {
    const entry = this.devices.get(deviceId);
    if (!entry) {
      return Promise.resolve({ content: `设备 ${deviceId} 不在线`, isError: true });
    }

    const callId = String(++this.seq);
    const key = `${deviceId}:${callId}`;

    return new Promise<ToolResult>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(key);
        resolve({ content: `设备 ${deviceId} 响应超时（${this.timeoutMs}ms）`, isError: true });
      }, this.timeoutMs);

      this.pending.set(key, { resolve, timer });
      this.transport.send(deviceId, entry.dialect.encodeCall({ callId, tool, args }));
    });
  }
}

export type { DeviceToolSpec };
