import yaml
from pathlib import Path


class SkillRegistry:
    def __init__(self, cwd: Path):
        self.skills_dir = cwd / "skills"  # Path 重载了 / 运算符
        # Build skill registry at startup (used for safe lookup in load_skill)
        self.skill_registry: dict[str, dict] = {}

    @staticmethod
    # s07: Skill catalog scan (used by build_system below)
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from SKILL.md. Returns (meta, body)."""
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, parts[2].strip()

    def scan_skills(self):

        self.skill_registry.clear()  # 在扫描开始时清空旧状态

        """Scan skills/ dir, populate SKILL_REGISTRY with name/description/content."""
        if not self.skills_dir.exists():
            return
        for d in sorted(self.skills_dir.iterdir()):
            if not d.is_dir():
                continue
            manifest = d / "SKILL.md"
            if manifest.exists():
                # raw = manifest.read_text()
                raw = manifest.read_text(encoding="utf-8")
                meta, body = self._parse_frontmatter(raw)
                name = meta.get("name", d.name)
                desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
                self.skill_registry[name] = {
                    "name": name,
                    "description": desc,
                    "content": raw,
                }

    def list_skills(self) -> str:
        """List all skills (name + one-line description)."""
        if not self.skill_registry:
            return "(no skills found)"
        return "\n".join(
            f"- **{s['name']}**: {s['description']}"
            for s in self.skill_registry.values()
        )

    # ═══════════════════════════════════════════════════════════
    #  NEW in s07: load_skill — runtime full content loading
    # ═══════════════════════════════════════════════════════════

    def load_skill(self, name: str) -> str:
        """Load full skill content. Lookup via registry — no path traversal."""
        skill = self.skill_registry.get(name)
        if not skill:
            return f"Skill not found: {name}"
        return skill["content"]
