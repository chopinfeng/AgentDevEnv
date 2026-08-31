import type { AgentNamespace } from "agents";
import type { AgentEnv } from "@agentdev/agent-kernel";
import type { MainAgent } from "./main-agent";

/**
 * 环境变量面 = 所有适配器所需变量的**并集**，一次性声明。
 * 这样切换 AGENT_FRAMEWORK 时无需增删 wrangler.jsonc 的 vars/secrets。
 */
export interface Env extends AgentEnv {
  MainAgent: AgentNamespace<MainAgent>;
  SUPABASE_URL: string;
  SUPABASE_SERVICE_KEY: string;
  /** heavy-runner 回调执行工具时的共享密钥；生产环境必填 */
  TOOL_CALLBACK_SECRET?: string;
}
