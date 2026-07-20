"""
s08_context_compact.py - Context Compact

Four-layer compaction pipeline inserted before LLM calls:

    L1: snip_compact      — trim middle messages when count > 50
    L2: micro_compact     — replace old tool_results with placeholders
    L3: tool_result_budget — persist large results to disk
    L4: compact_history   — LLM full summary (1 API call)

    Emergency: reactive_compact — when API still returns prompt_too_long

    ┌─────────────────────────────────────────────────────────────┐
    │  messages[]                                                 │
    │    ↓                                                        │
    │  L3 budget ─→ L1 snip ─→ L2 micro ─→ [token > threshold?]  │
    │                                      ├─ No  → LLM          │
    │                                      └─ Yes → L4 summary   │
    │                                              ↓              │
    │                                          LLM call           │
    │                                    [prompt_too_long?]        │
    │                                      └─ Yes → reactive      │
    └─────────────────────────────────────────────────────────────┘

"""

# ═══════════════════════════════════════════════════════════
#  NEW in s08: Four-Layer Compaction Pipeline
# ═══════════════════════════════════════════════════════════

import json, time

from pathlib import Path
from typing_extensions import deprecated
from anthropic.types import ContentBlock, TextBlock
from utils.system import TOOL_RESULTS_DIR, MESSAGES_DIR, MODEL, client

MAX_MESSAGES = 100  # C1
PERSIST_THRESHOLD = 30000  # C3: 超过该字节数的 tool_result 将被持久化到磁盘
KEEP_RECENT = 20  # C2: 允许最近3条tool_result超长保留
COMPACT_CHAR_LIMIT = 400_000  # C4: 上下文最大字符数


def estimate_size(msgs):
    return len(str(msgs))


# ═══════════════════════════════════════════════════════════
#  s08: C1 消息定长裁剪
# ═══════════════════════════════════════════════════════════
# 兼容 自定义用于 user 的 tool_result (dict) 以及 用于 assistant 的、 Anthropic API 返回的 ContentBlock
def _block_type(block: dict | ContentBlock) -> str | None:
    """
    message.get("role") == "user" 并且 results = message.get("content")  并且 results is list (过滤单条文本消息) 并且 block is dist (进入消息本身) ---> block 可能存在 tool_result
    message.get("role") == "assistant" 并且 content = messaget("conent") 并且 content is list (目前 s08版本并没有意义因为antropic返回结果总是List) 并且 block.type ---> block 可能存在 tool_use
    """
    return (block.get("type") if isinstance(block, dict) else getattr(block, "type", None)) # fmt: skip


# user message
def _message_has_tool_result(message: dict) -> bool:
    if message.get("role") != "user":
        return False
    results = message.get("content")
    if not isinstance(results, list): return False # fmt: skip
    return any(_block_type(block) == "tool_result" for block in results)


# assistant message
def _message_has_tool_use(message: dict) -> bool:
    if message.get("role") != "assistant":
        return False
    content = message.get("content")  # respons.content
    if not isinstance(content, list): return False # fmt: skip
    return any(_block_type(block) == "tool_use" for block in content)


# message定长裁剪 —————— snipCompact — trim middle messages
def c1_snip_compact(messages: list[dict], max_messages=MAX_MESSAGES) -> list[dict]:
    # 保留首头部3+尾部k-3条messages，剩余的裁剪；
    # 特殊情况：不能把 assistant(tool_use) 和 其对应的 user(tool_result) 拆开
    """
    [ H1, H2, A(tu), U(tr), U(tr) ] | [ M5, M6, ... ]
                                        ↑
                                        head_end = 5

    [ ..., M(n-1) ] | [ A(tu), U(tr), U(tr), T2, T3, ... ]
                        ↑
                        tail_start
    """

    if len(messages) <= max_messages:
        return messages
    # 裁剪messages中间部分，只保留首位3+47个messages
    keep_head, keep_tail = 3, max_messages - 3
    head_end, tail_start = keep_head, len(messages) - keep_tail

    # 确保 tool_use 和 其后附带的 若干 tool_result 不拆开
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _message_has_tool_result(messages[head_end]):
            head_end += 1

    # fmt: off
    if (tail_start > 0 and tail_start < len(messages)
        and _message_has_tool_result(messages[tail_start])
        and _message_has_tool_use(messages[tail_start - 1])
    ):
        tail_start -= 1
    # fmt: on
    if head_end >= tail_start:
        return messages

    snipped = [{"role": "user", "content": f"[snipped {tail_start - head_end} messages]"}]
    return messages[:head_end] + snipped + messages[tail_start:]


# ═══════════════════════════════════════════════════════════
#  s08: C2 所有超长tool_reults占位
# ═══════════════════════════════════════════════════════════


