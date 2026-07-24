#!/usr/bin/env python3
"""
s19b_real_mcp_client/code.py — Real MCP Client (sync over async)

s19 connected to MCP servers with an in-process **mock**: MCPClient.call_tool()
was a plain synchronous function call. Real MCP servers speak an **async**
protocol (asyncio streams over stdio / SSE / Streamable HTTP). But our agent
loop (s01 onward) is a plain synchronous `while` loop.

This chapter shows the bridge: one background thread owning one persistent
asyncio event loop and one persistent session. Sync calls from the main thread
are marshalled onto that loop with `asyncio.run_coroutine_threadsafe()` — so we
pay the connect/handshake cost ONCE, not on every tool call.

What this demo proves (no network, no mcp SDK, no Unity required):
  • start(): connect + initialize exactly once (persistent session)
  • call_tool(): many sync calls reuse the same session (no re-handshake)
  • timeout: a slow call raises instead of hanging forever
  • reconnect: a dropped session is re-established once, then the call retries
  • close(): the background loop and thread shut down cleanly

Run:
    python s19b_real_mcp_client/code.py
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeoutError


# ═══════════════════════════════════════════════════════════
#  A fake ASYNC MCP session — stands in for the real SDK.
#  The real thing is `mcp.ClientSession` over Streamable HTTP.
#  Here we just sleep to simulate network latency + a handshake.
# ═══════════════════════════════════════════════════════════
class FakeAsyncSession:
    total_handshakes = 0  # shared across sessions so the demo can prove reuse

    def __init__(self) -> None:
        self.id = 0
        self.alive = True

    async def initialize(self) -> None:
        await asyncio.sleep(0.05)                 # simulate the connect handshake
        FakeAsyncSession.total_handshakes += 1
        self.id = FakeAsyncSession.total_handshakes

    async def list_tools(self) -> list[str]:
        await asyncio.sleep(0.01)
        return ["manage_scene", "manage_gameobject", "read_console"]

    async def call_tool(self, name: str, args: dict, *, delay: float = 0.02) -> str:
        if not self.alive:
            raise ConnectionError("session dropped")   # simulate a broken pipe
        await asyncio.sleep(delay)                       # simulate round-trip
        return f"{name}({args}) -> ok  [handshake #{self.id}]"


# ═══════════════════════════════════════════════════════════
#  The sync-over-async client. This is the pattern that matters.
# ═══════════════════════════════════════════════════════════
class MCPConnectionError(RuntimeError):
    """Friendly, model-facing error instead of a raw async traceback."""


class SyncMCPClient:
    def __init__(self, *, timeout: float = 1.0, reconnect_attempts: int = 1) -> None:
        self.timeout = timeout
        self.reconnect_attempts = reconnect_attempts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: FakeAsyncSession | None = None
        self._started = False

    # ── lifecycle ────────────────────────────────────────────
    def start(self) -> None:
        if self._started:
            return
        # 1) spin up a background thread that owns one event loop forever
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-loop")
        self._thread.start()
        # 2) connect + initialize ONCE, blocking until ready
        self._run(self._connect(), self.timeout + 1)
        self._started = True

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()             # lives until close() stops it
        self._loop.close()

    async def _connect(self) -> None:
        session = FakeAsyncSession()
        await session.initialize()           # the one-time handshake
        self._session = session

    # ── the bridge: run an async coroutine from the sync world ──
    def _run(self, coro, timeout: float):
        if self._loop is None:
            raise MCPConnectionError("event loop not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPConnectionError(f"timed out after {timeout}s") from exc

    # ── sync API the agent loop actually calls ─────────────────
    def list_tools(self) -> list[str]:
        self._require_started()
        return self._run(self._session.list_tools(), self.timeout)

    def call_tool(self, name: str, args: dict, *, delay: float = 0.02) -> str:
        self._require_started()
        # A timeout (MCPConnectionError) propagates immediately.
        # A dropped session (ConnectionError) triggers up to reconnect_attempts
        # re-handshake-and-retry cycles.
        attempts = self.reconnect_attempts + 1
        for i in range(attempts):
            try:
                return self._run(self._session.call_tool(name, args, delay=delay), self.timeout)
            except ConnectionError as exc:
                if i >= attempts - 1:
                    raise MCPConnectionError(f"still failing after reconnect: {exc}") from exc
                print(f"    [reconnect] attempt {i + 1}/{self.reconnect_attempts} after: {exc}")
                self._run(self._connect(), self.timeout + 1)   # re-handshake once

    def drop(self) -> None:
        """Simulate the server dropping our session (for the demo)."""
        if self._session:
            self._session.alive = False

    def close(self) -> None:
        if not self._started:
            return
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)     # stop run_forever()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._started = False

    def _require_started(self) -> None:
        if not self._started or self._session is None:
            raise MCPConnectionError("client not started — call start() first")


# ═══════════════════════════════════════════════════════════
#  Demo
# ═══════════════════════════════════════════════════════════
def main() -> None:
    print("s19b — Real MCP Client (sync over async)\n" + "=" * 48)

    client = SyncMCPClient(timeout=0.5, reconnect_attempts=1)
    client.start()
    print(f"[start] connected. tools = {client.list_tools()}")

    print("\n[persistent session] 3 sync calls, all reuse ONE handshake:")
    for i in range(3):
        print("   ", client.call_tool("manage_scene", {"action": "get_active", "n": i}))

    print("\n[timeout] a call slower than the 0.5s budget raises (not hang):")
    try:
        client.call_tool("read_console", {"action": "get"}, delay=2.0)
    except MCPConnectionError as exc:
        print("    caught:", exc)

    print("\n[reconnect] drop the session, next call re-handshakes once then succeeds:")
    client.drop()
    print("   ", client.call_tool("manage_gameobject", {"action": "create"}))

    client.close()
    print("\n[close] background loop + thread stopped cleanly.")


if __name__ == "__main__":
    main()
