#!/usr/bin/env python3
"""
s19f_result_control/code.py — Result control + Observe->Act->Verify + wiring

The final branch chapter. Unity tool RESULTS are the last trap: a `CallToolResult`
can carry tens of thousands of hierarchy lines, hundreds of KB of screenshot
base64, or big structured JSON. Forward that raw into the LLM context and you
blow the token budget in one call.

This chapter:
  1. Serializes a CallToolResult into ONE compact string.
  2. Strips image/screenshot base64 -> a short metadata placeholder (never the blob).
  3. Truncates over-long output with a clear marker.
  4. Turns errors into stable, model-facing strings (never a raw traceback).
  5. Shows the Observe -> Act -> Verify rhythm with tiny helpers.
  6. Sketches the domain wiring (config + skill + the E2E summary shape).

Run:
    python s19f_result_control/code.py
"""

from __future__ import annotations

import json
import time

MAX_RESULT_CHARS = 2000  # small here so the demo can show truncation


# ═══════════════════════════════════════════════════════════
#  Fake CallToolResult content blocks (stand in for mcp.types)
# ═══════════════════════════════════════════════════════════
class FakeText:
    type = "text"

    def __init__(self, text): self.text = text


class FakeImage:
    type = "image"

    def __init__(self, data, mimeType="image/png"): self.data, self.mimeType = data, mimeType


class FakeResult:
    def __init__(self, content=None, structuredContent=None, isError=False):
        self.content, self.structuredContent, self.isError = content, structuredContent, isError


# ═══════════════════════════════════════════════════════════
#  1-4) The formatter
# ═══════════════════════════════════════════════════════════
def _stringify_block(block) -> str:
    if getattr(block, "type", None) == "text" or hasattr(block, "text"):
        return str(getattr(block, "text", ""))
    if getattr(block, "type", None) in ("image", "audio") or hasattr(block, "data"):
        mime = getattr(block, "mimeType", "binary")
        size = len(getattr(block, "data", "") or "")
        return f"[image omitted: {mime}, ~{size} base64 chars — not sent to the model]"
    return str(block)


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars — narrow the query or page]"


def format_result(tool_name: str, result) -> str:
    if result is None:
        return "(no result)"
    parts = [_stringify_block(b) for b in (getattr(result, "content", None) or [])]
    body = "\n".join(p for p in parts if p).strip()
    if not body and getattr(result, "structuredContent", None) is not None:
        body = json.dumps(result.structuredContent, ensure_ascii=False, separators=(",", ":"))
    if not body:
        body = "(empty result)"
    if getattr(result, "isError", False):
        return _truncate(f"[unity-tool-error] tool={tool_name}: {body} Diagnose args and retry.")
    return _truncate(body)


def format_error(tool_name: str, exc: BaseException, hint: str = "") -> str:
    suffix = f" Hint: {hint}" if hint else ""
    return f"[unity-tool-error] tool={tool_name} type={type(exc).__name__}: {exc}.{suffix}"


# ═══════════════════════════════════════════════════════════
#  5) Observe -> Act -> Verify helpers
# ═══════════════════════════════════════════════════════════
def wait_for_compile(state_reader, *, timeout=2.0, poll=0.05) -> dict:
    """Poll editor-state text until not compiling AND ready_for_tools."""
    start = time.time()
    while time.time() - start < timeout:
        text = state_reader().lower().replace(" ", "")
        if '"is_compiling":false' in text and '"ready_for_tools":true' in text:
            return {"ready": True, "waited": round(time.time() - start, 2)}
        time.sleep(poll)
    return {"ready": False, "waited": round(time.time() - start, 2)}


def count_console_errors(caller) -> int | None:
    result = caller("read_console", {"action": "get", "types": ["error"], "count": "50"})
    data = json.loads(format_result("read_console", result))
    return len(data.get("data", [])) if isinstance(data, dict) else None


# ═══════════════════════════════════════════════════════════
#  Demo
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print("s19f — Result control + verify + wiring\n" + "=" * 48)

    print("\n[1] text result passes through:")
    print("   ", format_result("manage_scene", FakeResult(content=[FakeText('{"name":"SampleScene"}')])))

    print("\n[2] screenshot base64 is STRIPPED (never sent to the model):")
    big = "QUJD" * 50000  # ~200 KB of fake base64
    out = format_result("manage_camera", FakeResult(content=[FakeImage(big)]))
    print("    ", out)
    print("     base64 present in output?", big in out)

    print("\n[3] over-long output is truncated:")
    huge = "x" * (MAX_RESULT_CHARS + 500)
    print("    ", format_result("manage_scene", FakeResult(content=[FakeText(huge)]))[-70:])

    print("\n[4] errors become stable strings:")
    print("    ", format_result("manage_gameobject", FakeResult(content=[FakeText("target not found")], isError=True)))
    print("    ", format_error("manage_asset", ValueError("bad path"), hint="check the path"))

    print("\n[5] Observe -> Act -> Verify (fake editor that finishes compiling):")
    polls = {"n": 0}

    def state_reader():
        polls["n"] += 1
        compiling = polls["n"] < 3           # 'compiling' for the first 2 polls
        return json.dumps({"data": {"compilation": {"is_compiling": compiling},
                                    "advice": {"ready_for_tools": not compiling}}})

    def caller(tool, args):
        return FakeResult(content=[FakeText('{"success":true,"data":[]}')])  # 0 errors

    wc = wait_for_compile(state_reader)
    print(f"     wait_for_compile -> ready={wc['ready']} after {polls['n']} polls")
    print(f"     console errors   -> {count_console_errors(caller)}")

    print("\n[wiring] the pieces come together as a config-driven, skill-guided agent:")
    summary = {
        "gameobject": "AgentCube", "scene": "Assets/Scenes/SampleScene.unity",
        "transform": {"position": [0, 1, 0]}, "components": ["Transform", "Rigidbody"],
        "material": "Assets/Materials/AgentRed.mat", "console_error_count": 0,
        "screenshot_path": "Assets/Screenshots/AgentCube_verify.png", "scene_saved": True,
    }
    print("     E2E structured summary shape:")
    print("     " + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
