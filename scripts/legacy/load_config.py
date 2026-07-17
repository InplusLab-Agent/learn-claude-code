"""
DEPRECATED MODULE.

This module implements load_config function, which has been moved into system.py

Use:
    utils.system

instead.

Deprecated since:
    2026-07-16

"""

from pathlib import Path
import yaml
from typing_extensions import deprecated


@deprecated("[已弃用] 在s06及以后 config 由 system 加载 (since 2026-07-16)")
def load_config(path="scripts/config.yaml") -> dict:
    if not Path(path).exists():
        print(f"Warning: Config file '{path}' not found. Using default config.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# @deprecated("[已弃用] 在s06及以后 cwd 由 system 加载 (since 2026-07-16)")
# cwd = Path(load_config().get("paths", {}).get("workspace", os.getcwd()))
