# s08b: Stream Response — 不等响应到齐，边收边看

[中文](README.md) · [English](README.en.md)

s01 → ... → s07 → s08 → `s08b` → [s09](../s09_memory/) → ...

> *"不等响应到齐, 边收边看"* — drop-in 包装器 + 5 个 Hook 事件，关闭时与 s08 完全一致。
>
> **Harness 层 (s08 分支)**: 流式响应 — 思考链与文字的实时打印。

---

## 关于命名

`s08b` 是 s08 的**分支功能**（branch），不是主线的下一步：

- 字母 `b` 代表 branch off s08，不破坏 s01–s20 主线编号；
- 文件系统按字母排序时，`s08b_` 恰好夹在 `s08_context_compact` 和 `s09_memory` 之间；
- 关掉 `streaming.enabled`，行为与 s08 完全一致，可以完全跳过这节继续 s09。

---

## 问题

s08 的 LLM 调用是阻塞的：

```python
response = client.messages.create(...)   # 等到整个响应到达
```

对思考型模型（如 claude-opus-4 / claude-3-7-sonnet），一次含 extended thinking 的回复
可能需要 30–60 秒。这段时间里终端**没有任何输出**：用户不知道模型还在运算，
还是已经卡住了。

---

## 解决方案

![Stream Overview](images/stream-overview.svg)

核心设计：`create_message(**kwargs)` 作为 `client.messages.create(**kwargs)` 的透明替换。

- **关闭时**（`streaming.enabled: false`，默认）：直接调 `client.messages.create()`，行为与 s08 完全一致；
- **开启时**（`streaming.enabled: true`）：切换到 `client.messages.stream()`，每收到一个 chunk 立即触发 Hook 事件打印到终端，最后调 `get_final_message()` 返回相同的 `Message` 对象；
- **`agent_loop` 无需改动**：返回类型不变，主循环不感知两种模式的差异。

---

## 工作原理

### create_message：两条路径

```
create_message(**kwargs)
        │
        ├─ streaming.enabled=false ──→ client.messages.create()
        │                                       │ (阻塞等待)
        │                                     Message
        │
        └─ streaming.enabled=true ───→ client.messages.stream()
                                                │
                                          event loop
                                                │ OnThinkingStart  → hook
                                                │ OnThinkingDelta  → hook × N
                                                │ OnBlockStop      → hook
                                                │ OnTextStart      → hook
                                                │ OnTextDelta      → hook × N
                                                │ OnBlockStop      → hook
                                                │
                                         get_final_message()
                                                │
                                             Message  ← 同一类型，agent_loop 零感知
```

两条路径的代码实现：

```python
def create_message(**kwargs):
    cfg = load_config().get("streaming", {})

    if not cfg.get("enabled", False):
        return client.messages.create(**kwargs)   # 批量路径，原封不动

    # 流式路径：事件循环 → Hook → 返回同一 Message
    _state = {"block_type": None}

    def _dispatch(event):
        etype = getattr(event, "type", None)
        if etype == "content_block_start":
            btype = getattr(getattr(event, "content_block", None), "type", None)
            _state["block_type"] = btype
            if btype == "thinking": fire("OnThinkingStart")
            elif btype == "text":   fire("OnTextStart")
        elif etype == "content_block_delta":
            delta = getattr(event, "delta", None)
            if delta:
                if delta.type == "thinking_delta": fire("OnThinkingDelta", delta.thinking)
                elif delta.type == "text_delta":   fire("OnTextDelta",     delta.text)
        elif etype == "content_block_stop":
            fire("OnBlockStop", _state["block_type"])

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            _dispatch(event)
        return stream.get_final_message()
```

### 5 个新 Hook 事件

![Hook Events](images/hook-events.svg)

5 个新事件全部只在 `streaming.enabled=true` 时触发。`OnThinking`（s08 原有，用于批量模式的完整思考块）保持不变。

`show_thinking_hook`（`OnThinking` 的处理函数）加了一个守卫：

```python
def show_thinking_hook(block):
    # 流式模式下 OnThinkingDelta 已实时打印，跳过整块重复打印
    if load_config().get("streaming", {}).get("enabled", False):
        return None
    if load_config().get("show_thinking", True):
        print(f"[HOOK] Thinking: {block.thinking}\n")
    return None
```

### agent_loop 的守卫

流式模式下 text 在 `OnTextDelta` 里已逐字打印，主循环里的打印需要跳过：

```python
# InplusCode.py — tool_use 分支里的文字打印
elif block.type == "text":
    if not load_config().get("streaming", {}).get("enabled", False):
        print(f"[blue]{block.text}[/blue]\n")

# __main__ 里的最终文字打印
if not load_config().get("streaming", {}).get("enabled", False):
    for block in response_content:
        if getattr(block, "type", None) == "text":
            print(f"\n{block.text}")
```

### extended thinking（可选）

在 config.yaml 里设置 `thinking_budget`，`create_message` 会自动注入 `thinking` 参数：

```python
thinking_budget = cfg.get("thinking_budget")
if thinking_budget and "thinking" not in kwargs:
    kwargs = {**kwargs, "thinking": {"type": "enabled", "budget_tokens": int(thinking_budget)}}
```

> **注意**：extended thinking 需要模型支持（claude-3-7-sonnet / claude-opus-4 等），
> 且 `max_tokens` 必须大于 `thinking_budget`。不配置则忽略，模型按默认行为处理。

---

## 开启方式

在 `scripts/config.yaml` 中：

```yaml
streaming:
  enabled: true           # 开启流式
  show_thinking: true     # 实时显示思考链（dim grey）
  show_text: true         # 实时显示回复文本（blue）
  # thinking_budget: 8000 # 可选：开启 extended thinking（token 预算）
```

---

## 相对 s08 的变更

| 组件 | s08 | s08b |
|------|-----|------|
| LLM 调用 | `client.messages.create()` | `create_message()`（透明包装） |
| 新文件 | — | `utils/stream.py` |
| Hook 事件 | 6 个（含 `OnThinking`） | 11 个（新增 5 个 streaming 事件） |
| `hooks.py` | `show_thinking_hook` 无守卫 | 加 streaming 守卫，避免重复打印 |
| `InplusCode.py` | `client.messages.create()` | `create_message()` + text 打印守卫 |
| `config.yaml` | 无 streaming 段 | 新增 `streaming` 配置块 |
| 返回类型 | `Message` | `Message`（不变） |
| 默认行为 | 批量 | 批量（`enabled: false`，零破坏） |

不变的部分：`agent_loop` 结构、四层压缩管线、所有工具、所有已有 Hook 逻辑。
