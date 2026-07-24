# s19d: Reuse Loop — 复用循环，不分叉

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"复用循环，不分叉"* — 向后兼容的可选参数让同一个 agent_loop 支撑第二个入口；顺手修掉 subagent 工具池不一致。
>
> **Harness 层（s19 分支）**: 扩展而非重写 — 加入口、加工具，不复制智能。

---

## 问题

s19c 把 Unity 工具装配好了。现在要加一个 Unity Agent 入口。最偷懒的做法是复制一份 `InplusCode.py` 改成 `UnityCode.py`——**这是灾难**：

- 两份几乎一样的 agent loop 会**永久分叉**：主线修了个 bug，Unity 分支不会自动同步。
- 后续 main 分支的新功能（压缩、记忆、hooks 升级）再也 merge 不进来。

这个仓库的第一原则就是"**一个 Agent Loop**"（见根 README）。加 Unity 能力，绝不能变成"再写一个 loop"。

还有个更隐蔽的老问题藏在 subagent 里：**工具池是一对，不是一个**。你 offer 给模型的工具列表（`tools`），必须等于它能执行的 handler 集合（`handlers`）。如果 offer 了一个没有 handler 的工具，模型会兴高采烈地调用它，然后撞上 "Unknown tool"。

---

## 解决方案

### 一、给 agent_loop 加向后兼容的可选参数

```python
def agent_loop(
    messages,
    *,                                  # 强制关键字，纯新增，不动位置参数
    system_prompt=SYSTEM,               # 默认 = 原来的全局
    tools=TOOLS,
    tool_handlers=TOOL_HANDLERS,
):
    ...
```

关键在**默认值**：三个新参数都默认回原来的全局。所以：

```python
agent_loop(history)                     # 老调用，行为完全不变 ✅
agent_loop(history, tools=unity_tools,  # 新入口，注入 Unity 工具池
           tool_handlers=unity_handlers,
           system_prompt=SYSTEM + appendix)
```

`UnityCode.py` 只是"薄启动器"：构建 Unity 增强工具池（在**副本**上，不动原全局），然后调用**同一个** `agent_loop`。没有第二份 loop。

### 二、工具池是一对：offer == execute

```
  offer (tools)  ───────▶  模型看到、可以挑选
                              │
                              ▼  模型挑了工具 X
  execute (handlers) ───▶  handlers[X] 存在吗？
                              ├─ 是 → 执行
                              └─ 否 → "Unknown tool: X"  ← subagent 的老 bug
```

修复：subagent 默认只用 `SUB_TOOLS` + `SUB_HANDLERS`——这一对严格匹配。Unity 工具只加进**主** agent 的池，subagent 看不到，自然也不会去调它。

---

## 工作原理

### 复用同一个 loop

demo 里 `agent_loop` 是**唯一**的循环函数，被三种场景复用：

```python
# A) 普通 agent —— 老调用不变
agent_loop(history)

# B) Unity agent —— 同一函数，注入增强池（副本）
unity_tools = list(TOOLS) + [{"name": "mcp__unity__ping"}]
unity_handlers = dict(TOOL_HANDLERS); unity_handlers["mcp__unity__ping"] = unity_ping
agent_loop(history, tools=unity_tools, tool_handlers=unity_handlers,
           system_prompt=SYSTEM + "\n# Unity mode")
```

跑起来你会看到 `base TOOLS untouched`——原全局工具池毫发无损，因为 Unity 入口在 `list(TOOLS)` / `dict(TOOL_HANDLERS)` 的**副本**上操作。

### subagent 的 bug 与修复

