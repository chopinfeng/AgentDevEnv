# Agent Skills

遵循 [Agent Skills 开放规范](https://agentskills.io/specification)。这是目前跨厂商共识度最高的 Agent 规范——OpenAI、Google、Microsoft、Anthropic、Mistral 均已采纳，所以 skill 目录可跨工具复用。

## 格式约束

照着写，否则校验不过：

| 字段 | 必需 | 约束 |
|---|---|---|
| `name` | 是 | 1–64 字符，仅小写字母/数字/连字符，不可首尾连字符或连续连字符，**须与目录名一致** |
| `description` | 是 | 1–1024 字符。同时说明「做什么」和「何时用」 |
| `license` / `compatibility` / `metadata` / `allowed-tools` | 否 | `compatibility` ≤500 字符，多数 skill 不需要 |

目录结构：

```
skill-name/
├── SKILL.md          # 必需
├── scripts/          # 可执行代码
├── references/       # 按需加载的文档
└── assets/           # 模板、资源
```

## 渐进式披露

三级预算（规范给出的量化建议）：

1. **metadata**（约 100 tokens）—— 启动时只加载所有 skill 的 name + description
2. **正文**（建议 <5000 tokens）—— skill 被激活时才加载 SKILL.md 全文
3. **资源文件** —— `scripts/` `references/` `assets/` 按需

另：SKILL.md 建议控制在 500 行内，引用保持一层深度。

## 在 Agent 里实现

只暴露一个 `load_skill` 工具，正文不进系统提示；清单（名字 + 描述）渲进提示。这样挂 50 个 skill 也只占几百 token，而不是把全部正文塞进每一轮。

```
系统提示里只有这个：
<skills>
- device-troubleshoot：当用户报告设备没反应、离线或行为异常时，用这套流程排查。
- refund-policy：处理退款请求时，按这套规则判断是否符合条件。
</skills>
```

`description` 决定这个 skill 会不会被想起来——写「何时用」比写「做什么」重要。

## 两层存储

- **随代码部署**：稳定能力，走 Git 版本管理与 PR 评审
- **对象存储**：进化管线产出的候选先落这里，验证后由 PR 固化

第二层是「记忆积累型进化」的落点——Agent 可以把复盘出的做法写成新 skill。配套要求见 `evaluation-and-evolution.md`：产物必须过评估门禁 + 人工审批才能固化。

## 解析 frontmatter

从对象存储读 SKILL.md 时要自己解析。两个实践要点：

- **以目录名为准**，不要信 frontmatter 里的 `name`——写错了会导致取不到
- 不合规的 skill 直接跳过，别让它污染清单
