/**
 * 框架中立的工具层。
 *
 * 工具用 **纯 JSON Schema** 描述，不绑定任何 SDK：
 *   - MCP 原生就用 JSON Schema
 *   - Vercel AI SDK 经 jsonSchema() 接收
 *   - Python 框架（LangGraph 等）直接吃 JSON Schema
 * 所以同一份工具集在任何 AGENT_FRAMEWORK 下都可用。
 */

/** 工具入参的 JSON Schema（object 类型） */
export interface ToolInputSchema {
  type: "object";
  properties?: Record<string, unknown>;
  required?: string[];
  [k: string]: unknown;
}

export type ToolSource = "builtin" | "mcp" | "device" | "skill";

export interface ToolResult {
  /** 回给模型的文本结果 */
  content: string;
  isError?: boolean;
}

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
  source: ToolSource;
  /** 来源标识：MCP serverId、设备 id 等，用于观测与排错 */
  origin?: string;
  invoke(args: Record<string, unknown>): Promise<ToolResult>;
}

/** 工具提供方。新增一类工具来源 = 加一个 provider，不动适配器。 */
export interface ToolProvider {
  readonly source: ToolSource;
  listTools(): Promise<ToolDefinition[]> | ToolDefinition[];
}

/** 交给适配器的工具集：名字 → 定义 */
export type ToolSet = Record<string, ToolDefinition>;
