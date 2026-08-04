"""事件聚合：embedding 相似度贪心聚类，把同一事件的多篇报道归为一组。"""
from __future__ import annotations

import logging

from .llm import BaseLLM
from .models import Article, Event

log = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # 输入均已归一化


def cluster_articles(articles: list[Article], llm: BaseLLM, threshold: float) -> list[Event]:
    if not articles:
        return []
    try:
        vectors = llm.embed([f"{a.title}\n{a.text[:300]}" for a in articles])
    except Exception as exc:
        log.warning("embedding 失败，退化为每篇文章一个事件: %s", exc)
        return [Event.from_articles([a]) for a in articles]

    # OpenAI embedding 已归一化；防御性地再归一化一次
    import math
    normed = []
    for v in vectors:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        normed.append([x / n for x in v])

    clusters: list[dict] = []  # {"articles": [...], "centroid": [...]}
    for art, vec in zip(articles, normed):
        best, best_sim = None, threshold
        for c in clusters:
            sim = _cosine(vec, c["centroid"])
            if sim >= best_sim:
                best, best_sim = c, sim
        if best is None:
            clusters.append({"articles": [art], "vectors": [vec], "centroid": vec})
        else:
            best["articles"].append(art)
            best["vectors"].append(vec)
            dim = len(vec)
            k = len(best["vectors"])
            centroid = [sum(v[i] for v in best["vectors"]) / k for i in range(dim)]
            n = math.sqrt(sum(x * x for x in centroid)) or 1.0
            best["centroid"] = [x / n for x in centroid]

    events = []
    for c in clusters:
        arts = sorted(c["articles"], key=lambda a: a.published_at, reverse=True)
        events.append(Event.from_articles(arts))
    log.info("%d articles -> %d events", len(articles), len(events))
    return events
