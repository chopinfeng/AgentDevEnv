import type { AgentAdapter, AgentTurnContext, AgentTurnResult } from "../types";

/**
 * 边缘原生备选：Mastra（Apache-2.0，官方有 CloudflareDeployer）。
 *
 * 未接线 —— 保留为可选项而非假实现。接入步骤：
 *   1. pnpm --filter @agentdev/agent-kernel add @mastra/core
 *   2. 在下方用 Mastra 的 Agent 构造并调用，把结果映射成 AgentTurnResult
 *   3. AGENT_FRAMEWORK=mastra
 * 环境侧（wrangler.jsonc / CI / Supabase）无需任何改动。
 */
export const mastraAdapter: AgentAdapter = {
  name: "mastra",
  runtime: "edge",

  async handle(_ctx: AgentTurnContext): Promise<AgentTurnResult> {
    throw new Error(
      "mastra 适配器尚未接线。见 packages/agent-kernel/src/adapters/mastra.ts 的接入步骤，" +
        "或把 AGENT_FRAMEWORK 切回 cf-agents。",
    );
  },
};
