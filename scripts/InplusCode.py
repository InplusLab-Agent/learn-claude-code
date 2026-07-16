import os
from anthropic import Anthropic
from dotenv import load_dotenv

try:
    import readline

    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

load_dotenv(override=True)  # 读取 .env 文件，把里面的变量加载进系统环境变量。


from utils.shell import get_prompt, build_agent_prompt
from utils.load_config import cwd
from utils.tools import *
from utils.hooks import trigger_hooks
from rich import print

client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
model = os.getenv("MODEL_ID")
prompt = get_prompt(cwd)  # deprecated
prompt = build_agent_prompt(cwd)


rounds_since_todo = 0


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    global rounds_since_todo
    while True:
        # s05: nag reminder — inject if model hasn't updated todos for 3 rounds
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"}) # fmt: skip
            rounds_since_todo = 0

        response = client.messages.create(
            model=model,
            system=prompt,
            messages=messages,
            tools=TOOLS,
            max_tokens=15000,
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # If the model calls a tool, execute it and feed results back, then continue the loop
        if response.stop_reason == "tool_use":

            rounds_since_todo += 1
            results = []

            # Execute each tool call, collect results
            for block in response.content:

                if block.type == "thinking":
                    trigger_hooks("OnThinking", block)

                elif block.type == "text":
                    print(f"[blue]{block.text}[/blue]\n")

                elif block.type == "tool_use":

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
                    try:
                        output = handler(**block.input) if handler else f"Unknown: {block.name}" # fmt: skip
                    except TypeError as e:
                        output = f"Error: {e}"
                    # **dict 将字典展开为关键字参数传递给 handler 函数，例如handler(path="main.py", limit=50)

                    trigger_hooks("PostToolUse", block, output)  # s04: post hook

                    # s05: reset nag counter when todo_write is called
                    if block.name == "todo_write":
                        rounds_since_todo = 0

                    # output = run_shell(block.input["command"], cwd)
                    # print(output[:200])
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )

            # Feed tool results back, loop continues
            messages.append({"role": "user", "content": results})
        else:
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
        # Print the model's final text response
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(f"\n{block.text}")
        print()
