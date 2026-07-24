#!/usr/bin/env python3
"""
s19c_dynamic_discovery/code.py — Dynamic Tool Discovery + Schema Adapter

s19's mock handed us tool definitions we wrote ourselves. A real MCP server
(s19b) advertises tools via `tools/list`, each carrying an `inputSchema` and
`annotations`. Before the model can use them, we must adapt them into the
harness's Anthropic tool format — and do it safely.

This chapter builds the adapter that turns discovered MCP tools into
`{name, description, input_schema}` + one handler each. It covers the four
things that bite you in production:

  1. Name normalization  — only [A-Za-z0-9_-] survive.
  2. Namespacing         — mcp__unity__<tool> avoids collisions with builtins.
  3. Collision de-dup     — two tools normalizing to the same name get _2, _3...
  4. Late-binding safety  — each handler is bound to ITS OWN base name via a
                            factory, not a lambda that closes over a loop var.
  Plus: group allow-listing so you expose only the tool groups you want.

Run:
    python s19c_dynamic_discovery/code.py
"""

from __future__ import annotations

import re
from typing import Any, Callable

# ═══════════════════════════════════════════════════════════
#  1) Name normalization + namespacing
# ═══════════════════════════════════════════════════════════
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def normalize_tool_name(name: str) -> str:
    """Reduce a raw name to the safe charset [A-Za-z0-9_-]; never empty."""
    if not name:
        return "tool"
    return _UNSAFE.sub("_", name) or "tool"


def namespaced_name(base: str, prefix: str) -> str:
    return f"{_UNSAFE.sub('_', prefix)}{normalize_tool_name(base)}"


# ═══════════════════════════════════════════════════════════
#  2) inputSchema (MCP) -> input_schema (Anthropic)
# ═══════════════════════════════════════════════════════════
def to_input_schema(mcp_tool: dict) -> dict:
    schema = mcp_tool.get("inputSchema") or {}
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}   # Anthropic requires object
    if "type" not in schema:
        schema = {**schema, "type": "object"}
    return schema


def to_anthropic_tool(mcp_tool: dict, prefix: str, taken: set[str]) -> dict:
    base = mcp_tool.get("name", "tool")
    name = namespaced_name(base, prefix)
    # 3) collision de-dup: deterministic _2, _3, ...
    if name in taken:
        n = 2
        while f"{name}_{n}" in taken:
            n += 1
        name = f"{name}_{n}"
    taken.add(name)
    return {
        "name": name,
        "description": mcp_tool.get("description", f"MCP tool '{base}'."),
        "input_schema": to_input_schema(mcp_tool),
    }


# ═══════════════════════════════════════════════════════════
#  4) Late-binding-safe handler factory
# ═══════════════════════════════════════════════════════════
def make_handler(call_tool: Callable[[str, dict], str], base_name: str) -> Callable[..., str]:
    """Bind base_name by VALUE (function arg), not by closing over a loop var."""

    def handler(**kwargs: Any) -> str:
        return call_tool(base_name, kwargs)

    handler.__name__ = f"unity_{normalize_tool_name(base_name)}"
    return handler


# ═══════════════════════════════════════════════════════════
#  Group allow-listing (unknown tools default to "core" -> included)
# ═══════════════════════════════════════════════════════════
_GROUPS = {"run_tests": "testing", "manage_material": "materials", "execute_menu_item": "arbitrary"}


def group_for(base: str) -> str:
    return _GROUPS.get(base, "core")


def is_allowed(base: str, allow_groups: list[str] | None, deny: list[str]) -> bool:
    if base in deny:
        return False
    if not allow_groups:
        return True
    return group_for(base) in allow_groups


def build_tools_and_handlers(mcp_tools, *, prefix, call_tool, allow_groups=None, deny=()):
    tools, handlers, meta = [], {}, {}
    taken: set[str] = set()
    for t in mcp_tools:
        base = t.get("name", "tool")
        if not is_allowed(base, allow_groups, list(deny)):
            continue
        atool = to_anthropic_tool(t, prefix, taken)
        tools.append(atool)
        handlers[atool["name"]] = make_handler(call_tool, base)     # factory = safe
        meta[atool["name"]] = {"base": base, "annotations": t.get("annotations", {})}
    return tools, handlers, meta


# ═══════════════════════════════════════════════════════════
#  The WRONG way (shown for contrast) — late binding bug
# ═══════════════════════════════════════════════════════════
def build_handlers_buggy(mcp_tools, call_tool):
    handlers = {}
    for t in mcp_tools:
        base = t["name"]
        # BUG: the lambda closes over `base`; after the loop, every lambda
        # sees the LAST value of `base`.
        handlers[base] = lambda **kw: call_tool(base, kw)
    return handlers


# ═══════════════════════════════════════════════════════════
#  Demo
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print("s19c — Dynamic Discovery + Schema Adapter\n" + "=" * 48)

    # Simulated tools/list from a real server. Note the collision:
    # "manage.scene" and "manage_scene" both normalize to manage_scene.
    discovered = [
        {"name": "manage_scene", "description": "Scene CRUD.",
         "inputSchema": {"properties": {"action": {"type": "string"}}, "required": ["action"]},
         "annotations": {"destructiveHint": True}},
        {"name": "manage.scene", "description": "A different server's scene tool.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "read_console", "description": "Read the console.", "inputSchema": {}},
        {"name": "run_tests", "description": "Run tests.", "inputSchema": {}},
        {"name": "execute_menu_item", "description": "Run any menu item.", "inputSchema": {}},
    ]

    # A fake caller records which base name it was invoked with.
    calls: list[str] = []

    def fake_call(base: str, args: dict) -> str:
        calls.append(base)
        return f"{base}{args} -> ok"

    tools, handlers, meta = build_tools_and_handlers(
        discovered, prefix="mcp__unity__", call_tool=fake_call,
        allow_groups=["core", "testing", "materials"],   # 'arbitrary' excluded
    )

    print("Adapted tools (execute_menu_item filtered out by group):")
    for t in tools:
        print(f"  {t['name']:<28} schema.type={t['input_schema']['type']}")

    print("\nCollision handling: manage.scene -> ", end="")
    print([t["name"] for t in tools if t["name"].startswith("mcp__unity__manage_scene")])

    print("\nLate-binding proof — call each handler, it must hit ITS OWN base:")
    for t in tools:
        out = handlers[t["name"]](action="x")
        print("  ", out)
    print("  recorded bases:", calls)

    print("\nContrast — the buggy lambda-in-loop version:")
    buggy = build_handlers_buggy(discovered, fake_call)
    calls.clear()
    for name in ["manage_scene", "read_console"]:
        buggy[name]()
    print("  called manage_scene & read_console, but recorded bases:", calls)
    print("  ^ both hit the LAST tool — that's the late-binding bug the factory avoids.")


if __name__ == "__main__":
    main()
