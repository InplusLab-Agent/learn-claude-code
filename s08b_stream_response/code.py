#!/usr/bin/env python3
"""
s08b_stream_response/code.py — Streaming Response

Demonstrates the streaming wrapper pattern built on top of s08.

The core addition over s08: create_message(**kwargs) is a drop-in for
client.messages.create(**kwargs).  When streaming.enabled=True in
config.yaml it switches to client.messages.stream(), fires 5 new Hook
events for real-time display, then returns the same Message object.

New Hook events:
  OnThinkingStart              — thinking block begins
  OnThinkingDelta(chunk: str)  — each thinking text chunk
  OnTextStart                  — text block begins
  OnTextDelta(chunk: str)      — each text chunk
  OnBlockStop(block_type: str) — any content block ends ("thinking"|"text"|...)

Design principles carried forward from s08:
  • Config-driven  — toggle in config.yaml, no code changes needed
  • Hook-extensible — new subscribers can react to stream events
  • Backward-compat — agent_loop unchanged; same Message return type

Usage:
    python s08b_stream_response/code.py

    Set streaming.enabled: true in scripts/config.yaml to watch live output.
    Needs: pip install anthropic python-dotenv pyyaml + .env with MODEL_ID
"""

import os, sys
from pathlib import Path

try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

MODEL  = os.environ["MODEL_ID"]
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
SYSTEM = "You are a helpful assistant. Answer clearly and concisely."


# ═══════════════════════════════════════════════════════════
#  Config helper
# ═══════════════════════════════════════════════════════════

