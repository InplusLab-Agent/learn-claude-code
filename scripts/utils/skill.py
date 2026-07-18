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
        """
        Parse YAML frontmatter from SKILL.md. Returns (meta, body).
        Frontmatter是一种在文本文件（如.md）开头用 ---分隔的元数据块。通常用YAML 格式书写。
        在 SKILL.md 里，前面用 --- 包裹的部分就是 frontmatter，包含技能的元信息，如 name 和 description。
        """
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2) # parts 大概是 ["", 'name: skill_name description: skill_description', 'body'] # fmt: skip
        if len(parts) < 3:
            return {}, text
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            meta = {}
        # meta 是 {name: str, description: str} 形式的字典, parts[2].strip() 把正文strip是去掉首尾空白
        return meta, parts[2].strip()

    # Scan skills/ dir, populate SKILL_REGISTRY with name/description/content.
    def scan_skills(self):

        self.skill_registry.clear()  # 在扫描开始时清空旧状态

        if not self.skills_dir.exists():
            return
        for d in sorted(
            self.skills_dir.iterdir()
        ):  # iterdir() 列出 skills/ 目录下的所有子目录
            if not d.is_dir():
                continue
            manifest = d / "SKILL.md"
            if manifest.exists():
                # raw = manifest.read_text()
                raw = manifest.read_text(encoding="utf-8")
                # meta, body = self._parse_frontmatter(raw)
                meta, _ = self._parse_frontmatter(raw)
                name = meta.get("name", d.name)
                desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
                # 果找不到，就使用一个备用策略：取 SKILL.md 文件的第一行，去掉行首的 # 和两边的空格，作为描述。

                self.skill_registry[name] = {
                    "name": name,
                    "description": desc,
                    "content": raw,  # 包含了不仅name和description，还有比如version等的全部正文内容
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
