# s19c: Dynamic Discovery — real tools, assembled at runtime

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → `s19c` → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"Real tools, assembled at runtime"* — turn a server's `inputSchema` into Anthropic tools, namespaced and late-binding-safe.
>
> **Harness layer (branch off s19)**: dynamic tool discovery — the real version of s19's `assemble_tool_pool`.

---

## The problem

s19b let a sync loop drive an async server. Now `tools/list` returns **real tool definitions** — each with an `inputSchema` (JSON Schema) and `annotations` (`readOnlyHint` / `destructiveHint`). They aren't mocks you wrote; you meet them for the first time **at runtime**.

To let the model use them, you must assemble them into the harness's Anthropic tool format:

```json
{ "name": "...", "description": "...", "input_schema": {...} }
```

Assembly has four traps, each of which bites you in production:

1. **Illegal names**: a server may return `manage.scene`, `my tool`, `x/y` — dots, spaces, slashes. Using them raw breaks things.
2. **Name collisions**: two servers both expose `search`; even after normalization, `manage.scene` and `manage_scene` collapse to the same name.
3. **Late-binding bug**: building handlers with `lambda: call(base)` in a for loop makes **every** lambda point at the last value of `base`. One of Python's most classic traps.
4. **Too many tools**: a server may expose 48 tools; you may not want to give them all to the model — you need group filtering.

---

## The solution

```
  tools/list (real)                     Anthropic tool pool
  ─────────────────                   ──────────────────
  {name: "manage.scene",              normalize  → manage_scene
   inputSchema: {...},        ──────▶  namespace  → mcp__unity__manage_scene
   annotations: {...}}                 de-dup     → ...manage_scene_2 (on clash)
        │                              schema     → input_schema (add type:object)
        │                              handler    → factory binds base by value ✅
        ▼
  group_for(base) ∈ allow_groups ?  ── no → skip (e.g. execute_menu_item)
```

Four steps: **normalize → namespace → de-dup → schema-convert + factory handler**, plus a group-filter layer.

---

## How it works

### Name normalization: keep only [A-Za-z0-9_-]

```python
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

def normalize_tool_name(name):
    return _UNSAFE.sub("_", name) or "tool"     # empty -> "tool"

def namespaced_name(base, prefix):
    return f"{_UNSAFE.sub('_', prefix)}{normalize_tool_name(base)}"
```

Every illegal char becomes `_`. The `mcp__unity__` prefix is normalized too, closing off injection and collisions.

### Schema conversion: add the type

```python
def to_input_schema(mcp_tool):
    schema = mcp_tool.get("inputSchema") or {}
    if not schema:
        return {"type": "object", "properties": {}}   # Anthropic requires object
    if "type" not in schema:
        schema = {**schema, "type": "object"}          # some servers omit type
    return schema
```

An Anthropic tool's `input_schema` must be an object type. Real servers sometimes omit the top-level `type`; we add it, or the API rejects the tool.

### Collision de-dup: deterministic _2 / _3

```python
if name in taken:
    n = 2
    while f"{name}_{n}" in taken:
        n += 1
    name = f"{name}_{n}"
taken.add(name)
```

`manage.scene` and `manage_scene` both normalize to `mcp__unity__manage_scene` — the later one gets `..._2`. Deterministic and reproducible.

### Late-binding safety: a factory binds by value

```python
def make_handler(call_tool, base_name):     # base_name is a param = captured by value
    def handler(**kwargs):
        return call_tool(base_name, kwargs)
    return handler
```

Contrast the **wrong way** (Python's most classic trap):

```python
for t in mcp_tools:
    base = t["name"]
    handlers[base] = lambda **kw: call_tool(base, kw)   # ❌ closes over the loop var
# after the loop, every lambda's `base` == the LAST tool name
```

The demo makes the bug visible: calling `manage_scene` and `read_console` both end up hitting `execute_menu_item` (the last tool in the loop). The factory turns `base_name` into a function parameter, so each handler holds its own value and the bug disappears.

### Group filtering: expose only what you want

```python
def is_allowed(base, allow_groups, deny):
    if base in deny: return False
    if not allow_groups: return True
    return group_for(base) in allow_groups   # unknown tools default to "core" -> allow
```

With `allow_groups=["core","testing","materials"]`, `execute_menu_item` (group `arbitrary`) is kept out. Unknown new tools default to `core` — forward-compatible, so a server that adds new tools still works.

---

## What changed vs s19

| Component | s19 (mock) | s19c (real discovery) |
|-----------|-----------|-----------------------|
| tool source | hand-written mock defs | runtime `tools/list` discovery |
| schema | none | inputSchema → input_schema, add type |
| name normalization | normalize_mcp_name | same [A-Za-z0-9_-] |
| namespace | mcp\_\_server\_\_tool | mcp\_\_unity\_\_tool |
| collisions | unhandled | deterministic _2 / _3 de-dup |
| handler binding | `lambda *, c=.., t=..` (default-arg trick) | factory function (this chapter's focus) |
| group filtering | none | allow_groups + deny_tools |
| annotations | text label | preserved structurally for s19e permissions |

---

## Try it

```sh
cd learn-claude-code
python s19c_dynamic_discovery/code.py
```

What to watch:

1. **Group filtering**: `execute_menu_item` is absent from the result (its `arbitrary` group isn't in the allow list).
2. **Collision de-dup**: `manage.scene` became `mcp__unity__manage_scene_2`.
3. **Late-binding**: the factory handlers each record their own base; the buggy version records `execute_menu_item` for both calls — the contrast makes the factory's value obvious.

---

## Next

The tools are assembled — but who gets to use them? Do we pollute the plain coding agent by dropping them into the main loop? Does the subagent see tools it can't execute?

s19d Reuse Loop → don't copy `agent_loop`; reuse the same loop via backward-compatible optional params, add a separate Unity entry point, and fix the long-standing subagent tool-pool inconsistency along the way.

<details>
<summary>Deep dive: what this looks like in production</summary>

See [`scripts/unity_agent/tool_adapter.py`](../scripts/unity_agent/tool_adapter.py):

- `build_tools_and_handlers()` returns a `(tools, handlers, meta)` triple; `meta[namespaced] = {"base": ..., "annotations": ...}` stores the base name and annotations for s19e's permission hook.
- `make_handler()` binds `base_name` and also collapses MCP call exceptions into a stable tool_result string (with s19f's result_formatter) — never leaking a raw exception back into the loop.
- `to_input_schema()` handles real Unity's `anyOf`/`null` union types — real schemas are far more complex than the teaching mock.
- The `_TOOL_GROUPS` table puts `execute_*`/`batch_execute` in `arbitrary` (withheld by default); every other unknown tool defaults to `core`, so new server tools are usable automatically after an upgrade.

</details>
