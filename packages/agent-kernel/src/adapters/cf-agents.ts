import { generateText, jsonSchema, tool, stepCountIs, type ToolSet as AiToolSet } from "ai";
import { createAnthropic } from "@ai-sdk/anthropic";
import { renderMainPrompt } from "@agentdev/prompts";
import type { AgentAdapter, AgentTurnContext, AgentTurnResult } from "../types";
import type { ToolSet } from "../tools/types";

/**
 * 把框架中立的 ToolSet 转成 AI SDK 的工具格式。
 * 转换只发生在这里 —— 工具层本身不依赖任何 SDK，
 * 所以换框架时工具集原样可用。
 */
function toAiTools(tools: ToolSet, used: string[]): AiToolSet {
  const out: AiToolSet = {};
  for (const [name, def] of Object.entries(tools)) {
    out[name] = tool({
      description: def.description,
      inputSchema: jsonSchema<Record<string, unknown>>(def.inputSchema as never),
      execute: async (args) => {
        used.push(name);
        const result = await def.invoke((args ?? {}) as Record<string, unknown>);
        return result.content;
      },
    });
  }
  return out;
}

/**
 * 边缘原生适配器：Cloudflare Agents SDK + Vercel AI SDK。
 * 默认选项 —— 全程跑在 Workers isolate 内，无额外网络跳数。
 */
export const cfAgentsAdapter: AgentAdapter = {
  name: "cf-agents",
  runtime: "edge",

  async handle(ctx: AgentTurnContext): Promise<AgentTurnResult> {
    const anthropic = createAnthropic({
      apiKey: ctx.env.ANTHROPIC_API_KEY,
      ...(ctx.env.AI_GATEWAY_BASE_URL ? { baseURL: ctx.env.AI_GATEWAY_BASE_URL } : {}),
    });

    const used: string[] = [];
    const aiTools = toAiTools(ctx.tools, used);

    const { text } = await generateText({
      model: anthropic("claude-sonnet-5"),
      system: renderMainPrompt(ctx.memory) + ctx.skillCatalog,
      messages: ctx.history.map((m) => ({
        role: m.role === "assistant" ? ("assistant" as const) : ("user" as const),
        content: m.content,
      })),
      ...(Object.keys(aiTools).length > 0
        ? // 允许多轮工具调用：加载 skill 后可能还要接着调设备工具
          { tools: aiTools, stopWhen: stepCountIs(8) }
        : {}),
    });

    return { reply: text, toolsUsed: used };
  },
};
