# s19b: Real MCP Client — swap the mock for real async

[中文](README.md) · [English](README.en.md)

s01 → ... → s18 → s19 → `s19b` → `s19c` → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"Swap the mock for real async"* — one background thread, one persistent event loop, one handshake reused forever.
>
> **Harness layer (branch off s19)**: a real MCP client — bridge the async SDK into the sync loop with sync-over-async.

---

## About the naming

`s19b`–`s19f` are a **branch** off s19, not the next step in the main sequence:

- The letter suffix follows the `s08b` convention: a branch off s19 that does not disturb the s01–s20 numbering.
- Sorted alphabetically, `s19b_` falls right between `s19_mcp_plugin` and `s20_comprehensive`.
- This branch is about turning s19's **mock** MCP into a **production-grade real** implementation, then wiring it into a real domain (Unity). You can jump straight back to s20 afterwards.

---

## The problem

s19 connected to MCP with an **in-process mock**:

```python
class MCPClient:                     # s19 teaching version
    def call_tool(self, tool_name, args):
        return self._handlers[tool_name](**args)   # just a plain sync call
```

The mock lets the flow run without any external service. The cost is you never see the two hard parts of real MCP:

1. **Real MCP servers are async.** The official Python SDK (`mcp.ClientSession`) is asyncio-based over stdio / SSE / Streamable HTTP. Its `initialize` / `list_tools` / `call_tool` are all `async def`.
2. **Our agent loop is sync.** Since s01, the main loop has been a plain `while True`.

If every tool call did `asyncio.run(session.call_tool(...))`, you would re-connect, re-handshake, and tear down on **every single call** — slow and wasteful. A real Unity session makes dozens to hundreds of tool calls; that cost is unacceptable.

You need a bridge: **call from the sync world, execute in the async world, and handshake only once.**

---

## The solution

Core idea: one background thread owns one **persistent** asyncio event loop and one **persistent** session. The main thread uses `asyncio.run_coroutine_threadsafe()` to hand coroutines to that loop.

```
  main thread (agent loop, sync)         background thread (asyncio, persistent)
  ─────────────────────────            ──────────────────────────
  client.start() ───────────────────▶  loop.run_forever()
                                          └─ await session.initialize()   ← handshake ×1
  client.call_tool("manage_scene") ──▶  run_coroutine_threadsafe
        │  future.result(timeout)          └─ await session.call_tool()
        ◀───────────────────────────────  result (same session reused)
  client.call_tool(...) × N ─────────▶  ... no more handshakes ...
  client.close() ───────────────────▶  loop.stop() → thread.join()
```

Three key properties:

- **Handshake once**: `await session.initialize()` runs once in `start()`; every later `call_tool` reuses that session.
- **Timeout without hanging**: `future.result(timeout=...)` bounds each call; on overrun it raises `MCPConnectionError` instead of waiting forever.
- **Reconnect once**: if the session drops (`ConnectionError`), re-handshake once and retry; only then raise.

---

## How it works

### The bridge: run_coroutine_threadsafe

```python
def _run(self, coro, timeout):
    future = asyncio.run_coroutine_threadsafe(coro, self._loop)  # onto bg loop
    try:
        return future.result(timeout=timeout)                    # sync wait
    except FutureTimeoutError as exc:
        future.cancel()
        raise MCPConnectionError(f"timed out after {timeout}s") from exc
```

`run_coroutine_threadsafe(coro, loop)` schedules a coroutine on an event loop running in **another thread** and returns a `concurrent.futures.Future`. The main thread blocks on `future.result(timeout)` — which raises on overrun, never hanging forever.

### Persistent loop: one thread hosts one loop

```python
def start(self):
    self._loop = asyncio.new_event_loop()
    self._thread = threading.Thread(target=self._run_loop, daemon=True)
    self._thread.start()
    self._run(self._connect(), self.timeout + 1)   # block until handshake done

def _run_loop(self):
    asyncio.set_event_loop(self._loop)
    self._loop.run_forever()      # alive until close() calls loop.stop()
    self._loop.close()
```

