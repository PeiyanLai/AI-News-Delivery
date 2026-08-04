"""Hacker News 适配器：Algolia API，按 AI 关键词 + 分数过滤。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Article
from .util import http_get

API = "https://hn.algolia.com/api/v1/search_by_date"


def fetch(src: dict, lookback_hours: int) -> list[Article]:
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    min_points = src.get("min_points", 20)
    keywords = [k.lower() for k in src.get("keywords", [])]

    seen: dict[str, Article] = {}
    # 拉最近窗口内的高分 story，再按关键词过滤（比逐关键词查询省请求且不易漏）
    for page in range(3):
        resp = http_get(
            f"{API}?tags=story&hitsPerPage=100&page={page}"
            f"&numericFilters=created_at_i>{cutoff},points>={min_points}"
        )
        hits = resp.json().get("hits", [])
        for h in hits:
            title = (h.get("title") or "").strip()
            if not title:
                continue
            haystack = (title + " " + (h.get("url") or "")).lower()
            if keywords and not any(k in haystack for k in keywords):
                continue
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            if url in seen:
                continue
            dt = datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc)
            seen[url] = Article(
                source_id=src["id"], source_name=src["name"],
                category=src.get("category", ""), title=title, url=url,
                published_at=dt.isoformat(),
                text=f"{title}（HN {h.get('points', 0)} points，讨论: "
                     f"https://news.ycombinator.com/item?id={h['objectID']}）",
            )
        if len(hits) < 100:
            break
    return list(seen.values())
