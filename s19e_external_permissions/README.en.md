# s19e: External Permissions — tiered gating for discovered tools

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → s19d → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"Tiered gating for discovered tools"* — read-only / mutating / destructive / arbitrary; gate the dangerous ones with the s04 hook; the specific action beats the coarse hint.
>
> **Harness layer (branch off s19)**: external-tool permissions — the s03/s04 system takes over discovered tools.

---

## The problem

s19d put Unity tools in the main loop and the model can call them freely. But some are dangerous:

- `manage_gameobject delete` — erase a GameObject
- `manage_asset delete` — delete an Asset on disk
- `execute_menu_item` / `execute_code` — run an arbitrary menu item / arbitrary C#

s03 gave us permission gates; s04 moved them onto a `PreToolUse` hook. Now we wire that system onto **externally discovered** tools: classify each call, then allow / ask / deny by tier.

**A real trap**: Unity marks multi-action tools (`manage_scene`, `manage_gameobject`, `manage_material`) with a tool-level `destructiveHint=True` — because **some** of their actions really are dangerous. But trust that coarse hint blindly and `get_hierarchy` (read), `create` (make a Cube), `save` all get mis-flagged as DESTRUCTIVE, drowning the basic demo in prompts. So **the specific `action` must win over the coarse tool-level hint.**

---

## The solution

### Four tiers

| Tier | Meaning | Examples | Default policy |
|------|---------|----------|----------------|
| READ_ONLY | observe only | get_hierarchy, read_console, screenshot | allow |
| MUTATING | normal edit | create, save, add component, set color | allow |
| DESTRUCTIVE | possible data loss | delete, remove, overwrite scene | ask |
| ARBITRARY | run arbitrary code | execute_menu_item, execute_code, batch_execute | ask |

### Decision precedence (the key is step 4)

```
classify_tool(base, args, annotations)
  1) base ∈ {execute_*, batch_execute}      → ARBITRARY
  2) read_console: action=clear→MUTATING, else→READ_ONLY
  3) readOnlyHint=True                       → READ_ONLY
  4) when an action exists (action beats the coarse hint):
        action starts with get/read/list/search/... → READ_ONLY
        action contains delete/remove/destroy        → DESTRUCTIVE
        otherwise                                    → MUTATING
  5) no action -> fall back to destructiveHint → DESTRUCTIVE
  6) default                                   → MUTATING
```

Step 4 is the soul of this chapter: **when an `action` exists, classify by it**, ignoring the tool-level `destructiveHint`. So `manage_scene get_hierarchy` = READ_ONLY, `manage_gameobject create` = MUTATING, only `delete` is DESTRUCTIVE. The Cube demo never prompts.

---

## How it works

### classify_tool: action first

```python
if has_action:                                   # an action = classify by it, most precise
    if action.startswith(READ_ONLY_PREFIXES):
        return P.READ_ONLY                        # get_hierarchy / read / search ...
    if any(k in action for k in ("delete","remove","destroy")):
        return P.DESTRUCTIVE                       # delete / remove_component ...
    return P.MUTATING                             # create / save / add ...

if ann.get("destructiveHint") is True:            # fall back to the hint ONLY without an action
    return P.DESTRUCTIVE                           # e.g. run_tests (no action)
```

Compare the demo output: `manage_scene` carries `destructiveHint=True`, yet `get_hierarchy` classifies as READ_ONLY and `save` as MUTATING — the action wins. Only `run_tests`, which has no action, falls back to `destructiveHint` → DESTRUCTIVE.

### permission_hook: reuse s04, don't reinvent

```python
def permission_hook(block, *, prefix="mcp__unity__", meta=None, policy=None, approve=...):
    if not block.name.startswith(prefix):
        return None                     # non-Unity tool — pass through (composes with bash hook)
    base = meta[block.name]["base"]
    cls  = classify_tool(base, block.input, meta[block.name]["annotations"])
    decision = policy[cls]
    if decision == "allow": return None
    if decision == "deny":  return f"denied by policy: {cls.value} '{base}'"
    return None if approve(base, cls) else f"denied by user: ..."   # ask
```

Three design points:

- **Prefix short-circuit**: non-`mcp__unity__` tools (bash, read_file) return `None` immediately, coexisting seamlessly with the existing bash permission hook — no bypass, no replacement.
- **Annotations first**: classification checks MCP annotations (`readOnlyHint` / `destructiveHint`) first, then falls back to action rules.
- **Independent of global mode**: this hook is registered separately by the Unity runtime. Even with global `permission.mode = off`, Unity destructive/arbitrary stays protected by `unity.permission`.

### Config-driven policy

```yaml
unity:
  permission:
    read_only: "allow"
    mutating: "allow"
    destructive: "ask"          # protected even when global mode is off
    arbitrary_execution: "ask"
```

The defaults are deliberately conservative but unobtrusive: making a Cube (create/save/add/color all allow) is uninterrupted; only delete and arbitrary execution ask.

---

## What changed vs s19

| Component | s19 | s19e |
|-----------|-----|------|
| risk labels | `(readOnly)`/`(destructive)` text in the description | structured 4 tiers + config policy |
| classification basis | — | annotations first, action rules as fallback |
| multi-action tools | — | **action beats tool-level destructiveHint** (this chapter's key) |
| gating | — | reuse the s04 `PreToolUse` hook, prefix short-circuit |
| vs global perms | — | separate `unity.permission`, protected even when global is off |

---

## Try it

```sh
cd learn-claude-code
python s19e_external_permissions/code.py
```

What to watch:

1. **Action first**: `manage_scene get_hierarchy` → `read_only`, `save` → `mutating`, even though the tool carries `destructiveHint=True`.
2. **Dangerous ops**: `manage_gameobject delete` / `manage_components remove` → `destructive` → `ask`; `execute_menu_item` → `arbitrary_execution` → `ask`.
3. **Hook composition**: `create` is allowed, `delete` is gated by ask (auto-denied in this non-interactive run); `bash`, a non-Unity tool, `passes through`.

---

## Next

Permissions tame the dangerous ops. But Unity tool **results** have their own traps: tens of thousands of hierarchy lines, hundreds of KB of screenshot base64, big structured JSON — dumping them raw into context blows the token budget instantly.

s19f Result Control → collapse a CallToolResult into a compact string: screenshots return a path not base64, over-long output is truncated, errors are stabilized; plus Observe→Act→Verify helpers, and finally tie config / skill / bootstrap into one complete Unity Agent.

<details>
<summary>Deep dive: what this looks like in production</summary>

- The real classifier is [`scripts/unity_agent/permissions.py`](../scripts/unity_agent/permissions.py)'s `classify_tool`: same precedence as this chapter, with a fuller `READ_ONLY_ACTION_PREFIXES` (incl. `validate_`, `docs`, `reflect`).
- The real hook is [`scripts/unity_agent/bootstrap.py`](../scripts/unity_agent/bootstrap.py)'s `UnityRuntime.permission_hook`: registered via `register_hook("PreToolUse", ...)` (reusing s04); `_ask()` degrades safely to deny when non-interactive (no TTY); `_record()` logs mutating/destructive ops into `session_state`, returning a traceable operation id.
- The real classifier is a pure, IO-free function, so it can be covered by offline unit tests in isolation — `classify_tool` never calls `input()`; the interactive prompt lives in the hook, fully decoupled from classification.
- This destructiveHint trap was found on real hardware: connected to the real Unity MCP, `manage_scene`/`manage_gameobject`/`manage_material` all carry `destructiveHint=True`; without action-first, reading a hierarchy or making a Cube gets mis-flagged as destructive.

</details>
