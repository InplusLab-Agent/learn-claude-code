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


# client.message.create() 的透明兼容
def create_message(**kwargs) -> Message:

    streaming_config = load_config().get("streaming", {})

    # # 关闭流式输出时，与原始的 client.messages.create() 行为一致
    # if not streaming_config.get("enabled", False):
    #     return client.messages.create(**kwargs)

    # Optionally inject extended thinking when budget is configured
    # thinking_budget = streaming_config.get("thinking_budget")
    # if thinking_budget and "thinking" not in kwargs:
    #     kwargs = {**kwargs, "thinking": {"type": "enabled", "budget_tokens": int(thinking_budget)}}

    # Local closure tracks the current block type across events
    _state: dict = {"block_type": None}

    def _dispatch(event: ParsedMessageStreamEvent) -> None:
        # event_type = getattr(event, "type", None)
        event_type = event.type

        if event_type == "content_block_start":
            # block_type = getattr(getattr(event, "content_block", None), "type", None)
            block_type = event.content_block.type
            _state["block_type"] = block_type

            if block_type == "thinking":
                if streaming_config.get("show_thinking", True):
                    sys.stdout.write(f"\n{_ANSI_THINKING}▷ Thinking: ")
                    sys.stdout.flush()
            elif block_type == "text":
                if streaming_config.get("show_text", True):
                    sys.stdout.write(f"\n{_ANSI_TEXT}")
                    sys.stdout.flush()

        elif event_type == "content_block_delta":
            delta = event.delta
            # delta = getattr(event, "delta", None)
            if delta is None: return # fmt: skip

            delta_type = delta.type

            if delta_type == "thinking_delta":
                if streaming_config.get("show_thinking", True):
                    sys.stdout.write(delta.thinking)
                    sys.stdout.flush()
            elif delta_type == "text_delta":
                if streaming_config.get("show_text", True):
                    sys.stdout.write(delta.text)
                    sys.stdout.flush()

        elif event_type == "content_block_stop":
            # Reset ANSI colour and print newline when a thinking or text block ends.
            if block_type == "thinking" and streaming_config.get("show_thinking", True):
                sys.stdout.write(f"{_ANSI_RESET}\n")
                sys.stdout.flush()
            elif block_type == "text" and streaming_config.get("show_text", True):
                sys.stdout.write(f"{_ANSI_RESET}\n")
                sys.stdout.flush()
            _state["block_type"] = None

    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            _dispatch(event)
        # Waits until the stream has been read to completion and returns the accumulated `Message` object.
        return stream.get_final_message()