def load_config(path: str = "scripts/config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ═══════════════════════════════════════════════════════════
#  Hook System (same pattern as s04, extended with stream events)
# ═══════════════════════════════════════════════════════════

HOOKS: dict[str, list] = {
    # s04 compatible
    "OnThinking": [],       # batch: full ThinkingBlock available

    # s08b new — streaming only
    "OnThinkingStart": [],  # thinking block begins
    "OnThinkingDelta": [],  # (chunk: str) each thinking chunk
    "OnTextStart": [],      # text block begins
    "OnTextDelta": [],      # (chunk: str) each text chunk
    "OnBlockStop": [],      # (block_type: str) block ends
}


def register_hook(event: str, fn) -> None:
    HOOKS[event].append(fn)


def fire(event: str, *args) -> None:
    for fn in HOOKS[event]:
        fn(*args)


# ═══════════════════════════════════════════════════════════
#  Streaming hook implementations
#  Each handler writes directly to stdout without buffering.
# ═══════════════════════════════════════════════════════════

_ANSI_THINKING = "\033[90m"   # dim grey  — thinking text
_ANSI_TEXT     = "\033[34m"   # blue      — assistant reply
_ANSI_RESET    = "\033[0m"


def stream_thinking_start_hook() -> None:
    if load_config().get("streaming", {}).get("show_thinking", True):
        sys.stdout.write(f"\n{_ANSI_THINKING}\u25b7 Thinking: ")
        sys.stdout.flush()


def stream_thinking_delta_hook(chunk: str) -> None:
    if load_config().get("streaming", {}).get("show_thinking", True):
        sys.stdout.write(chunk)
        sys.stdout.flush()


def stream_text_start_hook() -> None:
    if load_config().get("streaming", {}).get("show_text", True):
        sys.stdout.write(f"\n{_ANSI_TEXT}")
        sys.stdout.flush()


def stream_text_delta_hook(chunk: str) -> None:
    if load_config().get("streaming", {}).get("show_text", True):
        sys.stdout.write(chunk)
        sys.stdout.flush()


def stream_block_stop_hook(block_type: str | None) -> None:
    cfg = load_config().get("streaming", {})
    if block_type == "thinking" and cfg.get("show_thinking", True):
        sys.stdout.write(f"{_ANSI_RESET}\n")
        sys.stdout.flush()
    elif block_type == "text" and cfg.get("show_text", True):
        sys.stdout.write(f"{_ANSI_RESET}\n")
        sys.stdout.flush()


register_hook("OnThinkingStart", stream_thinking_start_hook)
register_hook("OnThinkingDelta", stream_thinking_delta_hook)
register_hook("OnTextStart",     stream_text_start_hook)
register_hook("OnTextDelta",     stream_text_delta_hook)
register_hook("OnBlockStop",     stream_block_stop_hook)


# ═══════════════════════════════════════════════════════════
#  create_message — drop-in for client.messages.create()
#
#  Batch path  (streaming.enabled=false):
#      create_message(**kwargs) → client.messages.create(**kwargs) → Message
#
#  Streaming path  (streaming.enabled=true):
#      create_message(**kwargs) → client.messages.stream(**kwargs)
#          → event loop → Hook events → get_final_message() → Message
# ═══════════════════════════════════════════════════════════

def create_message(**kwargs):
    """
    Drop-in replacement for client.messages.create(**kwargs).

    Streaming path fires Hook events so any registered subscriber can
    react to each chunk.  The final return value is always a Message.
    """
    cfg = load_config().get("streaming", {})

    if not cfg.get("enabled", False):
        # ── Batch path (unchanged from s08) ──────────────────────────
        return client.messages.create(**kwargs)

    # ── Streaming path (s08b new) ────────────────────────────────────
    # Optionally inject extended thinking if thinking_budget is configured.
    thinking_budget = cfg.get("thinking_budget")
    if thinking_budget and "thinking" not in kwargs:
        kwargs = {**kwargs, "thinking": {"type": "enabled", "budget_tokens": int(thinking_budget)}}

    _state: dict = {"block_type": None}

    def _dispatch(event) -> None:
        """Route one stream event to the Hook system."""
        etype = getattr(event, "type", None)

        if etype == "content_block_start":
            btype = getattr(getattr(event, "content_block", None), "type", None)
            _state["block_type"] = btype
            if btype == "thinking":
                fire("OnThinkingStart")
            elif btype == "text":
                fire("OnTextStart")

        elif etype == "content_block_delta":
            delta = getattr(event, "delta", None)
            if delta is None:
                return
            dtype = getattr(delta, "type", None)
            if dtype == "thinking_delta":
                fire("OnThinkingDelta", getattr(delta, "thinking", ""))
            elif dtype == "text_delta":
                fire("OnTextDelta", getattr(delta, "text", ""))

        elif etype == "content_block_stop":
            fire("OnBlockStop", _state["block_type"])
            _state["block_type"] = None

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            _dispatch(event)
        return stream.get_final_message()


# ═══════════════════════════════════════════════════════════
#  Minimal agent loop — focused on the streaming demo.
#  (Tool use and compact omitted; see s02 / s08 for full pattern.)
# ═══════════════════════════════════════════════════════════

def agent_loop(messages: list) -> None:
    while True:
        # create_message is a drop-in: same kwargs, same return type.
        # The agent_loop itself has zero awareness of streaming mode.
        response = create_message(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            max_tokens=4096,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Batch mode: text hasn't been printed yet — print now.
            # Streaming mode: text was already printed live via OnTextDelta.
            streaming_on = load_config().get("streaming", {}).get("enabled", False)
            if not streaming_on:
                for block in response.content:
                    if getattr(block, "type", None) == "text":
                        print(f"\n{_ANSI_TEXT}{block.text}{_ANSI_RESET}")
            return

        # Tool-use handling omitted — see s02 / s08 for full implementation.
        # The streaming path still fires OnTextDelta for any text blocks
        # that appear before the tool_use, so no changes needed there either.
        return


# ═══════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    streaming_on = load_config().get("streaming", {}).get("enabled", False)
    mode_label   = "流式 (streaming)" if streaming_on else "批量 (batch)"

    print(f"s08b: Stream Response Demo  [{mode_label}]")
    print("  修改 scripts/config.yaml → streaming.enabled: true 切换到流式模式")
    print("  Type 'q' to quit.\n")

    history: list[dict] = []
    while True:
        try:
            query = input("\033[36m Input >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
