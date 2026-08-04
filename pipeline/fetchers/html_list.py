"""通用网页列表适配器：用 CSS 选择器从列表页提取标题+链接，用于无 RSS 的站点。

页面上通常拿不到发布时间，条目不带日期，依赖 seen-url 记录做增量。
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Article
from .util import http_get

MAX_ITEMS = 15
MIN_TITLE_LEN = 8


def fetch(src: dict, lookback_hours: int) -> list[Article]:
    resp = http_get(src["url"])
    soup = BeautifulSoup(resp.text, "html.parser")
    base = src.get("base_url", src["url"])

    articles, seen_urls = [], set()
    for node in soup.select(src["item_selector"]):
        href = node.get("href")
        title = " ".join(node.get_text(" ").split())
        if not href or len(title) < MIN_TITLE_LEN:
            continue
        url = urljoin(base, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        articles.append(Article(
            source_id=src["id"], source_name=src["name"],
            category=src.get("category", ""), title=title, url=url,
            published_at="", text=title,
        ))
        if len(articles) >= MAX_ITEMS:
            break
    return articles
