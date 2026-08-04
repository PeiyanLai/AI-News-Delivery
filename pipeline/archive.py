"""事件档案：按天存 JSON，供 Dashboard 渲染与「趋势坐标」回看使用。

同时维护 seen-url 记录做跨天去重（抓取窗口有意与运行间隔重叠）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .config import DATA_DIR
from .models import DailyReport

SEEN_FILE = DATA_DIR / "seen_urls.json"
SEEN_RETENTION_DAYS = 30


def _day_file(day: str) -> Path:
    return DATA_DIR / f"{day}.json"


def save_report(report: DailyReport) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    path = _day_file(report.date)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_report(day: str) -> DailyReport | None:
    path = _day_file(day)
    if not path.exists():
        return None
    return DailyReport.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_days() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.stem for p in DATA_DIR.glob("????-??-??.json"))


def recent_digest(today: str, days: int) -> str:
    """最近 N 天（不含今天）的事件档案文本，喂给洞察 prompt 做趋势判断。"""
    lines = []
    for day in list_days():
        if day >= today:
            continue
        if (date.fromisoformat(today) - date.fromisoformat(day)).days > days:
            continue
        report = load_report(day)
        if not report:
            continue
        for e in report.events:
            if e.tier in ("must_read", "worth_reading") and e.title:
                lines.append(f"- [{day}] {e.title}: {e.summary[:80]}")
    return "\n".join(lines[-120:])  # 控制 token


def load_seen() -> dict[str, str]:
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    return {}


def save_seen(seen: dict[str, str], today: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    cutoff = (date.fromisoformat(today) - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    pruned = {url: d for url, d in seen.items() if d >= cutoff}
    SEEN_FILE.write_text(json.dumps(pruned, ensure_ascii=False, indent=0), encoding="utf-8")
