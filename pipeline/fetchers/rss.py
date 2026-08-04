"""通用 RSS/Atom 适配器。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import feedparser

from ..models import Article
from .util import http_get, strip_html


def fetch(src: dict, lookback_hours: int) -> list[Article]:
    resp = http_get(src["url"])
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 解析失败: {feed.bozo_exception}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    articles = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue

        published = ""
        ts = entry.get("published_parsed") or entry.get("updated_parsed")
        if ts:
            dt = datetime.fromtimestamp(time.mktime(ts), tz=timezone.utc)
            if dt < cutoff:
                continue
            published = dt.isoformat()
        # 无日期的条目保留，交给 seen-url 记录做跨天去重

        content = ""
        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        content = content or entry.get("summary", "")

        articles.append(Article(
            source_id=src["id"], source_name=src["name"],
            category=src.get("category", ""), title=title, url=link,
            published_at=published, text=strip_html(content),
        ))
    return articles
