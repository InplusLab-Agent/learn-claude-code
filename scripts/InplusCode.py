try:
    import readline

    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass


from utils.tools import TOOLS, TOOL_HANDLERS
from utils.hooks import trigger_hooks
from utils.system import SYSTEM, MODEL, load_config
from utils.context_compact import c1_snip_compact, c2_micro_compact, c3_tool_result_budget, c4_compact_history
from utils.context_compact import reactive_compact, estimate_size, COMPACT_CHAR_LIMIT

import utils.stream as stream
from rich import print

rounds_since_todo = 0


MAX_REACTIVE_RETRIES = 1  # retry limit for reactive compact


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    global rounds_since_todo
    reactive_retries = 0
    while True:
        # s05: nag reminder — inject if model hasn't updated todos for 3 rounds
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"}) # fmt: skip
            rounds_since_todo = 0
        # ═══════════════════════════════════════════════════════════
        #  agent_loop — s08 core: run compaction pipeline before LLM
        # ═══════════════════════════════════════════════════════════
        # s08 change: three preprocessors (0 API calls, cheap first)
        # Order matches CC source: budget → snip → micro
        # messages[:] = c3_tool_result_budget(messages)  # L3: persist large results first
        # messages[:] = c1_snip_compact(messages)  # L1: trim middle
        # messages[:] = c2_micro_compact(messages)  # L2: old result placeholders

        # s08 change: tokens still over threshold → LLM summary (1 API call)
        if estimate_size(messages) > COMPACT_CHAR_LIMIT:
            print("[auto compact]")
            messages[:] = c4_compact_history(messages)

        try:
            # response = client.messages.create(model=MODEL,system=SYSTEM,messages=messages,tools=TOOLS,max_tokens=15000,timeout=180,) # fmt: skip
            response = stream.create_message(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=15000, timeout=180)  # fmt: skip
            reactive_retries = 0  # reset on successful API call
        except Exception as e:
            if ("prompt_too_long" in str(e).lower() or "too many tokens" in str(e).lower()) and reactive_retries < MAX_REACTIVE_RETRIES: # fmt: skip
                print("[reactive compact]")
                messages[:] = reactive_compact(messages)
                reactive_retries += 1
                continue
            # TODO: 异常捕获应该放进create_message里面
            raise

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # If the model calls a tool, execute it and feed results back, then continue the loop
        if response.stop_reason == "tool_use":

            rounds_since_todo += 1
            results = []

            # Execute each tool call, collect results
            for block in response.content:

                # if block.type == "thinking":
                #     trigger_hooks("OnThinking", block)

                # elif block.type == "text":
                #     # Skip: streaming already printed this live via OnTextDelta
                #     if not load_config().get("streaming", {}).get("enabled", False):
                #         print(f"[blue]{block.text}[/blue]\n")

                if block.type == "tool_use":

                    # s08: compact tool triggers compact_history, not a no-op string
                    if block.name == "compact":
                        messages[:] = c4_compact_history(messages)
                        # results.append(
                        #     {
                        #         "type": "tool_result",
                        #         "tool_use_id": block.id,
                        #         "content": "[Compacted. Conversation history has been summarized.]",
                        #     }
                        # )
                        # messages.append({"role": "user", "content": results})
                        break  # end current turn, start fresh with compacted context

                    # 是否启用拦截风险
                    # s04 change: hook replaces hard-coded check_permission()
                    blocked = trigger_hooks("PreToolUse", block)
                    if blocked:  # 拦截本次工具调用
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(blocked),
                            }
                        )
                        continue

                    # ── Tool execution ────────────────────────────────────────
                    handler = TOOL_HANDLERS.get(block.name)
                    try:  # 拦截异常

                        output = handler(**block.input) if handler else f"Unknown: {block.name}" # fmt: skip
                        # **dict 将字典展开为关键字参数传递给 handler 函数，例如handler(path="main.py", limit=50)
                    except TypeError as e:
                        output = f"Error: {e}"

                    trigger_hooks("PostToolUse", block, output)  # s04: post hook

                    # s05: reset nag counter when todo_write is called
                    if block.name == "todo_write":
                        rounds_since_todo = 0

                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )
            else:  # 只有没有遇到 compact/break 时才执行
                # Feed tool results back, loop continues
                messages.append({"role": "user", "content": results})
                trigger_hooks("PostResponse", response)

        else:
            # TODO: fix the max_token bugs.
            force = trigger_hooks("Stop", response)  # 当 force为None时，正常结束。
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("Hello, What can I do for you? Type 'q' to quit.\n")

    history = []
    while True:
        try:
            query = input("\033[36m Input >> ")  # \033[36m 青色；\033[0m 重置颜色
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