# user message
def _collect_tool_results(messages: list[dict]) -> list[dict]:
    blocks = []
    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:  # msg["contents"] 即 results
            # if isinstance(block, dict) and block.get("type") == "tool_result":
            if _block_type(block) == "tool_result":
                blocks.append(block)
    return blocks


# 长工具结果占位: 收集所有的tool_result块，除了最近的3个以外，前面所有超长工具结果用占位符代替。
def c2_micro_compact(messages: list[dict]) -> list[dict]:
    tool_results: list[dict] = _collect_tool_results(messages)

    if len(tool_results) <= KEEP_RECENT:
        return messages
    # for _, _, block in tool_results[:-KEEP_RECENT]:
    for block in tool_results[:-KEEP_RECENT]:
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


# ═══════════════════════════════════════════════════════════
#  s08: C3 长tool_result持久化
# ═══════════════════════════════════════════════════════════
# C3: toolResultBudget — persist large results to disk
def _persist_large_output(tool_use_id, content) -> str:  # 将大工具调用的content持久化到磁盘
    if len(content) <= PERSIST_THRESHOLD:
        return content
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)  # mkdir()表示如果目录不存在则创建, parents=True表示递归创建父目录, exist_ok=True表示如果目录已存在则不报错 # fmt: skip
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return f"<persisted-output>\nFull output: {path}\nPreview:\n{content[:2000]}\n</persisted-output>"


# C3: 检查对话历史最后一条消息的 tool_results，优先持久化、并替换体积较大的 tool_result 块。
def c3_tool_result_budget(messages: list[dict], max_bytes=200_000):

    last = messages[-1] if messages else None

    # user message
    if not last or last.get("role") != "user" or not isinstance(last.get("content"), list):
        return messages

    tool_results = _collect_tool_results([last])

    total = sum(len(str(block.get("content", ""))) for block in tool_results)
    if total <= max_bytes:
        return messages
    ranked = sorted(tool_results, key=lambda block: len(str(block.get("content", ""))), reverse=True)

    for block in ranked:
        if total <= max_bytes:
            break  # 压缩完成
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD:
            break  # 后续 tool_result 块都较小，无需继续持久化

        tid = block.get("tool_use_id", "unknown")

        block["content"] = _persist_large_output(tid, content)  # 将大工具调用的content持久化到磁盘并替换原本内容

        total = sum(len(str(block.get("content", ""))) for block in tool_results)

    return messages


# ═══════════════════════════════════════════════════════════
#  s08: C4 大模型总结摘要压缩历史对话
# ═══════════════════════════════════════════════════════════
# L4: autoCompact — LLM full summary
def _persist_messages(messages: list[dict]) -> Path:
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = MESSAGES_DIR / f"message_{int(time.time())}.jsonl"  # 每条消息转换成一行 JSON，最后得到 JSONL 文件
    """
        JSONL 和普通 JSON 数组不同。它的特点是“一行一个 JSON 对象”，适合：
        逐条追加或读取；保存大量日志；某一条损坏时，不一定影响全部记录。
    """
    with path.open("w") as f:
        for msg in messages:  # 按行写入消息
            f.write(json.dumps(msg, default=str) + "\n")
    return path


# 让 LLM 总结历史
def _summarize_history(messages: list[dict]):

    # 原版写法截断方向可能不合理，改成首尾拼接
    conversation = serialized = json.dumps(messages, default=str, ensure_ascii=False)
    if len(serialized) > 80000:
        conversation = serialized[:30000] + "\n...[truncated]...\n" + serialized[-50000:]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve: 1. current goal, 2. key findings/decisions, 3. files read/changed, "
        "4. remaining work, 5. user constraints.\nBe compact but concrete.\n\n" + conversation
    )
    response = client.messages.create(model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=6000)
    return "\n".join(block.text for block in response.content if isinstance(block, TextBlock)).strip() or "(empty summary)"


# C4 entry point
def c4_compact_history(messages: list[dict]):
    message_path = _persist_messages(messages)
    print(f"[message saved: {message_path}]")
    summary = _summarize_history(messages)
    return [{"role": "user", "content": f"[Compacted] Conversation history has been summarized. \n\n{summary}"}]


# Emergency: reactiveCompact — on API error
def reactive_compact(messages: list[dict]):
    _persist_messages(messages)
    tail_start = max(0, len(messages) - 5)
    if (
        tail_start > 0
        and tail_start < len(messages)
        and _message_has_tool_result(messages[tail_start])
        and _message_has_tool_use(messages[tail_start - 1])
    ):
        tail_start -= 1
    summary = _summarize_history(messages[:tail_start])
    return [
        {"role": "user", "content": f"[Reactive compact]\n\n{summary}"},
        *messages[tail_start:],
    ]
