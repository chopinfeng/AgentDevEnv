export type Role = "user" | "assistant" | "system";

export interface ChatMessage {
  role: Role;
  content: string;
  ts: number;
}

export interface AgentStateSnapshot {
  /** 累计对话轮数，用于观测与进化管线采样 */
  turns: number;
  /** Agent 长期记忆摘要（记忆积累型进化的落点） */
  memory: string;
}

export interface ChatRequest {
  message: string;
}

export interface ChatResponse {
  reply: string;
  turns: number;
  environment: string;
  /** 本轮实际服务的框架适配器 —— 用来确认切换是否生效 */
  framework: string;
  promptVersion: string;
  /** 本轮可用的工具名（MCP + 设备 + skill） */
  tools: string[];
  /** 本轮实际调用过的工具 */
  toolsUsed: string[];
  /** 当前在线的设备 */
  devices: string[];
}
