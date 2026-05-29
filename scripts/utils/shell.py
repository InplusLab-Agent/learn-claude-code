import os
import shutil
import subprocess


# Get name of cross-platform shell tool.
def get_shell_config():
    if os.name == "nt":
        return "PowerShell", ["powershell.exe", "-NoProfile", "-Command"]

    bash_path = shutil.which("bash")
    if bash_path:
        return "bash", [bash_path, "-lc"]

    sh_path = shutil.which("sh") or "/bin/sh"
    return "sh", [sh_path, "-c"]


# System prompt construction and command execution.
def build_system_prompt(workdir: str) -> str:
    shell_name, _ = get_shell_config()
    return f"You are a coding agent at {workdir}. Use {shell_name} commands to solve tasks. Act, don't explain."


def normalize_shell_command(command: str, shell_name: str) -> str:
    stripped = command.strip()
    if shell_name == "PowerShell" and stripped in {"pwd", "cd"}:
        return "Get-Location | Select-Object -ExpandProperty Path"
    return command


def run_shell_command(command: str, cwd: str, timeout: int = 120) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(item in command for item in dangerous):
        return "Error: Dangerous command blocked"

    shell_name, shell_prefix = get_shell_config()
    command = normalize_shell_command(command, shell_name)

    try:
        result = subprocess.run(
            [*shell_prefix, command],
            cwd=cwd,
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
