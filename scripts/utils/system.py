import os
from dotenv import load_dotenv
from utils.shell import SHELL
from anthropic import Anthropic

load_dotenv(override=True)  # 读取 .env 文件，把里面的变量加载进系统环境变量。

client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
model = os.getenv("MODEL_ID")

# SYSTEM = (
#     f"You are a coding agent at {WORKDIR}. "
#     "For complex sub-problems, use the task tool to spawn a subagent."
# )

# SUB_SYSTEM = (
#     f"You are a coding agent at {WORKDIR}. "
#     "Complete the task you were given, then return a concise summary. "
#     "Do not delegate further."
# )

from pathlib import Path
import yaml, os

def load_config(path="scripts/config.yaml") -> dict:
    if not Path(path).exists():
        print(f"Warning: Config file '{path}' not found. Using default config.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
cwd = Path(load_config().get("paths", {}).get("workspace", os.getcwd()))

SYSTEM = (
    f"You are a coding agent at {cwd}. "
    f"The bash tool executes commands with {SHELL};"
    "For multi-step task, use todo_write to plan your steps. "
    "Update todo status as you work;"
    "For complex sub-problems, use the task tool to spawn a subagent."
)

# s06: subagent gets its own system prompt — no task, no recursion
SUB_SYSTEM = (
    f"You are a coding agent at {cwd}. "
    f"The bash tool executes commands with {SHELL};"
    "Use tools to complete the assigned task, then return a concise summary. "
    "Do not delegate further."
)



