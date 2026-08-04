"""静态站生成：把 data/ 下的全部日报渲染为 docs/ 下的 Dashboard。"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import archive
from .config import SITE_DIR
from .models import DailyReport, normalize_insight_md

TEMPLATE_DIR = Path(__file__).parent / "templates"
TIER_NAMES = {"must_read": "必读", "worth_reading": "值得看", "skim": "可略过"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )


def _day_context(report: DailyReport, days: list[str], site_title: str, path_prefix: str) -> dict:
    idx = days.index(report.date) if report.date in days else -1
    grouped = [
        (tier, [e for e in report.events if e.tier == tier])
        for tier in ("must_read", "worth_reading", "skim")
    ]
    for _, evs in grouped:
        for e in evs:
            e.insight_html = Markup(markdown.markdown(normalize_insight_md(e.insight))) if e.insight else None
    return {
        "report": report,
        "grouped": grouped,
        "tier_names": TIER_NAMES,
        "weekday": WEEKDAYS[date.fromisoformat(report.date).weekday()],
        "prev_day": days[idx - 1] if idx > 0 else None,
        "next_day": days[idx + 1] if 0 <= idx < len(days) - 1 else None,
        "site_title": site_title,
        "page_title": report.date,
        "path_prefix": path_prefix,
    }


def render_site(settings: dict) -> None:
    site_title = settings["site"]["title"]
    env = _env()
    day_tpl = env.get_template("day.html")
    archive_tpl = env.get_template("archive.html")

    SITE_DIR.mkdir(exist_ok=True)
    (SITE_DIR / "days").mkdir(exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "style.css", SITE_DIR / "style.css")
    (SITE_DIR / ".nojekyll").touch()

    days = archive.list_days()
    reports = [r for d in days if (r := archive.load_report(d))]

    # 清理 data/ 中已不存在的日期页面，避免残留过期文件
    for stale in (SITE_DIR / "days").glob("????-??-??.html"):
        if stale.stem not in days:
            stale.unlink()

    for report in reports:
        html = day_tpl.render(**_day_context(report, days, site_title, "../"))
        (SITE_DIR / "days" / f"{report.date}.html").write_text(html, encoding="utf-8")

    # index = 最新一天
    if reports:
        latest = reports[-1]
        html = day_tpl.render(**_day_context(latest, days, site_title, ""))
    else:
        html = archive_tpl.render(days=[], site_title=site_title,
                                  page_title="暂无数据", path_prefix="")
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")

    day_meta = [
        {"date": r.date, "events": len(r.events),
         "must_read": sum(1 for e in r.events if e.tier == "must_read")}
        for r in reversed(reports)
    ]
    html = archive_tpl.render(days=day_meta, site_title=site_title,
                              page_title="历史归档", path_prefix="")
    (SITE_DIR / "archive.html").write_text(html, encoding="utf-8")
