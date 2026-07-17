from pathlib import Path
import ast
import json
from utils.shell import run_shell

# from scripts.legacy.load_config import cwd
from rich import print
from utils.hooks import trigger_hooks
from utils.system import SUB_SYSTEM, client, MODEL, cwd

r"""
    \033[33m  黄色 yellow
    \033[36m  青色 cyan
    \033[32m  绿色 green
    \033[0m   重置样式 reset
    """
"""
  +---------+      +-------+      +------------------+
  |  User   | ---> |  LLM  | ---> | TOOL_HANDLERS    |
  | prompt  |      |       |      |  bash            |
  +---------+      +---+---+      |  read_file       |
                        ^         |  write_file      |
                        | result  |  edit_file       |
                        +---------+  glob            |
                                      todo_write ← NEW
                                   +------------------+
                                        |
                         in-memory current_todos
                                        |
                        if rounds_since_todo >= 3:
                          inject <reminder>
"""

CURRENT_TODOS: list[dict] = []


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


def run_read(path: str, limit: int | None = None, start_line: int = 1) -> str:
    try:
        try:
            text = safe_path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = safe_path(path).read_text(encoding="gbk", errors="replace")
        lines = text.splitlines()
        # lines = safe_path(path).read_text().splitlines()
        lines = lines[start_line - 1 :]  # 新增起始行号
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # file_path.write_text(content)
        file_path.write_text(content, encoding="utf-8")
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
        # file_path.write_text(text.replace(old_text, new_text, 1))
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# 使用python glob库支持【通配符搜索】功能；
# 例如 *.py ---> 查找所有Python脚本并将结果结果返回；
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
#  NEW in s05: todo_write tool — plan only, no execution
# ═══════════════════════════════════════════════════════════


# 单下划线 _ 开头的函数表示“私有”、“内部使用”，也不会被另一个文件的import导入。
def _normalize_todos(todos):

    # 初步标准化解析 todos 的格式
    if isinstance(todos, str):
        # todos 是字符串时，尝试将其解析为 JSON 或 Python 字面量列表
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                # ast.literal_eval() 把字符串按照Python字面量语义解析为对象，例如"[{'content': '写代码', 'status': 'pending'}]"
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"

    # 检查转换后的 todos
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None


def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error:
        return error

    CURRENT_TODOS = todos
    lines = ["\n[yellow]## Current Tasks[/yellow]"]
    for t in CURRENT_TODOS:
        icon = {
            "pending": " ",
            "in_progress": "[cyan]▸[/cyan]",
            "completed": "[green]✓[/green]",
        }[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"


# ═══════════════════════════════════════════════════════════
#  NEW in s06: Subagent — fresh messages[], summary only
# ═══════════════════════════════════════════════════════════
def _extract_text(content) -> str:
    """Extract text from message content blocks."""
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text"
    )


# —— s06: Spawn a subagent with fresh messages[], return summary only. ————————————
def spawn_subagent(description: str) -> str:

    print("\n[magenta][Subagent spawned][/magenta]")

    messages = [{"role": "user", "content": description}]  # fresh context

    for _ in range(30):  # safety limit 限制 subagent 的最大推理请求次数不超过30
        response = client.messages.create(
            model=MODEL,
            system=SUB_SYSTEM,
            messages=messages,
            tools=SUB_TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        results = []
        if response.stop_reason == "tool_use":
            for block in response.content:

                if block.type == "thinking":
                    trigger_hooks("OnThinking", block)

                elif block.type == "text":
                    print(f"[blue]{block.text}[/blue]\n")

                elif block.type == "tool_use":
                    # Issue 1: subagent also runs hooks (permissions apply)
                    blocked = trigger_hooks("PreToolUse", block)
                    if blocked:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(blocked),
                            }
                        )
                        continue

                    # ── Tool execution ────────────────────────────────────────
                    handler = SUB_HANDLERS.get(block.name)

                    try:  # 拦截异常
                        output = handler(**block.input) if handler else f"Unknown: {block.name}" # fmt: skip
                        # **dict 将字典展开为关键字参数传递给 handler 函数，例如handler(path="main.py", limit=50)
                    except TypeError as e:
                        output = f"Error: {e}"

                    trigger_hooks("PostToolUse", block, output)  # s04: post hook
                    # print(f"  [bright_black][sub] {block.name}: {str(output)[:100]}[/bright_black]") # fmt: skip

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
            # 结束 subagent 的 Loop
            break

    # Issue 5: fallback if safety limit hit during tool_use
    """
        情况A（正常结束）：最后是 assistant 的文字回复
        [..., assistant: "任务完成，结果是XXX"]

        情况B（被30轮中断）：最后是 user 的 tool_results
        [..., assistant: <tool_use>, user: [tool_result, tool_result, ...]]
    """
    result = _extract_text(messages[-1]["content"])
    if not result:
        # last message is tool_result, look backwards for assistant text
        for msg in reversed(messages):
            if msg["role"] == "assistant": # 找到最近一条 assistant 的消息，提取它说过的文字作为结果。# fmt:skip
                result = _extract_text(msg["content"])
                if result:
                    break
        if not result: #最极端的情况——30 轮内 assistant 从来没说过一句纯文字（全是 tool_use 块），就返回这个降级提示。 # fmt: skip
            result = "Subagent stopped after 30 turns without final answer."
    print("[magenta][Subagent done][/magenta]")
    return result  # only summary, entire message history discarded


# ═══════════════════════════════════════════════════════════
#  NEW in s02: 工具分发映射（s01 是硬编码 run_bash，现在改为查表）
# ═══════════════════════════════════════════════════════════
SUB_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
}


TOOL_HANDLERS = {
    **SUB_HANDLERS,
    "todo_write": run_todo_write,
    "task": spawn_subagent,
}


SUB_TOOLS = [
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
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based line number to start reading from. Defaults to 1.",
                },
            },
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


# ── Tool definition: 运行命令行────────────────────────────
TOOLS = [
    *SUB_TOOLS,  # 对一个字面量进行进行可迭代对象解包，适配到目标类型里。
    # s05: new tool
    {
        "name": "todo_write",
        # todos[('Read the README.md file',  'completed'), ( "List all files in the current directory", 'pending')]
        "description": "Create and manage a task list for your current coding session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                        },
                        "required": ["content", "status"],
                    },
                }
            },
            "required": ["todos"],
        },
    },
    # s06: new task tool to dispatch subagent
    {
        "name": "task",
        "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
        "input_schema": {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    },
]
