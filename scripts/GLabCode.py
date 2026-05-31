import os

try:
    import readline
    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv
from utils.shell import get_prompt_system, get_shell_command_result

load_dotenv(override=True)


working_dir = os.getcwd() # 获取工作区路径
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"),
                   auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"))
model = os.environ["MODEL_ID"]
system = get_prompt_system(working_dir) 






# ── Tool definition: 运行命令行────────────────────────────
tools = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]

# ── Tool execution ────────────────────────────────────────
def run_shell(command: str) -> str:
    return get_shell_command_result(command, working_dir)


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=8000,
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        # If the model calls a tool, execute it and feed results back, then continue the loop
        if response.stop_reason == "tool_use":

            results = []
            # Execute each tool call, collect results
            for block in response.content:
                if block.type == "tool_use":
                    print(f"\033[33m$ {block.input['command']}\033[0m")
                    output = run_shell(block.input["command"])
                    print(output[:200])
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

            # Feed tool results back, loop continues
            messages.append({"role": "user", "content": results})


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s01: Agent Loop")
    print("Hello, What can I do for you? Type 'q' to quit.\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
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
                    print(block.text)
        print()
