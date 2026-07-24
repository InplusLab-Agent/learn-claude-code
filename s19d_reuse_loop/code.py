#!/usr/bin/env python3
"""
s19d_reuse_loop/code.py — Extend the loop without forking

s19c gave us a pool of Unity tools. Now: how do we add a whole new "mode"
(a Unity agent) WITHOUT copying agent_loop into a second file that then drifts
out of sync forever?

Two lessons:

  1. Reuse, don't fork. Make agent_loop accept backward-compatible keyword
     params (system_prompt, tools, tool_handlers) that DEFAULT to the originals.
     `agent_loop(history)` keeps working; a Unity entry passes its own pool.

  2. A tool pool is a pair. What you OFFER the model (tools) must equal what it
     can EXECUTE (handlers). The subagent bug: offer TOOLS but execute
     SUB_HANDLERS -> the model picks a tool with no handler. The fix: offer the
     matching SUB_TOOLS.

This demo uses a scripted fake LLM, so no API key / network is needed.

Run:
    python s19d_reuse_loop/code.py
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════
#  Minimal message/block types + a scripted fake LLM
# ═══════════════════════════════════════════════════════════
class ToolUse:
    type = "tool_use"

    def __init__(self, name: str, inp: dict) -> None:
        self.name, self.input, self.id = name, inp, "id"


class Text:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class Resp:
    def __init__(self, stop_reason: str, content: list) -> None:
        self.stop_reason, self.content = stop_reason, content


class ScriptedLLM:
    """Tries to call each tool in `wants`, but only if it is actually OFFERED.

    This mimics a real model: it can only call tools it can see in the tool
    list it was given.
    """

    def __init__(self, wants: list[str]) -> None:
        self.wants = list(wants)

    def create(self, *, system: str, tools: list[dict], messages: list) -> Resp:
        offered = {t["name"] for t in tools}
        while self.wants:
            name = self.wants.pop(0)
            if name in offered:
                return Resp("tool_use", [ToolUse(name, {"v": 1})])
        return Resp("end_turn", [Text("done")])


# ═══════════════════════════════════════════════════════════
#  The ONE reusable loop. Note the *, backward-compatible kwargs.
#  `agent_loop(history)` still works because every extra param defaults.
# ═══════════════════════════════════════════════════════════
def echo(**kw) -> str:
    return f"echo{kw}"


def add(a: int = 0, b: int = 0, **_) -> str:
    return f"sum={a + b}"


def unity_ping(**kw) -> str:
    return f"unity pong {kw}"


SYSTEM = "You are a coding agent."
TOOLS = [{"name": "echo"}, {"name": "add"}, {"name": "task"}]     # note: task has NO handler
TOOL_HANDLERS = {"echo": echo, "add": add}                        # task handled specially (like real 'compact')

SUB_TOOLS = [{"name": "echo"}, {"name": "add"}]                   # subagent's OFFER
SUB_HANDLERS = {"echo": echo, "add": add}                        # subagent's EXECUTE (matches SUB_TOOLS)


def agent_loop(messages, *, system_prompt=SYSTEM, tools=TOOLS, tool_handlers=TOOL_HANDLERS, llm=None):
    llm = llm or ScriptedLLM(["echo"])
    transcript = []
    for _ in range(10):  # safety bound
        resp = llm.create(system=system_prompt, tools=tools, messages=messages)
        if resp.stop_reason != "tool_use":
            transcript.append(("text", resp.content[0].text))
            return transcript
        for block in resp.content:
            if block.type != "tool_use":
                continue
            handler = tool_handlers.get(block.name)
            out = handler(**block.input) if handler else f"Unknown tool: {block.name}"
            transcript.append((block.name, out))
    return transcript


# ═══════════════════════════════════════════════════════════
#  Demo
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print("s19d — Extend the loop without forking\n" + "=" * 48)

    # A) Plain coding agent — the ORIGINAL call still works unchanged.
    print("\n[A] Plain agent — agent_loop(history) uses base tools:")
    print("   ", agent_loop([{"role": "user", "content": "hi"}], llm=ScriptedLLM(["add", "echo"])))

    # B) Unity agent — SAME function, augmented pool built over COPIES.
    unity_tools = list(TOOLS) + [{"name": "mcp__unity__ping"}]
    unity_handlers = dict(TOOL_HANDLERS)
    unity_handlers["mcp__unity__ping"] = unity_ping
    print("\n[B] Unity agent — same agent_loop, extra tools/handlers + appendix:")
    print("   ", agent_loop(
        [{"role": "user", "content": "ping unity"}],
        system_prompt=SYSTEM + "\n# Unity mode",
        tools=unity_tools,
        tool_handlers=unity_handlers,
        llm=ScriptedLLM(["mcp__unity__ping"]),
    ))
    print("    base TOOLS untouched:", [t["name"] for t in TOOLS])

    # C) Subagent tool-pool consistency.
    print("\n[C] Subagent — a tool pool is a PAIR (offer == execute):")
    sub_llm_buggy = ScriptedLLM(["task", "echo"])   # model 'wants' task first
    print("   BUGGY (offer TOOLS, execute SUB_HANDLERS):")
    print("     ", agent_loop([{"role": "user", "content": "sub"}],
                              tools=TOOLS, tool_handlers=SUB_HANDLERS, llm=sub_llm_buggy))
    print("       ^ model saw 'task' (offered) but there's no handler -> Unknown tool.")

    sub_llm_fixed = ScriptedLLM(["task", "echo"])   # same intent
    print("   FIXED (offer SUB_TOOLS, execute SUB_HANDLERS):")
    print("     ", agent_loop([{"role": "user", "content": "sub"}],
                              tools=SUB_TOOLS, tool_handlers=SUB_HANDLERS, llm=sub_llm_fixed))
    print("       ^ 'task' not offered -> model can't pick it -> falls through to echo.")


if __name__ == "__main__":
    main()
