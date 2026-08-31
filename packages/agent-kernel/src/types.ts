import type { ChatMessage } from "@agentdev/shared";
import type { ToolSet } from "./tools/types";

/**
 * ─── 冻结契约 ───────────────────────────────────────────────
 * 本文件定义环境与框架之间的边界。切换 Agent 框架不得修改这里，
 * 也不得修改 wrangler.jsonc 的 bindings/migrations、Supabase schema
 * 或 .github/workflows —— 那些都属于"环境"。
 *
 * 分工：
 *   环境（DO 外壳）负责：会话持久化、记忆读写、路由、观测、部署
 *   框架（Adapter）负责：给定 消息 + 历史 + 记忆，产出回复
 * ──────────────────────────────────────────────────────────
 */

/** 适配器可见的环境变量子集 —— 所有适配器所需变量的并集，一次性声明 */
export interface AgentEnv {
  ENVIRONMENT: string;
  /** 选择框架：见 registry.ts 的 FRAMEWORKS */
  AGENT_FRAMEWORK?: string;
  ANTHROPIC_API_KEY: string;
  /** 走 Cloudflare AI Gateway 时设置 */
  AI_GATEWAY_BASE_URL?: string;
  /** remote 适配器转发目标（heavy-runner） */
  HEAVY_RUNNER_URL?: string;
}

/** 一次对话轮次的输入：由 DO 外壳从持久层组装后交给适配器 */
export interface AgentTurnContext {
  sessionId: string;
  message: string;
  /** 最近若干轮历史，时间正序 */
  history: ChatMessage[];
  /** 长期记忆摘要（记忆积累型进化的落点） */
  memory: string;
  /** 统一工具集：MCP + 设备 + skill，已由外壳汇总 */
  tools: ToolSet;
  /** 渲进系统提示的 skill 清单（仅名字与描述，正文按需加载） */
  skillCatalog: string;
  env: AgentEnv;
}

/** 适配器的输出：外壳负责把它写回持久层 */
export interface AgentTurnResult {
  reply: string;
  /** 适配器可选择更新长期记忆；不返回则保持原值 */
  memory?: string;
  /** 本轮实际调用过的工具名，用于观测与进化管线采样 */
  toolsUsed?: string[];
}

/**
 * Agent 框架适配器。实现这个接口即可接入任意框架，
 * 环境侧零改动。
 */
export interface AgentAdapter {
  readonly name: string;
  /** edge = 跑在 Workers isolate 内；remote = 转发到 heavy-runner 容器 */
  readonly runtime: "edge" | "remote";
  handle(ctx: AgentTurnContext): Promise<AgentTurnResult>;
}
