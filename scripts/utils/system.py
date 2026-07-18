import os, yaml
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

from utils.shell import SHELL
from utils.skill import SkillRegistry

load_dotenv(override=True)  # 读取 .env 文件，把里面的变量加载进系统环境变量。


def load_config(path="scripts/config.yaml") -> dict:
    if not Path(path).exists():
        print(f"Warning: Config file '{path}' not found. Using default config.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


WORKDIR = Path(load_config().get("paths", {}).get("workspace", os.getcwd()))


TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

MODEL = os.getenv("MODEL_ID")

client = Anthropic(
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
    auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN"),
)
skill_registry = SkillRegistry(WORKDIR)
skill_registry.scan_skills()


# SYSTEM = (
#     f"You are a coding agent at {WORKDIR}. "
#     "For complex sub-problems, use the task tool to spawn a subagent."
# )

# SUB_SYSTEM = (
#     f"You are a coding agent at {WORKDIR}. "
#     "Complete the task you were given, then return a concise summary. "
#     "Do not delegate further."
# )


# deprecated: since 2026-07-17
# SYSTEM_legacy = (
#     f"You are a coding agent at {WORKDIR}. "
#     f"The bash tool executes commands with {SHELL};"
#     "For multi-step task, use todo_write to plan your steps. "
#     "Update todo status as you work;"
#     "For complex sub-problems, use the task tool to spawn a subagent."
# )

_catalog = skill_registry.list_skills()

# s07: Build SYSTEM prompt with skill catalog injected at startup.
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    f"The bash tool executes commands with {SHELL}."
    "For multi-step task, use todo_write to plan your steps. "
    "Update todo status as you work. "
    "For complex sub-problems, use the task tool to spawn a subagent. "
    f"Skills available:\n{_catalog}\n"
    "Use load_skill to get full details when needed. "
)

# s06: subagent gets its own system prompt — no task, no recursion
SUB_SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    f"The bash tool executes commands with {SHELL};"
    "Use tools to complete the assigned task, then return a concise summary. "
    "Do not delegate further."
)
