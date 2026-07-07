import os
from pathlib import Path

try:
    import readline

    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv
from utils.shell import get_prompt, run_shell
from utils.load_config import config
from rich import print

load_dotenv(override=True)  # 读取 .env 文件，把里面的变量加载进系统环境变量。


# cwd = Path.cwd()  # 获取工作区路径
cwd = Path("D:\--UnityProject\RunminG-Lab\learn-claude-code\scripts")
client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
model = os.getenv("MODEL_ID")
prompt = get_prompt(cwd)


# ═══════════════════════════════════════════════════════════
#  NEW in s02: 4 个新工具
# ═══════════════════════════════════════════════════════════
def safe_path(p: str) -> Path:
    path = (cwd / p).resolve()
    if not path.is_relative_to(cwd):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    return run_shell(command, cwd)


def run_read(path: str, limit: int | None = None) -> str:
    try:
        try:
            text = safe_path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = safe_path(path).read_text(encoding="gbk", errors="replace")
        lines = text.splitlines()
        # lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        # text = file_path.read_text()
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="gbk", errors="replace")
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    import glob as g

    try:
        results = []
        for match in g.glob(pattern, root_dir=cwd):
            if (cwd / match).resolve().is_relative_to(cwd):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════
#  NEW in s02: 工具分发映射（s01 是硬编码 run_bash，现在改为查表）
# ═══════════════════════════════════════════════════════════

TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
}


# ── Tool definition: 运行命令行────────────────────────────
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in a file once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "glob",
        "description": "Find files matching a glob pattern.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    },
]


# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=model,
            system=prompt,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        # If the model calls a tool, execute it and feed results back, then continue the loop
        if response.stop_reason == "tool_use":
            results = []

            # Execute each tool call, collect results
            for block in response.content:
                if block.type == "thinking":
                    if config.get("show_thinking", True):  # 是否打印思考过程
                        print(f"[blue]{block.thinking}[/blue]\n")

                elif block.type == "tool_use":
                    if config.get("show_tool_use", True):  # 是否打印工具调用
                        print(
                            f"[green]Tool Use: {block.name}[/green] [yellow]${block.input}[/yellow]\n"
                        )

                    # ── Tool execution ────────────────────────────────────────
                    handler = TOOL_HANDLERS.get(block.name)
                    output = (
                        handler(**block.input) if handler else f"Unknown: {block.name}"
                    )  # **dict 将字典展开为关键字参数传递给 handler 函数，例如handler(path="main.py", limit=50)

                    # output = run_shell(block.input["command"], cwd)
                    print(output[:200])
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
            return


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("Hello, What can I do for you? Type 'q' to quit.\n")

    history = []
    while True:
        try:
            query = input(
                "\033[36m Input >> \033[0m"
            )  # \033[36m 青色；\033[0m 重置颜色
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
