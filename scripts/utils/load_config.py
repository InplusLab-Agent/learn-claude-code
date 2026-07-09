from pathlib import Path
import yaml, os


def load_config(path="scripts/config.yaml") -> dict:
    if not Path(path).exists():
        print(f"Warning: Config file '{path}' not found. Using default config.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


cwd = Path(load_config().get("paths", {}).get("workspace", os.getcwd()))
