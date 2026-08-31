import type { AgentAdapter, AgentEnv } from "./types";
import { cfAgentsAdapter } from "./adapters/cf-agents";
import { mastraAdapter } from "./adapters/mastra";
import { createRemoteAdapter } from "./adapters/remote";

/** 可选框架。切换 = 改 AGENT_FRAMEWORK 一个值，环境结构不动。 */
export const FRAMEWORKS = [
  "cf-agents", // 边缘原生，默认
  "mastra", // 边缘原生备选（待接线）
  "remote:langgraph", // 容器内 LangGraph
  "remote:claude-code", // 容器内 Claude Agent SDK
  "remote:pi", // 容器内 Pi
] as const;

export type FrameworkName = (typeof FRAMEWORKS)[number];

export const DEFAULT_FRAMEWORK: FrameworkName = "cf-agents";

/**
 * 按 env.AGENT_FRAMEWORK 解析出适配器。
 * 未设置时回落默认值；设了未知值则明确报错，不静默回落 ——
 * 否则一个拼写错误会让生产悄悄跑在另一个框架上。
 */
export function resolveAdapter(env: AgentEnv): AgentAdapter {
  const name = (env.AGENT_FRAMEWORK ?? DEFAULT_FRAMEWORK).trim();

  if (name === "cf-agents") return cfAgentsAdapter;
  if (name === "mastra") return mastraAdapter;

  if (name.startsWith("remote:")) {
    const target = name.slice("remote:".length);
    if (!target) throw new Error("AGENT_FRAMEWORK=remote: 缺少目标框架名");
    return createRemoteAdapter(target);
  }

  throw new Error(
    `未知的 AGENT_FRAMEWORK "${name}"。可选：${FRAMEWORKS.join(", ")}`,
  );
}
