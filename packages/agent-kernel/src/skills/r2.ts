import { parseSkillMarkdown } from "./loader";
import { validateSkillMeta, type Skill, type SkillMeta, type SkillStore } from "./types";

/** R2 桶的最小接口 —— 只声明用到的部分，免得 kernel 依赖 Workers 类型 */
export interface SkillBucket {
  list(opts?: { prefix?: string }): Promise<{ objects: Array<{ key: string }> }>;
  get(key: string): Promise<{ text(): Promise<string> } | null>;
}

/**
 * R2 里的动态 skill —— 进化管线产出的候选先落这里，验证后再由 PR 固化进 bundled。
 *
 * 布局遵循 Agent Skills 规范：每个 skill 一个目录，正文是 SKILL.md。
 *   skills/<name>/SKILL.md
 *
 * 清单做了缓存：list() 要读每个 SKILL.md 的 frontmatter，
 * 每轮对话都全量拉一遍 R2 太贵。
 */
export function createR2SkillStore(bucket: SkillBucket, prefix = "skills/"): SkillStore {
  let cache: SkillMeta[] | null = null;

  return {
    kind: "r2",

    async list(): Promise<SkillMeta[]> {
      if (cache) return cache;

      const { objects } = await bucket.list({ prefix });
      const metas: SkillMeta[] = [];

      for (const obj of objects) {
        if (!obj.key.endsWith("/SKILL.md")) continue;
        const body = await bucket.get(obj.key);
        if (!body) continue;

        const { meta } = parseSkillMarkdown(await body.text());
        // 规范要求 name 与目录名一致；以目录名为准，避免 frontmatter 写错导致取不到
        const dirName = obj.key.slice(prefix.length, -"/SKILL.md".length);
        const candidate = { ...meta, name: meta.name ?? dirName };

        if (validateSkillMeta(candidate)) continue; // 不合规的跳过，不让它污染清单
        metas.push(candidate as SkillMeta);
      }

      cache = metas;
      return metas;
    },

    async get(name: string): Promise<Skill | undefined> {
      const obj = await bucket.get(`${prefix}${name}/SKILL.md`);
      if (!obj) return undefined;

      const raw = await obj.text();
      const { meta, body } = parseSkillMarkdown(raw);
      return {
        name,
        description: meta.description ?? "",
        version: meta.version,
        compatibility: meta.compatibility,
        body,
      };
    },
  };
}
