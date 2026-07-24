# s19e: External Permissions — 外部工具分级放行

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → s19d → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"外部工具分级放行"* — 只读 / 变更 / 破坏 / 任意执行四级，用 s04 的 hook 拦高危；具体 action 盖过粗粒度注解。
>
> **Harness 层（s19 分支）**: 外部工具权限 — s03/s04 权限体系接管发现来的工具。

---

## 问题

s19d 把 Unity 工具装进了主 loop，模型能自由调用。但其中混着高危操作：

- `manage_gameobject delete` —— 删掉 GameObject
- `manage_asset delete` —— 删掉磁盘上的 Asset
- `execute_menu_item` / `execute_code` —— 执行任意菜单项 / 任意 C#

s03 给了权限门，s04 把它挪到了 `PreToolUse` hook 上。现在要把这套体系接到**外部发现**的工具上。核心是：给每个工具调用分级，按级别决定放行 / 询问 / 拒绝。

**一个真实的坑**：Unity 给多动作工具（`manage_scene`、`manage_gameobject`、`manage_material`）统一打了工具级的 `destructiveHint=True`——因为它们**某些** action 确实危险。但如果你盲信这个粗粒度注解，`get_hierarchy`（读层级）、`create`（建 Cube）、`save`（存场景）全会被误判成 DESTRUCTIVE，基本演示会被弹窗淹没。所以：**具体的 `action` 必须盖过粗粒度的工具级注解。**

---

## 解决方案

### 四级分类

| 级别 | 含义 | 示例 | 默认策略 |
|------|------|------|---------|
| READ_ONLY | 只观察 | get_hierarchy、read_console、screenshot | allow |
| MUTATING | 常规修改 | create、save、add component、set color | allow |
| DESTRUCTIVE | 可能丢数据 | delete、remove、覆盖场景 | ask |
| ARBITRARY | 执行任意代码 | execute_menu_item、execute_code、batch_execute | ask |

### 判定优先级（关键在第 4 步）

```
classify_tool(base, args, annotations)
  1) base ∈ {execute_*, batch_execute}      → ARBITRARY
  2) read_console: action=clear→MUTATING, 否则→READ_ONLY
  3) readOnlyHint=True                       → READ_ONLY
  4) 有 action 时（action 盖过粗粒度注解）：
        action 以 get/read/list/search/... 开头 → READ_ONLY
        action 含 delete/remove/destroy        → DESTRUCTIVE
        否则                                    → MUTATING
  5) 没有 action 时才回退 destructiveHint     → DESTRUCTIVE
  6) 兜底                                      → MUTATING
```

第 4 步是本章的灵魂：**只要有 `action`，就用 action 判**，不看工具级 `destructiveHint`。这样 `manage_scene get_hierarchy` = READ_ONLY，`manage_gameobject create` = MUTATING，只有 `delete` 才 DESTRUCTIVE。建 Cube 全程零弹窗。

---

## 工作原理

### classify_tool：action 优先

```python
if has_action:                                   # 有 action = 用它判，最精确
    if action.startswith(READ_ONLY_PREFIXES):
        return P.READ_ONLY                        # get_hierarchy / read / search ...
    if any(k in action for k in ("delete","remove","destroy")):
        return P.DESTRUCTIVE                       # delete / remove_component ...
    return P.MUTATING                             # create / save / add ...

if ann.get("destructiveHint") is True:            # 只有无 action 才回退注解
    return P.DESTRUCTIVE                           # 如 run_tests（无 action）
```

对照 demo 输出：`manage_scene` 明明带 `destructiveHint=True`，但 `get_hierarchy` 判成 READ_ONLY、`save` 判成 MUTATING——action 赢了。而 `run_tests` 没有 action，才回退到 `destructiveHint` → DESTRUCTIVE。

### permission_hook：复用 s04，不另起炉灶

