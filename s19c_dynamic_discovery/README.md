# s19c: Dynamic Discovery — 真实工具，动态装配

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → `s19c` → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"真实工具，动态装配"* — 把 server 发现的 `inputSchema` 转成 Anthropic 工具，命名空间 + 防晚绑定。
>
> **Harness 层（s19 分支）**: 动态工具发现 — s19 `assemble_tool_pool` 的真实版。

---

## 问题

s19b 打通了同步 loop 调用异步 server。现在 `tools/list` 返回的是**真实工具定义**——每个都带 `inputSchema`（JSON Schema）和 `annotations`（`readOnlyHint` / `destructiveHint`）。它们不是你手写的 mock，你在**运行时**才第一次见到它们。

要让模型能用这些工具，得把它们装配进当前 harness 的 Anthropic 工具格式：

```json
{ "name": "...", "description": "...", "input_schema": {...} }
```

装配过程有四个坑，每一个都会在生产环境咬你：

1. **工具名不合法**：server 可能返回 `manage.scene`、`my tool`、`x/y`，含点、空格、斜杠——直接当工具名会出问题。
2. **名字撞车**：两个 server 都有 `search`；甚至规范化后 `manage.scene` 和 `manage_scene` 会撞成同一个名字。
3. **晚绑定 bug**：在 for 循环里用 `lambda: call(base)` 建 handler，循环结束后**所有** lambda 都指向 `base` 的最后一个值。这是 Python 最经典的坑之一。
4. **工具太多**：一个 server 可能暴露 48 个工具，你未必都想给模型——需要按分组过滤。

---

## 解决方案

```
  tools/list (真实)                     Anthropic 工具池
  ─────────────────                   ──────────────────
  {name: "manage.scene",              normalize  → manage_scene
   inputSchema: {...},        ──────▶  namespace  → mcp__unity__manage_scene
   annotations: {...}}                 de-dup     → ...manage_scene_2 (撞车时)
        │                              schema     → input_schema (补 type:object)
        │                              handler    → 工厂函数按值绑定 base ✅
        ▼
  group_for(base) ∈ allow_groups ?  ── 否 → 跳过（如 execute_menu_item）
```

四步装配：**规范化 → 命名空间 → 去重 → schema 转换 + 工厂 handler**，再叠一层分组过滤。

---

## 工作原理

### 名称规范化：只留 [A-Za-z0-9_-]

```python
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

def normalize_tool_name(name):
    return _UNSAFE.sub("_", name) or "tool"     # 空串兜底成 "tool"

def namespaced_name(base, prefix):
    return f"{_UNSAFE.sub('_', prefix)}{normalize_tool_name(base)}"
```

所有非法字符替换成 `_`。前缀 `mcp__unity__` 也一起规范化，杜绝注入和冲突。

### schema 转换：补上 type

```python
def to_input_schema(mcp_tool):
    schema = mcp_tool.get("inputSchema") or {}
    if not schema:
        return {"type": "object", "properties": {}}   # Anthropic 要求 object
    if "type" not in schema:
        schema = {**schema, "type": "object"}          # 有些 server 省了 type
    return schema
```

Anthropic 工具的 `input_schema` 必须是 object 类型。真实 server 有时省略顶层 `type`，这里补上，否则 API 会拒绝。

### 撞车去重：确定性的 _2 / _3

```python
if name in taken:
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    name = f"{name}_{n}"
taken.add(name)
```

`manage.scene` 和 `manage_scene` 都规范化成 `mcp__unity__manage_scene`——后来者拿到 `..._2`。确定性、可复现。

### 防晚绑定：工厂函数按值绑定

```python
def make_handler(call_tool, base_name):     # base_name 是函数参数 = 按值捕获
    def handler(**kwargs):
        return call_tool(base_name, kwargs)
    return handler
```

对比**错误写法**（Python 最经典的坑）：

```python
for t in mcp_tools:
    base = t["name"]
    handlers[base] = lambda **kw: call_tool(base, kw)   # ❌ 闭包捕获循环变量
# 循环结束后，所有 lambda 里的 base 都 == 最后一个工具名
```

demo 里这个 bug 一眼可见：调 `manage_scene` 和 `read_console`，结果两次都打到了 `execute_menu_item`（循环最后一个）。工厂函数把 `base_name` 变成函数参数，每个 handler 各自持有自己的值，bug 消失。

### 分组过滤：只暴露你要的

```python
def is_allowed(base, allow_groups, deny):
    if base in deny: return False
    if not allow_groups: return True
    return group_for(base) in allow_groups   # 未知工具默认 "core" → 放行
```

`allow_groups=["core","testing","materials"]` 时，`execute_menu_item`（`arbitrary` 组）被挡在外面。未知的新工具默认归 `core`，向前兼容——server 加了新工具也能自动用上。

---

## 相对 s19 的变更

| 组件 | s19（mock） | s19c（真实发现） |
|------|------------|----------------|
| 工具来源 | 手写 mock 定义 | 运行时 `tools/list` 发现 |
| schema | 无 | inputSchema → input_schema，补 type |
| 命名规范化 | normalize_mcp_name（已有） | 同款 [A-Za-z0-9_-] |
| 命名空间 | mcp\_\_server\_\_tool | mcp\_\_unity\_\_tool |
| 撞车 | 未处理 | 确定性 _2 / _3 去重 |
| handler 绑定 | `lambda *, c=.., t=..`（默认参数法） | 工厂函数法（本章重点对比） |
| 分组过滤 | 无 | allow_groups + deny_tools |
| annotations | 文本标注 | 结构化保留，供 s19e 权限判定 |

---

## 试一下

```sh
cd learn-claude-code
python s19c_dynamic_discovery/code.py
```

观察重点：

1. **分组过滤**：`execute_menu_item` 没出现在结果里（`arbitrary` 组未在 allow 列表）。
2. **撞车去重**：`manage.scene` 变成了 `mcp__unity__manage_scene_2`。
3. **防晚绑定**：工厂 handler 逐个调用，`recorded bases` 一一对应；而 buggy 版两次调用都打到 `execute_menu_item`——对比之下，工厂法的价值一目了然。

---

## 接下来

工具装配好了，但装配好的工具要交给谁用？直接塞进主 loop 会不会污染原来的通用 agent？subagent 会不会看到它调不动的工具？

s19d Reuse Loop → 不复制 agent_loop，用向后兼容的可选参数复用同一个循环，新开一个 Unity 入口，并顺手修掉 subagent 工具池不一致的老问题。

<details>
<summary>深入：这段代码在生产里长什么样</summary>

真实实现见 [`scripts/unity_agent/tool_adapter.py`](../scripts/unity_agent/tool_adapter.py)：

- `build_tools_and_handlers()` 返回 `(tools, handlers, meta)` 三元组；`meta[namespaced] = {"base": ..., "annotations": ...}` 把 base 名和注解存下来，供 s19e 的权限 hook 用。
- `make_handler()` 里除了绑定 base_name，还把 MCP 调用异常收敛成稳定的 tool_result 字符串（配合 s19f 的 result_formatter），绝不把裸异常抛回 loop。
- `to_input_schema()` 对真实 Unity 的 `anyOf`/`null` 联合类型做了兼容——真实 schema 比教学 mock 复杂得多。
- 分组表 `_TOOL_GROUPS` 把 `execute_*`/`batch_execute` 归入 `arbitrary`，默认不暴露；其余未知工具归 `core`，保证 server 升级后新工具自动可用。

</details>