`run_forever()` keeps the loop resident. The session established in `_connect()` stays alive and is reused by all later calls.

### Reconnect: re-handshake once, then retry

```python
def call_tool(self, name, args, *, delay=0.02):
    attempts = self.reconnect_attempts + 1
    for i in range(attempts):
        try:
            return self._run(self._session.call_tool(name, args, delay=delay), self.timeout)
        except ConnectionError as exc:            # session dropped
            if i >= attempts - 1:
                raise MCPConnectionError(f"still failing after reconnect: {exc}")
            self._run(self._connect(), self.timeout + 1)   # re-handshake once
```

Note the split: a **timeout** (`MCPConnectionError`) propagates immediately with no reconnect; a **drop** (`ConnectionError`) triggers a re-handshake and retry. Keeping the two concerns separate makes the semantics clear.

> In production [`scripts/utils/mcp_client.py`](../scripts/utils/mcp_client.py), a timeout also triggers a single reconnect (a timeout often means the connection itself is bad). The teaching version splits them so you can see the two mechanisms in isolation first.

### Friendly errors: don't hand an async traceback to the model

```python
class MCPConnectionError(RuntimeError):
    """Friendly, model-facing error instead of a raw async traceback."""
```

When Unity isn't open, the port isn't listening, or it's stuck compiling, the transport throws a pile of asyncio/httpx exceptions. Collapse them into one human sentence so the model can act on it ("Unity is closed, call unity_connect first") instead of drowning in a traceback.

---

## What changed vs s19

| Component | s19 (mock) | s19b (real async) |
|-----------|-----------|-------------------|
| session | in-process sync function | persistent asyncio session (mocks the real SDK) |
| call path | direct function call | run_coroutine_threadsafe across threads |
| handshake | none | initialize once, reused throughout |
| timeout | none | future.result(timeout), bounded, never hangs |
| drop | none | re-handshake once, then retry |
| lifecycle | none | start / call / close, clean thread shutdown |
| errors | raw string | collapsed into a friendly MCPConnectionError |

---

## Try it

```sh
cd learn-claude-code
python s19b_real_mcp_client/code.py
```

What to watch:

1. **Persistent session**: all 3 `call_tool`s print `[handshake #1]` — proof the session was established once and reused.
2. **Timeout**: a slow `delay=2.0` call under the 0.5s budget prints `caught: timed out` instead of hanging.
3. **Reconnect**: after `drop()` kills the session, the next call prints `[reconnect] ...` then `[handshake #2]` — only a drop causes a fresh handshake.

The whole demo needs no real Unity, no mcp SDK, and no network.

---

## Next

Now a sync loop can reliably drive an async MCP server. But a real server returns tool definitions carrying `inputSchema` and `annotations` — not s19's hand-written mocks.

s19c Dynamic Discovery → turn really-discovered tools into the Anthropic tool format: schema conversion, namespacing, name normalization, late-binding safety, and group filtering.

<details>
<summary>Deep dive: what this looks like in production</summary>

See the `MCPClient` class in [`scripts/utils/mcp_client.py`](../scripts/utils/mcp_client.py):

- `_open_transport()` uses the SDK's `streamable_http_client(url, headers, timeout, ...)`, preferring the new symbol name and falling back to the old one for compatibility.
- `_session_main()` is the "persistent coroutine": it enters and exits both async context managers (transport + `ClientSession`) in the **same** task — MCP's context managers are task-bound and cannot be entered/exited across tasks. It holds them open with `await self._stop.wait()`.
- `_connect()` uses `asyncio.wait_for(self._ready.wait(), timeout)`; a failed handshake still sets `_ready`, and the waiter then inspects `_connect_error` — so it never deadlocks.
- The real URL defaults to `http://127.0.0.1:8080/mcp`, overridable via the `UNITY_MCP_URL` environment variable, never hard-coded.

In one line: the teaching version uses `FakeAsyncSession` to show the *shape* of the bridge; production swaps it for a real `mcp.ClientSession` over Streamable HTTP, and the bridge structure is identical.

</details>
