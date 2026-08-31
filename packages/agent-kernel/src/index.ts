export type {
  AgentAdapter,
  AgentEnv,
  AgentTurnContext,
  AgentTurnResult,
} from "./types";
export {
  FRAMEWORKS,
  DEFAULT_FRAMEWORK,
  resolveAdapter,
  type FrameworkName,
} from "./registry";
export { cfAgentsAdapter } from "./adapters/cf-agents";
export { mastraAdapter } from "./adapters/mastra";
export { createRemoteAdapter } from "./adapters/remote";

// 工具层（框架中立）
export type {
  ToolDefinition,
  ToolInputSchema,
  ToolProvider,
  ToolResult,
  ToolSet,
  ToolSource,
} from "./tools/types";
export { collectTools, invokeTool, summarizeTools } from "./tools/registry";
export { DeviceRegistry, type DeviceToolSpec, type DeviceTransport } from "./tools/device";
export {
  minDialect,
  mcpDialect,
  resolveDialect,
  type DeviceDialect,
  type DialectName,
  type InboundEvent,
} from "./tools/dialects";

// Skills（遵循 agentskills.io 开放规范）
export type { Skill, SkillMeta, SkillStore } from "./skills/types";
export { validateSkillMeta, validateSkillName } from "./skills/types";
export { bundledSkills } from "./skills/bundled";
export { createR2SkillStore, type SkillBucket } from "./skills/r2";
export { SkillProvider, parseSkillMarkdown, renderSkillCatalog } from "./skills/loader";
