# s19b: Real MCP Client — 把 mock 换成真异步

[中文](README.md) · [English](README.en.md)

s01 → ... → s18 → s19 → `s19b` → `s19c` → `s19d` → `s19e` → `s19f` → [s20](../s20_comprehensive/)

> *"把 mock 换成真异步"* — 一个后台线程，一个常驻事件循环，一次握手复用到底。
>
> **Harness 层（s19 分支）**: 真实 MCP 客户端 — 用 sync-over-async 把异步 SDK 接进同步 loop。

---

## 关于命名

`s19b`–`s19f` 是 s19 的**分支功能**（branch），不是主线的下一步：

- 字母后缀沿用 `s08b` 的约定，代表 branch off s19，不打乱 s01–s20 主线编号；
- 文件系统按字母排序时，`s19b_` 恰好落在 `s19_mcp_plugin` 和 `s20_comprehensive` 之间；
- 这条支线讲的是：**把 s19 的 mock MCP 变成生产级真实实现，再接入一个真实领域（Unity）**；学完可以直接回到 s20。

---

## 问题

s19 用一个**进程内 mock** 接入 MCP：

```python
class MCPClient:                     # s19 教学版
    def call_tool(self, tool_name, args):
        return self._handlers[tool_name](**args)   # 就是一次普通同步函数调用
```

mock 的好处是不依赖外部服务就能跑通流程。代价是你看不到真实 MCP 的两个硬骨头：

1. **真实 MCP server 是异步的。** 官方 Python SDK（`mcp.ClientSession`）基于 asyncio，走 stdio / SSE / Streamable HTTP。它的 `initialize` / `list_tools` / `call_tool` 全是 `async def`。
2. **我们的 agent loop 是同步的。** 从 s01 起，主循环就是一个普通的 `while True`。

如果每次工具调用都 `asyncio.run(session.call_tool(...))`，你会在**每一次调用**都重新建立连接、重新握手、重新关闭——又慢又浪费。真实 Unity 一个会话里要调几十上百次工具，这个代价无法接受。

你需要一座桥：**同步世界调用，异步世界执行，且连接只握手一次。**

---

## 解决方案

核心：一个后台线程独占一个**常驻** asyncio 事件循环和一个**常驻** session。主线程用 `asyncio.run_coroutine_threadsafe()` 把协程"扔"进那个循环执行。

```
  主线程 (agent loop, 同步)              后台线程 (asyncio, 常驻)
  ─────────────────────────            ──────────────────────────
  client.start() ───────────────────▶  loop.run_forever()
                                          └─ await session.initialize()   ← 握手 1 次
  client.call_tool("manage_scene") ──▶  run_coroutine_threadsafe
        │  future.result(timeout)          └─ await session.call_tool()
        ◀───────────────────────────────  返回结果（复用同一 session）
  client.call_tool(...) × N ─────────▶  ... 不再握手 ...
  client.close() ───────────────────▶  loop.stop() → thread.join()
```

三个要点：

- **握手一次**：`start()` 里 `await session.initialize()` 只跑一次；之后所有 `call_tool` 复用同一个 session。
- **超时不卡死**：`future.result(timeout=...)` 给每次调用一个预算，超了抛 `MCPConnectionError`，而不是无限等待。
- **掉线重连一次**：session 断了（`ConnectionError`）就重握手一次再重试；再失败才抛错。

---

## 工作原理

### 桥的核心：run_coroutine_threadsafe

```python
def _run(self, coro, timeout):
    future = asyncio.run_coroutine_threadsafe(coro, self._loop)  # 扔进后台循环
    try:
        return future.result(timeout=timeout)                    # 同步等结果
    except FutureTimeoutError as exc:
        future.cancel()
        raise MCPConnectionError(f"timed out after {timeout}s") from exc
```

`run_coroutine_threadsafe(coro, loop)` 是关键：它把一个协程安排到**另一个线程**里运行的事件循环上，返回一个 `concurrent.futures.Future`。主线程 `future.result(timeout)` 同步阻塞等待——超时就抛，绝不永久挂起。

### 常驻循环：一个线程养一个 loop

```python
def start(self):
    self._loop = asyncio.new_event_loop()
    self._thread = threading.Thread(target=self._run_loop, daemon=True)
    self._thread.start()
    self._run(self._connect(), self.timeout + 1)   # 阻塞直到握手完成

def _run_loop(self):
    asyncio.set_event_loop(self._loop)
    self._loop.run_forever()      # 一直活着，直到 close() 里 loop.stop()
    self._loop.close()
```

