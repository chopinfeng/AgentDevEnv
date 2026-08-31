import { routeAgentRequest } from "agents";
import type { Env } from "./env";

export { MainAgent } from "./main-agent";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({ ok: true, environment: env.ENVIRONMENT });
    }

    // Agents SDK 路由：POST /agents/main-agent/:sessionId → MainAgent 实例
    const routed = await routeAgentRequest(request, env);
    return routed ?? Response.json({ error: "not found" }, { status: 404 });
  },
} satisfies ExportedHandler<Env>;
