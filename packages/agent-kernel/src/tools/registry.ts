import type { ToolDefinition, ToolProvider, ToolResult, ToolSet } from "./types";

/**
 * 汇总多个 provider 的工具集。
 * 名字冲突时按 provider 顺序先到先得，后到者加来源前缀，避免互相覆盖。
 */
export async function collectTools(providers: ToolProvider[]): Promise<ToolSet> {
  const set: ToolSet = {};

  for (const provider of providers) {
    const tools = await provider.listTools();
    for (const tool of tools) {
      const key = set[tool.name] ? `${tool.source}_${tool.name}` : tool.name;
      set[key] = tool;
    }
  }

  return set;
}

/** 调用工具并把异常转成模型可读的错误结果 —— 工具报错不应中断整个回合 */
export async function invokeTool(
  tools: ToolSet,
  name: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const tool = tools[name];
  if (!tool) {
    return { content: `未知工具 "${name}"。可用：${Object.keys(tools).join(", ")}`, isError: true };
  }
  try {
    return await tool.invoke(args);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { content: `工具 ${name} 执行失败：${msg}`, isError: true };
  }
}

/** 按来源分组统计，用于观测与调试 */
export function summarizeTools(tools: ToolSet): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const tool of Object.values(tools)) {
    counts[tool.source] = (counts[tool.source] ?? 0) + 1;
  }
  return counts;
}

export type { ToolDefinition, ToolProvider, ToolResult, ToolSet };
