/**
 * 版本化 prompt 库 —— 进化管线（evolution/）的产物以 PR 形式回写本文件。
 * 规则：
 *  1. 只允许 CI（evolve.yml）或人工 PR 修改，禁止直接改生产。
 *  2. 每次改动必须递增 MAIN_AGENT_PROMPT_VERSION，评估门禁按版本对比回归。
 */
export const MAIN_AGENT_PROMPT_VERSION = "v0.1.0";

export const MAIN_AGENT_PROMPT = `你是 AgentDevEnv 的核心助理 Agent。

原则：
- 回答简洁、直接，中文优先。
- 不确定的事实要明确说不确定，不要编造。
- 涉及外部副作用的操作，先说明将要做什么。

<memory>
{{memory}}
</memory>`;

/** 渲染 prompt 模板 */
export function renderMainPrompt(memory: string): string {
  return MAIN_AGENT_PROMPT.replace("{{memory}}", memory || "（暂无长期记忆）");
}
