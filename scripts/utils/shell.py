import os  # 通过python的os模块，可以判断当前操作系统。
import shutil
import subprocess


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
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except (FileNotFoundError, OSError) as error:
        return f"Error: {error}"
