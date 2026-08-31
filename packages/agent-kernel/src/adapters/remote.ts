import type { AgentAdapter, AgentTurnContext, AgentTurnResult } from "../types";

/**
 * 远程适配器：把这一轮转发给 heavy-runner 容器。
 *
 * 覆盖所有跑不进 Workers isolate 的框架 —— LangGraph(Python)、
 * Claude Agent SDK、Pi、DeepSeek Harness 等。边缘侧看到的仍是同一个契约，
 * 换哪个 Python 框架由 heavy-runner 内部的 FRAMEWORK 决定，
 * wrangler.jsonc 与 CI 完全不动。
 */
export function createRemoteAdapter(target: string): AgentAdapter {
  return {
    name: `remote:${target}`,
    runtime: "remote",

    async handle(ctx: AgentTurnContext): Promise<AgentTurnResult> {
      const base = ctx.env.HEAVY_RUNNER_URL;
      if (!base) {
        throw new Error(
          `AGENT_FRAMEWORK=remote:${target} 需要 HEAVY_RUNNER_URL，但它是空的。` +
            "本地开发可在 .dev.vars 里设为 http://localhost:8080。",
        );
      }

      const res = await fetch(`${base.replace(/\/$/, "")}/turn`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          framework: target,
          session_id: ctx.sessionId,
          message: ctx.message,
          history: ctx.history,
          memory: ctx.memory,
          skill_catalog: ctx.skillCatalog,
          // 工具的可调用部分（invoke）留在边缘：容器侧拿到声明后，
          // 需要执行时回调 /tools/invoke，设备与 MCP 连接因此不必在容器里重建。
          tools: Object.entries(ctx.tools).map(([name, t]) => ({
            name,
            description: t.description,
            input_schema: t.inputSchema,
            source: t.source,
          })),
        }),
      });

      if (!res.ok) {
        throw new Error(`heavy-runner 返回 ${res.status}: ${await res.text()}`);
      }

      const data = (await res.json()) as { reply?: string; memory?: string };
      if (typeof data.reply !== "string") {
        throw new Error("heavy-runner 响应缺少 reply 字段");
      }
      return { reply: data.reply, memory: data.memory };
    },
  };
}
