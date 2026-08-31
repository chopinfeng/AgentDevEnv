/**
 * Agent Skills —— 按需加载的能力包。
 *
 * 遵循 Agent Skills 开放规范（https://agentskills.io/specification）。
 * 这是目前跨厂商共识度最高的一项 Agent 规范：OpenAI (ChatGPT/Codex)、
 * Google (Gemini CLI)、Microsoft (Copilot/VS Code)、Anthropic、Mistral
 * 均已采纳，所以这里的 skill 目录可以跨工具复用。
 *
 * 渐进式披露的三级预算（规范给出的量化建议）：
 *   1. metadata   ~100 tokens —— 启动时只加载所有 skill 的 name + description
 *   2. 正文       < 5000 tokens —— skill 被激活时才加载 SKILL.md 全文
 *   3. 资源文件   按需 —— scripts/ references/ assets/
 * 另：SKILL.md 建议控制在 500 行内，引用保持一层深度。
 *
 * 这一层同时是"记忆积累型进化"的落点：Agent 可以把复盘出的做法
 * 写成新 skill 存进 R2，经评估门禁后由 PR 固化到仓库。
 */

export interface SkillMeta {
  /** 1–64 字符，仅小写字母/数字/连字符，不可首尾连字符或连续连字符，须与目录名一致 */
  name: string;
  /** 1–1024 字符。同时说明「做什么」和「何时用」—— 这句话决定它会不会被想起来 */
  description: string;
  version?: string;
  /** 可选：环境要求（目标产品、系统依赖等），≤500 字符。多数 skill 不需要 */
  compatibility?: string;
}

export interface Skill extends SkillMeta {
  /** SKILL.md 正文（去掉 frontmatter） */
  body: string;
}

/** 规范对 name 的约束，写成可执行的校验 */
const NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function validateSkillName(name: string): string | null {
  if (name.length < 1 || name.length > 64) return "name 长度须在 1–64 字符";
  if (!NAME_RE.test(name)) {
    return "name 只能含小写字母、数字与单个连字符，且不可首尾为连字符";
  }
  return null;
}

export function validateSkillMeta(meta: Partial<SkillMeta>): string | null {
  if (!meta.name) return "缺少 name";
  const nameErr = validateSkillName(meta.name);
  if (nameErr) return nameErr;
  if (!meta.description) return "缺少 description";
  if (meta.description.length > 1024) return "description 超过 1024 字符";
  return null;
}

/**
 * Skill 存储。两种实现：
 *   bundled — 随代码部署，走 Git 版本管理（稳定能力）
 *   r2      — 运行时可写，进化管线产出的新 skill 先落这里（实验能力）
 */
export interface SkillStore {
  readonly kind: string;
  list(): Promise<SkillMeta[]> | SkillMeta[];
  get(name: string): Promise<Skill | undefined> | Skill | undefined;
}
