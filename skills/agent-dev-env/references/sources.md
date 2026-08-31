# 事实来源

skill 里的判断依据。核实于 2026-08/09。**引用前请注意时效** —— 协议与框架都在快速变化，超过半年建议重新核实。

## 规范

| 主题 | 来源 |
|---|---|
| Agent Skills 规范 | https://agentskills.io/specification |
| Skills 校验工具 | https://github.com/agentskills/agentskills/tree/main/skills-ref |
| MCP 传输层（当前版本 2026-07-28） | https://modelcontextprotocol.io/specification/2026-07-28/basic/transports |
| MCP 版本策略 | https://modelcontextprotocol.io/specification/versioning |
| WebSocket transport 提案（已关闭为 dormant） | https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1288 |

**MCP 2026-07-28 的破坏性变更**（对接旧设备时必须注意）：移除 `initialize` 握手、移除协议级 session、移除 GET SSE 流；协议版本改为逐请求在 `params._meta` 里携带。标准 transport 只剩 stdio 与 Streamable HTTP，HTTP+SSE 双端点那套已废弃。

## 平台

| 主题 | 来源 |
|---|---|
| Cloudflare Agents SDK | https://developers.cloudflare.com/agents/ |
| MCP client / server API | https://developers.cloudflare.com/agents/api-reference/mcp-client-api/ |
| Sandbox 内跑 Claude Code | https://developers.cloudflare.com/sandbox/tutorials/claude-code/ |
| Claude Managed Agents on Cloudflare | https://blog.cloudflare.com/claude-managed-agents/ |

## 设备能力实测

| 结论 | 来源 |
|---|---|
| ESP32-S3 上 260K 参数模型约 19 tok/s，作者自评"能跑但没什么用" | https://github.com/DaveBben/esp32-llm |
| 29M 参数模型约 9.5 tok/s（逐层从 Flash 流式读取） | https://www.hackster.io/news/running-a-28-9m-parameter-llm-on-an-8-microcontroller-173f1f370708 |
| Pi 5 + Ollama：1–1.5B 约 10–12 tok/s，3B 类 4–6 tok/s 且长 prompt 超时 | https://www.stratosphereips.org/blog/2025/6/5/how-well-do-llms-perform-on-a-raspberry-pi-5 |
| xiaozhi-esp32 架构（设备=MCP Server、云端=MCP Client） | https://github.com/78/xiaozhi-esp32/blob/main/docs/mcp-protocol.md |
| Espressif 官方 mcp-c-sdk（默认协议 2025-11-25，落后一版） | https://components.espressif.com/components/espressif/mcp-c-sdk |

ESP32 典型规格：ESP32 约 520KB SRAM，ESP32-C3 约 400KB，ESP32-S3 约 512KB + 模组常见 8MB PSRAM。

## 工程化实践

| 主题 | 来源 |
|---|---|
| AWS Well-Architected Agentic AI Lens（最接近「上线清单」的成体系文档，成熟度模型基本厂商中立） | https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentic-ai-lens.html |
| Anthropic《Building Effective Agents》（workflow vs agent、五个编排模式） | https://www.anthropic.com/engineering/building-effective-agents |
| 上下文工程（just-in-time 加载、结构化笔记） | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents |
| 上下文管理实测数字 | https://claude.com/blog/context-management |
| Prompt caching（阈值与失效层级，**数字以此为准**） | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| LangGraph interrupt/resume 的四个坑 | https://docs.langchain.com/oss/python/langgraph/interrupts |
| 轨迹评估（trajectory evaluators 四种匹配模式） | https://docs.langchain.com/langsmith/trajectory-evals |
| Prompt 版本治理（不可变版本 + 标签指针） | https://langfuse.com/resources/engineering/prompt-cicd |
| 幂等键语义（失败响应也要缓存） | https://docs.stripe.com/api/idempotent_requests |
| LLM-as-judge 的三类偏差（原始出处） | https://arxiv.org/abs/2306.05685 |
| 评估误差棒与功效分析 | https://arxiv.org/abs/2411.00640 |
| 评估噪声分解（同题多采样 > 加样本量） | https://arxiv.org/abs/2512.21326 |
| OWASP Top 10 for LLM Applications | https://genai.owasp.org/llm-top-10/ |
| Anthropic 评估与 rubric 指引 | https://docs.claude.com/en/docs/test-and-evaluate/develop-tests |

## 规范治理的一点提醒

**Agent Skills 目前不在 Linux Foundation / Agentic AI Foundation 的治理之下**（MCP、AGENTS.md、goose 在），仍由 Anthropic 主导。厂商采用面很广（约 47 家客户端），但跨厂商可移植性靠厂商自觉，不是标准组织担保的。给用户做长期技术选型建议时，这一点应当说明。

另：Claude Code 支持一批规范之外的 frontmatter 字段（`context: fork`、`paths`、`hooks` 等）。用了会让 skill 在其他客户端上出现未知字段——追求可移植就只用规范定义的 6 个字段。

## 进化框架

| 机制 | 代表项目 |
|---|---|
| 提示词优化 | https://github.com/stanfordnlp/dspy · https://github.com/gepa-ai/gepa |
| 代码进化 | https://github.com/algorithmicsuperintelligence/openevolve |
| 记忆积累 | https://github.com/letta-ai/letta |
| RL 训练 | https://github.com/microsoft/agent-lightning |
| 自进化工作流 | https://github.com/EvoAgentX/EvoAgentX |

综述（用于系统了解这个方向）：
- https://arxiv.org/abs/2508.07407 —— Self-Evolving AI Agents 综述
- https://arxiv.org/abs/2507.21046 —— What/When/How/Where to Evolve

## 未核实

以下说法流传较广但我没能在一手来源确认，引用时请自行核实：

- Espressif `mcp-c-sdk` 的实际 RAM/Flash 占用（官方 README 无数据）
- Raspberry Pi AI HAT+ 2 的实际 LLM 吞吐（官方未公布 token/s）
- MCP 规范中是否存在 JSON-RPC 消息大小上限（未找到 MUST 级约束）
- 是否存在 CoAP 上承载 MCP 的方案（未找到）
