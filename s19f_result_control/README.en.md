# s19f: Result Control — collapse results, verify, wrap up

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → s19d → s19e → `s19f` → [s20](../s20_comprehensive/)

> *"Collapse results, verify"* — squeeze big results into one string, screenshots return a path, errors stabilize; then tie the whole Unity Agent together with Observe→Act→Verify.
>
> **Harness layer (branch off s19)**: result & context control — the branch's closing chapter.

---

## The problem

s19e tamed the dangerous ops. The last hurdle is the **return value**. A Unity tool's `CallToolResult` can carry:

- tens of thousands of hierarchy JSON lines;
- hundreds of KB of screenshot base64;
- a big structured `structuredContent` blob.

Forward that raw into the LLM context and one call burns the token budget. This extends s08's context management: **external results must be collapsed before they enter context.**

And this is the **closing chapter** — the parts from the previous five chapters (real async client, dynamic discovery, loop reuse, external permissions) come together here into a complete "config-driven, skill-guided, Observe→Act→Verify" Unity Agent.

---

## The solution

### Four things the formatter does

```
CallToolResult
  ├─ text block        → take the text as-is
  ├─ image block       → [image omitted: png, ~200000 chars]  ← never the base64
  ├─ structuredContent → compact JSON (fallback when no text)
  └─ whole thing       → truncate to MAX_RESULT_CHARS with a clear marker
  isError=True         → [unity-tool-error] tool=... : ... stable string
```

In one line: `CallToolResult` → **one compact string**, images become metadata, over-long output is truncated, errors are predictable.

### Observe → Act → Verify

```
  Observe            Act               Verify
  ────────           ────              ──────────────────
  read editor state  create Cube       wait for compile (is_compiling=false)
  read active scene  set position      read Console error count
  read hierarchy     add Rigidbody     re-read the changed object
  read Console(base) assign red mat    screenshot / save when it checks out
```

This is the **prompt-level default rhythm** (written into the skill), not a hard-coded state machine — the model decides when to observe and when to verify. This chapter provides two small helpers so the common checks are one call away.

---

## How it works

### Screenshots return a path; base64 never enters context

```python
def _stringify_block(block):
    if hasattr(block, "text"):
        return str(block.text)
    if hasattr(block, "data"):                       # image / audio
        size = len(block.data or "")
        return f"[image omitted: {block.mimeType}, ~{size} base64 chars — not sent]"
    return str(block)
```

In the demo a ~200 KB fake screenshot collapses to one metadata line, `base64 present? False`. Real screenshots go through `manage_camera`, which returns a **file path** (`Assets/Screenshots/...png`) — the model reasons about the path and views the image with a dedicated tool only if needed, never dumping base64 into context.

### Truncation + stable errors

```python
def _truncate(text, limit=MAX_RESULT_CHARS):
    if len(text) <= limit: return text
    return text[:limit] + f"\n...[truncated {len(text)-limit} chars — narrow the query or page]"

def format_error(tool_name, exc, hint=""):
    return f"[unity-tool-error] tool={tool_name} type={type(exc).__name__}: {exc}. {hint}"
```

Errors always carry **tool name + error type + an actionable hint**, not a bare "Error". The model can self-repair ("target not found → retry with a different search_method").

### wait_for_compile: wait, don't guess

```python
def wait_for_compile(state_reader, *, timeout=2.0, poll=0.05):
    while ...:
        text = state_reader()
        if '"is_compiling":false' in text and '"ready_for_tools":true' in text:
            return {"ready": True, ...}
        time.sleep(poll)
```

Real Unity's compile state lives in the **resource** `mcpforunity://editor/state` (fields `data.compilation.is_compiling`, `data.advice.ready_for_tools`), not in some tool's action. So `wait_for_compile` takes a `state_reader` callback and polls until "done compiling and ready." After editing scripts or adding components, you must wait for it before using new types.

### Wrap-up: config + skill + structured acceptance

Three threads assemble the parts into an agent:

- **Config-driven**: the `unity:` block controls connection, tool groups, permissions, and verification toggles (see [s19e](../s19e_external_permissions/)'s policy and [s19b](../s19b_real_mcp_client/)'s URL override).
- **Skill-guided**: Observe→Act→Verify, the scene-op scope, API truthfulness, and safety rules go into `skills/unity-agent/SKILL.md`; the Unity entry injects just one line — "for Unity tasks, load_skill first."
- **Structured acceptance**: an end-to-end run prints a checkable summary — name, instance id, scene, transform, component list, material, Console error count, screenshot path, whether saved, and per-step success/failure.

---

## What changed vs s19

| Component | s19 | s19f |
|-----------|-----|------|
| result handling | return a raw string | CallToolResult → compact string, images stripped, truncated |
| screenshots | — | path + metadata only, base64 never enters context |
| errors | bare string | stable format: tool name + type + diagnostic hint |
| verification | — | Observe→Act→Verify helpers (wait for compile / read Console) |
| domain behavior | none | skill injects domain rules, config-driven |
| wrap-up | — | structured E2E summary (each step checkable) |

---

## Try it

```sh
cd learn-claude-code
python s19f_result_control/code.py
```

What to watch:

1. **base64 stripping**: a ~200 KB fake screenshot collapses to `[image omitted ...]`, `base64 present? False`.
2. **truncation**: over-long text is cut to `MAX_RESULT_CHARS` with a `...[truncated N chars]` marker.
3. **stable errors**: both an `isError` result and an exception become one `[unity-tool-error] tool=... type=...` line.
4. **verify rhythm**: the fake compiler reports `ready=True` after 3 polls; Console error count = 0.
5. **wrap-up**: the end-to-end summary shape is printed.

---

## Next

This s19 branch closes here: **s19b real async client → s19c dynamic discovery → s19d reuse loop → s19e external permissions → s19f result control** — five chapters that turned s19's mock MCP into a production-grade agent driving real Unity.

Return to the main line, [s20 Comprehensive](../s20_comprehensive/) — all mechanisms around one loop. The sync-over-async bridge, dynamic discovery, loop reuse, external permissions, and result collapsing you learned on this branch apply to any real MCP server (Jira, Figma, a database…), not just Unity.

<details>
<summary>Deep dive: what this looks like in production</summary>

- The real formatter is [`scripts/unity_agent/result_formatter.py`](../scripts/unity_agent/result_formatter.py): `format_result` handles text / image / embedded resource / structuredContent, `MAX_RESULT_CHARS=20000`, images use `_IMAGE_PLACEHOLDER`; compatible with s08's large-output hook and context compaction.
- The real verification is [`scripts/unity_agent/verification.py`](../scripts/unity_agent/verification.py): `wait_for_compile(state_reader)` reads `mcpforunity://editor/state`, `read_console_errors(caller)` counts errors by the `data` list length.
- The real wrap-up is [`scripts/unity_agent/bootstrap.py`](../scripts/unity_agent/bootstrap.py) (runtime + static diagnostic tools + system appendix) and [`scripts/skills/unity-agent/`](../scripts/skills/unity-agent/) (domain rules); the real vertical acceptance run (the full Observe→Act→Verify flow) is driven by this runtime against a live Unity MCP.
- Real acceptance result: a red AgentCube@[0,1,0] + Rigidbody in real Unity, 0 Console errors, scene saved, screenshot taken — all 17 steps passed. Screenshots are gitignored by default; session_state records an operation id per step.

</details>
