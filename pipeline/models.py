"""流水线各阶段共享的数据结构。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict


def normalize_insight_md(text: str) -> str:
    """洞察卡片的 Markdown 容错：模型偶尔会把小节标题挤在一行里，
    渲染前把每个 ### 前强制补换行，保证六个小节都渲染成标题。"""
    return re.sub(r"\s*#{2,4}\s*", "\n\n### ", text).strip()


@dataclass
class Article:
    source_id: str
    source_name: str
    category: str
    title: str
    url: str
    published_at: str  # ISO8601，未知时为 ""
    text: str = ""     # 清洗后的正文/摘要节选

    @property
    def id(self) -> str:
        return "a" + hashlib.sha1(self.url.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


@dataclass
class Event:
    id: str
    articles: list[Article]
    title: str = ""          # LLM 生成的事件标题
    summary: str = ""        # LLM 生成的中文摘要
    tier: str = "worth_reading"  # must_read | worth_reading | skim
    insight: str | None = None   # Markdown 洞察卡片，仅必读事件有

    @classmethod
    def from_articles(cls, articles: list[Article]) -> "Event":
        eid = "e" + hashlib.sha1(articles[0].url.encode()).hexdigest()[:10]
        return cls(id=eid, articles=articles)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "tier": self.tier,
            "insight": self.insight,
            "articles": [a.to_dict() for a in self.articles],
        }


@dataclass
class DailyReport:
    date: str
    generated_at: str
    briefing: str = ""
    highlights: str = ""
    events: list[Event] = field(default_factory=list)
    failed_sources: list[dict] = field(default_factory=list)  # [{id, name, error}]
    empty_sources: list[str] = field(default_factory=list)    # 成功但 0 篇的源名
    stats: dict = field(default_factory=dict)
    mock: bool = False

    TIER_ORDER = {"must_read": 0, "worth_reading": 1, "skim": 2}

    def sort_events(self) -> None:
        self.events.sort(key=lambda e: self.TIER_ORDER.get(e.tier, 1))

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "generated_at": self.generated_at,
            "briefing": self.briefing,
            "highlights": self.highlights,
            "events": [e.to_dict() for e in self.events],
            "failed_sources": self.failed_sources,
            "empty_sources": self.empty_sources,
            "stats": self.stats,
            "mock": self.mock,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DailyReport":
        events = []
        for ed in d.get("events", []):
            arts = [
                Article(
                    source_id=a["source_id"], source_name=a["source_name"],
                    category=a.get("category", ""), title=a["title"], url=a["url"],
                    published_at=a.get("published_at", ""), text=a.get("text", ""),
                )
                for a in ed.get("articles", [])
            ]
            events.append(Event(
                id=ed["id"], articles=arts, title=ed.get("title", ""),
                summary=ed.get("summary", ""), tier=ed.get("tier", "worth_reading"),
                insight=ed.get("insight"),
            ))
        return cls(
            date=d["date"], generated_at=d.get("generated_at", ""),
            briefing=d.get("briefing", ""), highlights=d.get("highlights", ""),
            events=events, failed_sources=d.get("failed_sources", []),
            empty_sources=d.get("empty_sources", []), stats=d.get("stats", {}),
            mock=d.get("mock", False),
        )
