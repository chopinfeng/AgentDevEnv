import type { ToolDefinition, ToolProvider } from "../tools/types";
import type { SkillMeta, SkillStore } from "./types";

/** 解析 SKILL.md 的 frontmatter —— R2 里存的是原始 markdown */
export function parseSkillMarkdown(raw: string): { meta: Partial<SkillMeta>; body: string } {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(raw);
  if (!m) return { meta: {}, body: raw.trim() };

  const meta: Partial<SkillMeta> = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^(\w+):\s*(.*)$/.exec(line.trim());
    if (!kv) continue;
    const value = kv[2].replace(/^["']|["']$/g, "");
    if (kv[1] === "name") meta.name = value;
    else if (kv[1] === "description") meta.description = value;
    else if (kv[1] === "version") meta.version = value;
    else if (kv[1] === "compatibility") meta.compatibility = value;
  }
  return { meta, body: raw.slice(m[0].length).trim() };
}

/**
 * 把多个 SkillStore 合成一个工具 provider。
 *
 * 只暴露一个 load_skill 工具 —— skill 正文不进系统提示，
 * 模型判断需要时才拉。清单（名字 + 描述）由 renderSkillCatalog 渲进提示。
 */
export class SkillProvider implements ToolProvider {
  readonly source = "skill" as const;

  constructor(private stores: SkillStore[]) {}

  async catalog(): Promise<SkillMeta[]> {
    const seen = new Set<string>();
    const out: SkillMeta[] = [];
    for (const store of this.stores) {
      for (const meta of await store.list()) {
        if (seen.has(meta.name)) continue; // 前面的 store 优先
        seen.add(meta.name);
        out.push(meta);
      }
    }
    return out;
  }

  listTools(): ToolDefinition[] {
    return [
      {
        name: "load_skill",
        description:
          "加载一个 skill 的完整说明。当手头任务匹配某个 skill 的描述时调用，" +
          "拿到步骤后再动手。参数 name 取自系统提示里的 skill 清单。",
        inputSchema: {
          type: "object",
          properties: { name: { type: "string", description: "skill 名称" } },
          required: ["name"],
        },
        source: "skill",
        invoke: async (args) => {
          const name = String(args.name ?? "").trim();
          for (const store of this.stores) {
            const skill = await store.get(name);
            if (skill) return { content: skill.body };
          }
          const available = (await this.catalog()).map((s) => s.name).join(", ");
          return { content: `没有名为 "${name}" 的 skill。可用：${available}`, isError: true };
        },
      },
    ];
  }
}

/** 渲进系统提示的 skill 清单 —— 只有名字和描述，正文按需加载 */
export function renderSkillCatalog(skills: SkillMeta[]): string {
  if (skills.length === 0) return "";
  const lines = skills.map((s) => `- ${s.name}：${s.description}`);
  return `\n<skills>\n以下能力可用 load_skill 加载完整说明：\n${lines.join("\n")}\n</skills>`;
}
