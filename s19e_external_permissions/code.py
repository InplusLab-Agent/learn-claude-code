#!/usr/bin/env python3
"""
s19e_external_permissions/code.py — Permission classes for external tools

s19d put Unity tools in the main pool. But `manage_gameobject delete` erases
work and `execute_menu_item` runs arbitrary code. We can't let the model fire
those silently.

s03 gave us permission gates; s04 moved them onto a PreToolUse hook. This
chapter classifies EXTERNAL (discovered) tools into four tiers and gates them
with the same hook system — independent of the global bash policy.

The subtle, important part: Unity marks multi-action tools like `manage_scene`
with a coarse tool-level `destructiveHint=True`. If you trust that blindly,
reading a hierarchy or creating a Cube gets mis-flagged as DESTRUCTIVE and the
basic demo drowns in prompts. So the specific `action` must WIN over the coarse
hint.

Run:
    python s19e_external_permissions/code.py
"""

from __future__ import annotations

from enum import Enum


class P(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"
    ARBITRARY = "arbitrary_execution"


ARBITRARY_TOOLS = {"execute_menu_item", "execute_code", "execute_custom_tool", "batch_execute"}
DESTRUCTIVE_KEYWORDS = ("delete", "remove", "destroy")
READ_ONLY_PREFIXES = ("get", "read", "list", "search", "find", "ping", "telemetry")


def classify_tool(base: str, args: dict | None = None, annotations: dict | None = None) -> P:
    args, ann = args or {}, annotations or {}
    name = base.lower()
    action = str(args.get("action", "")).lower()
    has_action = bool(action)

    # 1) Arbitrary execution — the most sensitive, name-based.
    if name in ARBITRARY_TOOLS:
        return P.ARBITRARY

    # 2) read_console is read-only unless it clears.
    if name == "read_console":
        return P.MUTATING if action == "clear" else P.READ_ONLY
    if "screenshot" in name or "screenshot" in action:
        return P.READ_ONLY

    # 3) An explicit read-only annotation is authoritative.
    if ann.get("readOnlyHint") is True:
        return P.READ_ONLY

    # 4) THE KEY RULE: the specific action beats the coarse tool-level
    #    destructiveHint. Unity sets destructiveHint=True on manage_scene etc.
    if has_action:
        if action.startswith(READ_ONLY_PREFIXES):
            return P.READ_ONLY
        if any(k in action for k in DESTRUCTIVE_KEYWORDS):
            return P.DESTRUCTIVE
        return P.MUTATING

    # 5) No action -> fall back to the annotation.
    if ann.get("destructiveHint") is True:
        return P.DESTRUCTIVE
    return P.MUTATING


# ═══════════════════════════════════════════════════════════
#  Policy: allow / ask / deny per class. Conservative defaults.
# ═══════════════════════════════════════════════════════════
DEFAULT_POLICY = {
    P.READ_ONLY: "allow",
    P.MUTATING: "allow",
    P.DESTRUCTIVE: "ask",
    P.ARBITRARY: "ask",
}


# ═══════════════════════════════════════════════════════════
#  PreToolUse hook (reuses the s04 hook shape). Returns None to
#  allow, or a denial string to block. Non-Unity tools pass through.
# ═══════════════════════════════════════════════════════════
class Block:
    def __init__(self, name: str, inp: dict) -> None:
        self.name, self.input = name, inp


def permission_hook(block, *, prefix="mcp__unity__", meta=None, policy=None, approve=lambda *_: False):
    if not block.name.startswith(prefix):
        return None  # not a Unity tool — not our concern (composes with bash hook)
    policy = policy or DEFAULT_POLICY
    info = (meta or {}).get(block.name, {})
    base = info.get("base", block.name[len(prefix):])
    cls = classify_tool(base, block.input, info.get("annotations", {}))
    decision = policy.get(cls, "ask")
    if decision == "allow":
        return None
    if decision == "deny":
        return f"denied by policy: {cls.value} '{base}'"
    # ask — interactive in production; here a pluggable approver keeps it non-interactive
    return None if approve(base, cls) else f"denied by user: {cls.value} '{base}'"


# ═══════════════════════════════════════════════════════════
#  Demo
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print("s19e — Permission classes for external tools\n" + "=" * 52)

    dh = {"title": "Manage Scene", "destructiveHint": True}  # coarse tool-level hint
    samples = [
        ("manage_scene", {"action": "get_hierarchy"}, dh),
        ("manage_scene", {"action": "save"}, dh),
        ("manage_gameobject", {"action": "create"}, dh),
        ("manage_gameobject", {"action": "delete"}, dh),
        ("manage_components", {"action": "remove"}, {}),
        ("read_console", {"action": "get"}, {}),
        ("read_console", {"action": "clear"}, {}),
        ("execute_menu_item", {}, {}),
        ("run_tests", {}, {"destructiveHint": True}),  # no action -> falls back to hint
    ]

    print(f"\n{'tool':<20}{'action':<14}{'class':<20}{'policy'}")
    print("-" * 62)
    for base, args, ann in samples:
        cls = classify_tool(base, args, ann)
        print(f"{base:<20}{str(args.get('action','')):<14}{cls.value:<20}{DEFAULT_POLICY[cls]}")

    print("\nKey point: manage_scene has destructiveHint=True, yet")
    print("  get_hierarchy -> READ_ONLY, save -> MUTATING (action beats the coarse hint).")
    print("  Only delete/remove -> DESTRUCTIVE. So the Cube demo never prompts.")

    print("\nHook in action (auto-deny 'ask' for a non-interactive run):")
    meta = {
        "mcp__unity__manage_gameobject": {"base": "manage_gameobject", "annotations": dh},
    }
    for action in ["create", "delete"]:
        b = Block("mcp__unity__manage_gameobject", {"action": action})
        result = permission_hook(b, meta=meta)  # default approve() -> False (deny on ask)
        print(f"  manage_gameobject {action:<7} -> {result if result else 'ALLOWED'}")

    b = Block("bash", {"command": "ls"})
    print(f"  bash (non-Unity)        -> {permission_hook(b, meta=meta) or 'passes through (None)'}")


if __name__ == "__main__":
    main()
