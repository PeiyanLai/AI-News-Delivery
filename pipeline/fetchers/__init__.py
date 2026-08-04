"""抓取层：每个源是一个独立适配器，单源失败不影响整体。"""
from __future__ import annotations

import logging

from ..models import Article
from . import rss, hackernews, html_list

log = logging.getLogger(__name__)

ADAPTERS = {
    "rss": rss.fetch,
    "hackernews": hackernews.fetch,
    "html_list": html_list.fetch,
}


def fetch_all(sources: list[dict], lookback_hours: int) -> tuple[list[Article], list[dict], list[str]]:
    """返回 (articles, failed_sources, empty_sources)。"""
    articles: list[Article] = []
    failed: list[dict] = []
    empty: list[str] = []
    for src in sources:
        adapter = ADAPTERS.get(src["type"])
        if adapter is None:
            failed.append({"id": src["id"], "name": src["name"], "error": f"未知类型 {src['type']}"})
            continue
        try:
            items = adapter(src, lookback_hours)
        except Exception as exc:  # 单源失败：记录并继续
            log.warning("source %s failed: %s", src["id"], exc)
            failed.append({"id": src["id"], "name": src["name"], "error": str(exc)[:200]})
            continue
        if not items:
            empty.append(src["name"])
        articles.extend(items)
        log.info("source %s: %d articles", src["id"], len(items))
    return articles, failed, empty
