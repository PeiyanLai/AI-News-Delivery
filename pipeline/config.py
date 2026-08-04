"""加载 config/ 下的 yaml 配置与 prompt 模板。"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "docs"


def load_settings() -> dict:
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> list[dict]:
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        sources = yaml.safe_load(f)["sources"]
    return [s for s in sources if s.get("enabled", True)]


def load_prompt(name: str) -> str:
    """读取 prompt 模板，去掉文件头部以 # 开头的说明行。"""
    text = (CONFIG_DIR / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") or not line.strip():
            body_start = i + 1
        else:
            break
    return "\n".join(lines[body_start:]).strip()