`run_forever()` 让循环常驻。session 在 `_connect()` 里建立后一直存活，供后续所有调用复用。

### 重连：只握手一次，然后重试

```python
def call_tool(self, name, args, *, delay=0.02):
    attempts = self.reconnect_attempts + 1
    for i in range(attempts):
        try:
            return self._run(self._session.call_tool(name, args, delay=delay), self.timeout)
        except ConnectionError as exc:            # session 掉线
            if i >= attempts - 1:
                raise MCPConnectionError(f"still failing after reconnect: {exc}")
            self._run(self._connect(), self.timeout + 1)   # 重握手一次
```

注意分工：**超时**（`MCPConnectionError`）直接向上抛，不重连；**掉线**（`ConnectionError`）才重握手重试。两个问题分开处理，语义清晰。

> 生产版 [`scripts/utils/mcp_client.py`](../scripts/utils/mcp_client.py) 里，超时也会触发一次重连（因为超时往往意味着连接本身出了问题）；这里教学版把两者拆开，是为了让你先看清两个独立的机制。

### 友好错误：不把 async traceback 丢给模型

```python
class MCPConnectionError(RuntimeError):
    """Friendly, model-facing error instead of a raw async traceback."""
```

真实 Unity 没开、端口没监听、编译卡住时，底层会抛一堆 asyncio/httpx 异常。全部收敛成一句人话，模型才能据此决策（"Unity 没开，先 unity_connect"），而不是被 traceback 淹没。

---

## 相对 s19 的变更

| 组件 | s19（mock） | s19b（真异步） |
|------|------------|---------------|
| session | 进程内同步函数 | 常驻 asyncio session（模拟真实 SDK） |
| 调用方式 | 直接函数调用 | run_coroutine_threadsafe 跨线程 |
| 握手 | 无 | initialize 一次，全程复用 |
| 超时 | 无 | future.result(timeout) 有界，不挂起 |
| 掉线 | 无 | 重握手一次再重试 |
| 生命周期 | 无 | start / call / close，后台线程干净退出 |
| 错误 | 直接返回字符串 | 收敛成 MCPConnectionError 友好信息 |

---

## 试一下

```sh
cd learn-claude-code
python s19b_real_mcp_client/code.py
```

观察重点：

1. **持久 session**：3 次 `call_tool` 全部打印 `[handshake #1]`——证明只握手了一次，session 被复用。
2. **超时**：一个 `delay=2.0` 的慢调用在 0.5s 预算下 `caught: timed out`，不会永久卡住。
3. **重连**：`drop()` 掐断 session 后，下一次调用打印 `[reconnect] ...` 然后 `[handshake #2]`——只有掉线才会产生新握手。

整个 demo 不需要真实 Unity、不需要 mcp SDK、不需要网络。

---

## 接下来

现在同步 loop 能稳定地调用异步 MCP server 了。但真实 server 返回的是一堆带 `inputSchema` 和 `annotations` 的工具定义——不是 s19 那种手写 mock。

s19c Dynamic Discovery → 把真实发现到的工具转成 Anthropic 工具格式：schema 转换、命名空间、名称规范化、防"晚绑定"、按分组过滤。

<details>
<summary>深入：这段代码在生产里长什么样</summary>

真实实现见 [`scripts/utils/mcp_client.py`](../scripts/utils/mcp_client.py) 的 `MCPClient` 类：

- `_open_transport()` 用官方 SDK 的 `streamable_http_client(url, headers, timeout, ...)`，并优先新符号名、回退旧名做前后兼容。
- `_session_main()` 是那个"常驻协程"：在**同一个** task 里进入并退出两层 async context manager（transport + `ClientSession`），因为 MCP 的 context manager 是 task-bound 的，不能跨 task 进/出。它用 `await self._stop.wait()` 把 context 一直挂住。
- `_connect()` 用 `asyncio.wait_for(self._ready.wait(), timeout)` 等待就绪，握手失败也会把 `_ready` set 上，等待方再检查 `_connect_error`——避免死等。
- 真实 URL 默认 `http://127.0.0.1:8080/mcp`，可用环境变量 `UNITY_MCP_URL` 覆盖，绝不硬编码。

一句话：教学版用 `FakeAsyncSession` 演示"桥"的形状，生产版把 `FakeAsyncSession` 换成真正的 `mcp.ClientSession` over Streamable HTTP，桥的结构完全一样。

</details>
