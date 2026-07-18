---
name: create-skill
description: 帮助用户创建新的 Claude Code skill。收集 skill 的名称、用途和行为描述，生成标准的 SKILL.md 文件。
allowed-tools: Read, Write, Bash, Glob
---

# Create Skill

帮助用户创建一个新的 Claude Code skill。

## 流程

### 第一步：收集信息

如果用户没有提供足够信息，询问以下内容：

1. **skill 名称**（用于 `/skill-name` 调用，小写加连字符，如 `code-review`）
2. **一句话描述**（用于 Claude 判断何时自动触发）
3. **skill 的具体行为**：它应该做什么？输出什么格式？遵循什么规范？

### 第二步：确定存放位置

- **用户级**（所有项目可用）：`~/.claude/skills/<name>/SKILL.md`
- **项目级**（仅当前项目）：`.claude/skills/<name>/SKILL.md`

默认使用用户级，除非用户明确说只用于当前项目。

### 第三步：生成 SKILL.md

按以下模板生成内容：

```markdown
---
name: <skill-name>
description: <一句话描述，说明 skill 的用途和触发时机>
allowed-tools: <需要的工具列表，逗号分隔>
---

# <Skill 标题>

<简短说明这个 skill 的目标>

## 行为规范

<具体的指令、步骤、格式要求等>

## 输出格式

<如果有特定输出格式，在这里描述>
```

### 第四步：写入文件

1. 创建目录：`mkdir -p <skill-dir>`
2. 写入 `SKILL.md` 文件
3. 告知用户如何调用：`/<skill-name>`

## 注意事项

- `description` 字段直接影响 Claude 是否自动触发该 skill，要写得准确
- `allowed-tools` 只列出 skill 真正需要的工具
- SKILL.md 的正文是给 Claude 看的指令，要清晰、具体、可执行
- skill 名称即调用命令，保持简短易记
