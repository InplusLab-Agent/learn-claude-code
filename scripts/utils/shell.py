import os # 通过python的os模块，可以判断当前操作系统。
import shutil
import subprocess

# Tuple 在3.9前后的写法不同，3.9之前是 Tuple[str, List[str]]，3.9及以后是 tuple[str, list[str]]。表示返回的类型。注意这里不要用 ()
def get_shell_config() -> tuple[str, list[str]]:
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


# 构造指令执行的提示词，将工作路径、当前工具调用的具体shell_name告诉LLM。
def get_prompt_system(working_dir: str) -> str:
    _shell_name_, _ = get_shell_config()
    return f"You are a coding agent at {working_dir}. Use {_shell_name_} commands to solve tasks. Act, don't explain."

# 优化PowerShell里面的pwd和cd返回字符串并非纯文本的问题（进行指令替换）
def get_normalized_shell_command(command: str, shell_name: str) -> str:
    stripped = command.strip()
    if shell_name == "PowerShell" and stripped in {"pwd", "cd"}:
        return "Get-Location | Select-Object -ExpandProperty Path"
    return command



# 运行指令获取结果。
def get_shell_command_result(command: str, working_dir: str, timeout: int = 120) -> str:
    
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command blocked"

    shell_name, shell_prefix = get_shell_config()
    command = get_normalized_shell_command(command, shell_name)

    try:
        result = subprocess.run(
            [*shell_prefix, command],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except (FileNotFoundError, OSError) as error:
        return f"Error: {error}"