```python
TOOLS         = [echo, add, task]      # task 没有 handler（真实里由 loop 特判，像 compact）
SUB_HANDLERS  = {echo, add}            # subagent 能执行的

# BUGGY: offer TOOLS 但只有 SUB_HANDLERS 能执行
agent_loop(msgs, tools=TOOLS, tool_handlers=SUB_HANDLERS)
#   模型看到 task → 调用 → handlers 里没有 → "Unknown tool: task"

# FIXED: offer 与 execute 匹配的那一对
agent_loop(msgs, tools=SUB_TOOLS, tool_handlers=SUB_HANDLERS)
#   task 根本没 offer → 模型挑不到 → 落到 echo，正常执行
```

真实修复只有一行：`spawn_subagent` 里把 `tools=TOOLS` 改成 `tools=SUB_TOOLS`（见 [`scripts/utils/tools.py`](../scripts/utils/tools.py)）。改动极小，但杜绝了"模型看到自己调不动的工具"。

> **为什么 `task` 没有 handler？** 和真实的 `compact` 一样——它在 loop 里被特判处理（派生 subagent / 触发压缩），不走普通的 `handlers[name]` 路径。所以主池里 `task`/`compact` 没 handler 是**设计**，不是 bug；关键是别把它们 offer 给一个用 `SUB_HANDLERS` 执行的 subagent。

---

## 相对 s19 的变更

| 组件 | s19 之前 | s19d |
|------|---------|------|
| agent_loop 签名 | `agent_loop(messages)` | `agent_loop(messages, *, system_prompt, tools, tool_handlers)` |
| 老调用 | — | `agent_loop(history)` 完全不变（默认值兜底） |
| 新入口 | 复制整份 loop（❌） | 薄启动器复用同一 loop（✅） |
| 工具池来源 | 直接用全局 | 在副本上增强，原全局不动 |
| subagent 工具 | offer TOOLS，execute SUB_HANDLERS（不一致） | offer SUB_TOOLS，execute SUB_HANDLERS（一致） |
| 核心文件改动 | — | agent_loop 加 3 个可选参数；spawn_subagent 改 1 行 |

---

## 试一下

```sh
cd learn-claude-code
python s19d_reuse_loop/code.py
```

观察重点：

1. **[A]** `agent_loop(history)` 老调用照常工作。
2. **[B]** 同一个 `agent_loop` 注入 Unity 工具后能调 `mcp__unity__ping`，且 `base TOOLS untouched`。
3. **[C]** BUGGY 版打印 `('task', 'Unknown tool: task')`——模型被 offer 了没 handler 的工具；FIXED 版里 `task` 没被 offer，模型挑不到，直接落到 `echo`。

---

## 接下来

Unity 工具进了主池，模型能调了。但有些 Unity 操作很危险：删 GameObject、删 Asset、执行任意 C#。总不能让模型无声无息就把场景删了。

s19e External Permissions → 给外部工具分级（只读 / 变更 / 破坏 / 任意执行），用 s03/s04 的权限 + hook 体系拦截高危操作；还有一个关键坑：多动作工具的粗粒度 `destructiveHint` 不能盖过具体 `action`。

<details>
<summary>深入：这段代码在生产里长什么样</summary>

- 真实签名见 [`scripts/InplusCode.py`](../scripts/InplusCode.py) 的 `agent_loop`：`def agent_loop(messages, *, system_prompt=SYSTEM, tools=TOOLS, tool_handlers=TOOL_HANDLERS)`，函数体里 3 处引用改成参数，`agent_loop(history)` 行为零变化。
- 真实入口见 [`scripts/UnityCode.py`](../scripts/UnityCode.py)：`from InplusCode import agent_loop`（复用，绝不复制），在 `list(TOOLS)` / `dict(TOOL_HANDLERS)` 副本上装配 Unity 工具，再进同一个交互式 loop。
- subagent 修复见 [`scripts/utils/tools.py`](../scripts/utils/tools.py) 的 `spawn_subagent`：`tools=TOOLS` → `tools=SUB_TOOLS`，一行。
- 这样做的收益：main 分支后续更新（记忆、压缩、hooks）能继续 merge 进 unity 分支，因为 loop 只有一份。

</details>