```python
def permission_hook(block, *, prefix="mcp__unity__", meta=None, policy=None, approve=...):
    if not block.name.startswith(prefix):
        return None                     # 非 Unity 工具，直接放过（与 bash hook 组合）
    base = meta[block.name]["base"]
    cls  = classify_tool(base, block.input, meta[block.name]["annotations"])
    decision = policy[cls]
    if decision == "allow": return None
    if decision == "deny":  return f"denied by policy: {cls.value} '{base}'"
    return None if approve(base, cls) else f"denied by user: ..."   # ask
```

三个设计点：

- **前缀短路**：非 `mcp__unity__` 的工具（bash、read_file）直接返回 `None`，和现有 bash 权限 hook 无缝共存——不绕过、不替换现有体系。
- **注解优先分类**：分类先看 MCP annotations（`readOnlyHint` / `destructiveHint`），没有再按 action 规则判。
- **独立于全局 mode**：这个 hook 由 Unity runtime 单独注册。即使全局 `permission.mode = off`，Unity 的 destructive / arbitrary 仍受 `unity.permission` 配置保护。

### 配置化策略

```yaml
unity:
  permission:
    read_only: "allow"
    mutating: "allow"
    destructive: "ask"          # 全局 off 也保留保护
    arbitrary_execution: "ask"
```

默认值刻意保守但不碍事：建 Cube（create/save/add/color 全是 allow）零打断；删除、任意执行才 ask。

---

## 相对 s19 的变更

| 组件 | s19 | s19e |
|------|-----|------|
| 工具风险标注 | description 里 `(readOnly)`/`(destructive)` 文本 | 结构化 4 级 + 配置策略 |
| 分类依据 | — | annotations 优先，action 规则兜底 |
| 多动作工具 | — | **action 盖过工具级 destructiveHint**（本章关键） |
| 拦截机制 | — | 复用 s04 `PreToolUse` hook，前缀短路 |
| 与全局权限 | — | 独立 `unity.permission`，全局 off 仍保护 |

---

## 试一下

```sh
cd learn-claude-code
python s19e_external_permissions/code.py
```

观察重点：

1. **action 优先**：`manage_scene get_hierarchy` → `read_only`、`save` → `mutating`，尽管工具带 `destructiveHint=True`。
2. **危险操作**：`manage_gameobject delete` / `manage_components remove` → `destructive` → `ask`；`execute_menu_item` → `arbitrary_execution` → `ask`。
3. **hook 组合**：`create` 放行、`delete` 被 ask 拦下（demo 非交互，自动拒绝）；`bash` 非 Unity 工具直接 `passes through`。

---

## 接下来

权限管住了危险操作。但 Unity 工具的**返回**还有一堆坑：几万行的 Hierarchy、几百 KB 的截图 base64、结构化大 JSON——原样塞进上下文会瞬间爆 token。

s19f Result Control → 把 CallToolResult 收敛成紧凑字符串：截图只回路径不回 base64、超长截断、错误稳定化；再加 Observe→Act→Verify 验证辅助，最后把 config / skill / bootstrap 串成一个完整的 Unity Agent。

<details>
<summary>深入：这段代码在生产里长什么样</summary>

- 真实分类见 [`scripts/unity_agent/permissions.py`](../scripts/unity_agent/permissions.py) 的 `classify_tool`：优先级与本章一致，`READ_ONLY_ACTION_PREFIXES` 更全（含 `validate_`、`docs`、`reflect` 等）。
- 真实 hook 见 [`scripts/unity_agent/bootstrap.py`](../scripts/unity_agent/bootstrap.py) 的 `UnityRuntime.permission_hook`：用 `register_hook("PreToolUse", ...)` 注册（复用 s04），`_ask()` 在非交互（无 TTY）时安全降级为拒绝；`_record()` 把 mutating/destructive 操作记进 `session_state`，返回可追踪的 operation id。
- 真实分类是纯函数、无 IO，所以能被离线单测独立覆盖——`classify_tool` 不做任何 `input()`，交互提示留在 hook 里，与分类彻底解耦。
- 这个 destructiveHint 坑是真机发现的：连上真实 Unity MCP 后，`manage_scene`/`manage_gameobject`/`manage_material` 全带 `destructiveHint=True`，若不让 action 优先，读层级、建 Cube 都会误判成破坏性操作。

</details>
