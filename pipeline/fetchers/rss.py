"""通用 RSS/Atom 适配器。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import feedparser

from ..models import Article
from .util import http_get, strip_html


def fetch(src: dict, lookback_hours: int) -> list[Article]:
    # url 可以是字符串或列表（备用端点，依次尝试）
    urls = src["url"] if isinstance(src["url"], list) else [src["url"]]
    feed, last_err = None, None
    for url in urls:
        try:
            resp = http_get(url)
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                raise RuntimeError(f"RSS 解析失败: {parsed.bozo_exception}")
            feed = parsed
            break
        except Exception as exc:
            last_err = exc
    if feed is None:
        raise RuntimeError(str(last_err))

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
