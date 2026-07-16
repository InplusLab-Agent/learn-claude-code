from pathlib import Path
import ast
import json
from utils.shell import run_shell
from utils.load_config import cwd
from rich import print

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


"""
run_todo_write([
    {"content": "读论文", "status": "pending"},
    {"content": "写实验代码", "status": "in_progress"},
    {"content": "提交报告", "status": "completed"},
])
转换为：
## Current Tasks
  [ ] 读论文
  [▸] 写实验代码
  [✓] 提交报告
"""


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
#  NEW in s02: 工具分发映射（s01 是硬编码 run_bash，现在改为查表）
# ═══════════════════════════════════════════════════════════

TOOL_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
    "todo_write": run_todo_write,
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
]
