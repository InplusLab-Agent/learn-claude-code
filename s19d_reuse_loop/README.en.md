# s19d: Reuse Loop — extend without forking

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"Extend without forking"* — backward-compatible optional params let one agent_loop back a second entry point; and fix the subagent tool-pool inconsistency along the way.
>
> **Harness layer (branch off s19)**: extend, don't rewrite — add an entry, add tools, don't copy the intelligence.

---

## The problem

s19c assembled the Unity tools. Now we want a Unity Agent entry point. The lazy move is to copy `InplusCode.py` into `UnityCode.py` — **a disaster**:

- Two nearly-identical agent loops **fork forever**: a bug fixed on main won't sync to the Unity branch.
- Future main-branch features (compaction, memory, hook upgrades) can never merge back.

This repo's first principle is "**one agent loop**" (see the root README). Adding Unity must not become "write a second loop."

There's also a subtler long-standing bug hiding in the subagent: **a tool pool is a pair, not a single thing**. What you OFFER the model (`tools`) must equal what it can EXECUTE (`handlers`). Offer a tool with no handler and the model will happily call it — then hit "Unknown tool."

---

## The solution

### 1. Give agent_loop backward-compatible optional params

```python
def agent_loop(
    messages,
    *,                                  # keyword-only, pure addition, positional args untouched
    system_prompt=SYSTEM,               # default = the original global
    tools=TOOLS,
    tool_handlers=TOOL_HANDLERS,
):
    ...
```

The **defaults** are the trick: all three new params fall back to the originals. So:

```python
agent_loop(history)                     # old call, behavior unchanged ✅
agent_loop(history, tools=unity_tools,  # new entry, inject the Unity pool
           tool_handlers=unity_handlers,
           system_prompt=SYSTEM + appendix)
```

`UnityCode.py` is just a "thin launcher": it builds the augmented Unity pool (on **copies**, not the globals) and calls the **same** `agent_loop`. No second loop.

### 2. A tool pool is a pair: offer == execute

```
  offer (tools)  ───────▶  model sees them, can pick
                              │
                              ▼  model picked tool X
  execute (handlers) ───▶  does handlers[X] exist?
                              ├─ yes → run it
                              └─ no  → "Unknown tool: X"  ← the subagent bug
```

The fix: the subagent uses only `SUB_TOOLS` + `SUB_HANDLERS` — a strictly matching pair. Unity tools are added only to the **main** agent's pool; the subagent never sees them, so it can't call them.

---

## How it works

### Reuse the one loop

In the demo, `agent_loop` is the **only** loop function, reused in three scenarios:

```python
# A) plain agent — old call unchanged
agent_loop(history)

# B) Unity agent — same function, inject augmented pool (copies)
unity_tools = list(TOOLS) + [{"name": "mcp__unity__ping"}]
unity_handlers = dict(TOOL_HANDLERS); unity_handlers["mcp__unity__ping"] = unity_ping
agent_loop(history, tools=unity_tools, tool_handlers=unity_handlers,
           system_prompt=SYSTEM + "\n# Unity mode")
```

You'll see `base TOOLS untouched` — the original global pool is intact because the Unity entry works on the `list(TOOLS)` / `dict(TOOL_HANDLERS)` **copies**.

### The subagent bug and fix

```python
TOOLS         = [echo, add, task]      # task has NO handler (special-cased in the loop, like compact)
SUB_HANDLERS  = {echo, add}            # what the subagent can execute

# BUGGY: offer TOOLS but only SUB_HANDLERS can execute
agent_loop(msgs, tools=TOOLS, tool_handlers=SUB_HANDLERS)
#   model sees task → calls it → not in handlers → "Unknown tool: task"

# FIXED: offer the pair that matches execute
agent_loop(msgs, tools=SUB_TOOLS, tool_handlers=SUB_HANDLERS)
#   task was never offered → model can't pick it → falls through to echo
```

The real fix is one line: in `spawn_subagent`, change `tools=TOOLS` to `tools=SUB_TOOLS` (see [`scripts/utils/tools.py`](../scripts/utils/tools.py)). Tiny change, but it eliminates "the model sees a tool it can't run."

> **Why does `task` have no handler?** Same as the real `compact` — it's special-cased in the loop (spawn a subagent / trigger compaction) instead of going through the normal `handlers[name]` path. So `task`/`compact` having no handler in the main pool is **by design**, not a bug; the key is not to offer them to a subagent that executes via `SUB_HANDLERS`.

---

## What changed vs s19

| Component | before s19 | s19d |
|-----------|-----------|------|
| agent_loop signature | `agent_loop(messages)` | `agent_loop(messages, *, system_prompt, tools, tool_handlers)` |
| old call | — | `agent_loop(history)` unchanged (defaults cover it) |
| new entry | copy the whole loop (❌) | thin launcher reuses the same loop (✅) |
| tool pool source | use globals directly | augment on copies, globals untouched |
| subagent tools | offer TOOLS, execute SUB_HANDLERS (inconsistent) | offer SUB_TOOLS, execute SUB_HANDLERS (consistent) |
| core-file change | — | agent_loop +3 optional params; spawn_subagent +1 line |

---

## Try it

```sh
cd learn-claude-code
python s19d_reuse_loop/code.py
```

What to watch:

1. **[A]** the old `agent_loop(history)` call still works.
2. **[B]** the same `agent_loop`, given Unity tools, can call `mcp__unity__ping`, and `base TOOLS untouched`.
3. **[C]** the BUGGY run prints `('task', 'Unknown tool: task')` — the model was offered a handler-less tool; in the FIXED run `task` isn't offered, so the model can't pick it and falls through to `echo`.

---

## Next

Unity tools are in the main pool and the model can call them. But some Unity ops are dangerous: delete a GameObject, delete an Asset, execute arbitrary C#. You can't let the model silently delete the scene.

s19e External Permissions → classify external tools (read-only / mutating / destructive / arbitrary), gate the dangerous ones with the s03/s04 permission + hook system, and handle one key trap: a multi-action tool's coarse `destructiveHint` must not override its specific `action`.

<details>
<summary>Deep dive: what this looks like in production</summary>

- The real signature is in [`scripts/InplusCode.py`](../scripts/InplusCode.py): `def agent_loop(messages, *, system_prompt=SYSTEM, tools=TOOLS, tool_handlers=TOOL_HANDLERS)`, with 3 body references swapped to params; `agent_loop(history)` behaves identically.
- The real entry is [`scripts/UnityCode.py`](../scripts/UnityCode.py): `from InplusCode import agent_loop` (reuse, never copy), assemble Unity tools on `list(TOOLS)` / `dict(TOOL_HANDLERS)` copies, then enter the same interactive loop.
- The subagent fix is in [`scripts/utils/tools.py`](../scripts/utils/tools.py)'s `spawn_subagent`: `tools=TOOLS` → `tools=SUB_TOOLS`, one line.
- The payoff: future main-branch updates (memory, compaction, hooks) can keep merging into the unity branch, because there is only one loop.

</details>
