"""
Streaming response wrapper for Anthropic client.

Design contract:
  - create_message(**kwargs) is a drop-in for client.messages.create(**kwargs)
  - Streams the response live and fires the hook events below for real-time display,
    then returns the same anthropic.types.Message object.

config.yaml keys consumed:
  streaming.show_thinking  bool   (default: true)
  streaming.show_text      bool   (default: true)
"""

from anthropic.types import Message
from anthropic.lib.streaming import ParsedMessageStreamEvent

from utils.system import client, load_config
import sys

_ANSI_THINKING = "\033[90m"  # dim grey  for thinking text
_ANSI_TEXT = "\033[34m"  # blue      for assistant reply text
_ANSI_RESET = "\033[0m"


# client.messages.create() 的透明替换
def create_message(**kwargs) -> Message:
    cfg = load_config().get("streaming", {})
    show_thinking = cfg.get("show_thinking", True)
    show_text = cfg.get("show_text", True)

    block_type: str | None = None  # 当前 content block 的类型
    stream_started: bool = False  # 是否已打印过思考块头部（用于懒打印 + 空块过滤）

    def _dispatch(event: ParsedMessageStreamEvent) -> None:
        nonlocal block_type, stream_started

        event_type = event.type

        if event_type == "content_block_start":
            block_type = event.content_block.type  # 每个块开始时设置块类型
            stream_started = False  # 每个块开始时重置

        elif event_type == "content_block_delta":
            event_delta, chunk = event.delta, ""
            if event_delta is None: return # fmt: skip

            if show_thinking and event_delta.type == "thinking_delta":
                if not stream_started:  # 懒打印：仅在首个 chunk 前输出头部
                    sys.stdout.write(f"\n{_ANSI_THINKING}▷ Thinking: ")
                    stream_started = True
                chunk = event_delta.thinking

            elif show_text and event_delta.type == "text_delta":
                if not stream_started:  # 懒打印：仅在首个 chunk 前输出头部
                    sys.stdout.write(f"\n{_ANSI_TEXT}")
                    stream_started = True
                chunk = event_delta.text

            sys.stdout.write(chunk)
            sys.stdout.flush()

        elif event_type == "content_block_stop":
            if stream_started and ((block_type == "thinking" and show_thinking) or (block_type == "text" and show_text)):
                # stream_started=False 时（空块）静默跳过，不输出任何内容
                sys.stdout.write(f"{_ANSI_RESET}\n")
                sys.stdout.flush()
            block_type = None

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            _dispatch(event)
        return stream.get_final_message()
