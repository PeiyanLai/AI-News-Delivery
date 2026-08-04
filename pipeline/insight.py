"""摘要、分级与洞察：调用 LLM 完成事件摘要和每日分析，并把结果写回事件。"""
from __future__ import annotations

import logging

from .llm import BaseLLM
from .models import Event

log = logging.getLogger(__name__)

VALID_TIERS = {"must_read", "worth_reading", "skim"}


def summarize_events(events: list[Event], llm: BaseLLM) -> None:
    for e in events:
        try:
            out = llm.summarize_event(e.articles)
            e.title = out["title"] or e.articles[0].title
            e.summary = out["summary"]
        except Exception as exc:
            log.warning("event %s 摘要失败: %s", e.id, exc)
            e.title = e.articles[0].title
            e.summary = e.articles[0].text[:150]


def analyze_day(events: list[Event], llm: BaseLLM, recent_digest: str,
                focus_areas: list[str], max_cards: int) -> tuple[str, str]:
    """写回 tier/insight，返回 (briefing, highlights)。"""
    if not events:
        return "今日各源均无新内容。", ""
    try:
        out = llm.daily_analysis(events, recent_digest, focus_areas, max_cards)
    except Exception as exc:
        log.error("每日分析失败，保留默认分级: %s", exc)
        return "（今日分析生成失败，以下为未分级事件列表）", ""

    by_id = {e.id: e for e in events}
    cards = 0
    for item in out.get("events", []):
        e = by_id.get(item.get("id"))
        if e is None:
            continue
        tier = item.get("tier")
        if tier in VALID_TIERS:
            e.tier = tier
        insight = item.get("insight")
        if e.tier == "must_read" and insight and cards < max_cards:
            e.insight = str(insight)
            cards += 1
    return str(out.get("briefing", "")), str(out.get("highlights", ""))
