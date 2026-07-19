import os  # 通过python的os模块，可以判断当前操作系统。
import shutil
import subprocess
from typing_extensions import deprecated


# Tuple 在3.9前后的写法不同，3.9之前是 Tuple[str, List[str]]，3.9及以后是 tuple[str, list[str]]。表示返回的类型。注意这里不要用 ()
def _load_shell_command() -> tuple[str, list[str]]:
    # os.name == "nt" 即为 WinOS，
    if os.name == "nt":
        # NoProfile 不加载用户自己的配置文件，当然也无法使用环境变量。这样的好处是能够提供更干净的环境。
        return "PowerShell", ["powershell.exe", "-NoProfile", "-Command"]
        # 最终执行powershell.exe -NoProfile -Command "command"

    bash_path = shutil.which("bash")
    if bash_path:
        return "bash", [bash_path, "-lc"]

    sh_path = shutil.which("sh") or "/bin/sh"
    return "sh", [sh_path, "-c"]


SHELL, SHELL_PREFIX = _load_shell_command()


# 优化PowerShell里面的pwd和cd返回字符串并非纯文本的问题（进行指令替换）
def _normalized_shell_command(command: str) -> str:
    stripped = command.strip()
    if SHELL == "PowerShell" and stripped in {"pwd", "cd"}:
        return "Get-Location | Select-Object -ExpandProperty Path"
    return command


# 运行指令获取结果。
def run_shell(command: str, cwd: str, timeout: int = 30) -> str:

    # 指令检查已经被hooks替代
    # dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    # if any(item in command for item in dangerous):
    #     return "Error: Dangerous command blocked"

    # shell, shell_prefix = _load_shell_command()
    command = _normalized_shell_command(command)

    try:
        result = subprocess.run(
            [*SHELL_PREFIX, command],
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            # text=True,
            # encoding="utf-8",
        )
        raw = result.stdout + result.stderr
        try:
            output = raw.decode("utf-8")
        except UnicodeDecodeError:
            output = raw.decode("gb18030", errors="replace")

        output = output.strip()
        return output[:50000] if output else "(no output)"
        # output = (result.stdout + result.stderr).strip()
        # return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except (FileNotFoundError, OSError) as error:
        return f"Error: {error}"


# 构造指令执行的提示词，将工作路径、当前工具调用的具体shell_name告诉LLM。
@deprecated("[已弃用] s01 的prompt无法支持后续 s05及以后的 todo-prompt")
def get_prompt(cwd: str) -> str:
    shell, _ = _load_shell_command()
    return f"You are a coding agent at {cwd}. Use {shell} commands to solve tasks. Act, don't explain."


@deprecated("[已弃用] 在s06及其以后改用 prompt.py 下的prompt (since: 2026-07-16)")
def build_agent_prompt(cwd: str) -> str:
    shell, _ = _load_shell_command()
    return (
        f"You are a coding agent at {cwd}. "
        f"The bash tool executes commands with {shell};"
        "Before starting any multi-step task, use todo_write to plan your steps. "
        "Update status as you go."
    )
