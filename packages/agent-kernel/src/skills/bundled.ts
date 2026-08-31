import type { Skill, SkillMeta, SkillStore } from "./types";

/**
 * 随代码部署的 skill —— 走 Git 版本管理与 PR 评审。
 * 新增 skill 就在这里加一条；进化管线产出的候选先进 R2，
 * 验证通过后再由 PR 固化到这里。
 */
const SKILLS: Skill[] = [
  {
    name: "device-troubleshoot",
    description: "当用户报告某台设备没反应、离线或行为异常时，用这套流程排查。",
    version: "v0.1.0",
    body: `# 设备排查流程

1. 先用 list_devices 确认设备是否在线。不在线就直接告诉用户设备未连接，不要猜测原因。
2. 在线但调用超时，通常是固件卡在阻塞操作里 —— 建议用户断电重启，而不是反复重试。
3. 调用返回错误，把设备原样返回的错误信息转述给用户，不要改写成自己的猜测。
4. 涉及执行器（继电器、电机）的操作失败时，明确提示用户去现场确认物理状态，
   不要假定"没生效"就等于"没动作"。`,
  },
  {
    name: "skill-authoring",
    description: "当需要把一次成功的处理经验沉淀成新的 skill 时，按这个格式写。",
    version: "v0.1.0",
    body: `# 编写新 skill

格式要求：
- name：kebab-case，动词或场景名，不要用编号
- description：一句话说明**何时**用它，不是它做什么。这句话决定它会不会被想起来。
- 正文：可直接执行的步骤，不写背景介绍

写完存入 R2 待评估。不要直接改 bundled skill —— 那需要走 PR。`,
  },
];

export const bundledSkills: SkillStore = {
  kind: "bundled",
  list(): SkillMeta[] {
    return SKILLS.map(({ name, description, version }) => ({ name, description, version }));
  },
  get(name: string): Skill | undefined {
    return SKILLS.find((s) => s.name === name);
  },
};
