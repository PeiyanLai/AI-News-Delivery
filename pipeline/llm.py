"""LLM 调用层：provider 抽象 + mock 实现。

业务代码只依赖 BaseLLM 的三个方法，未来换 provider 或本地模型只改这里。
Mock 模式不依赖任何 API key，用于本地验证全链路和 UI。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re

from .config import load_prompt
from .models import Article, Event

log = logging.getLogger(__name__)


class BaseLLM:
    usage: dict  # {"prompt_tokens": int, "completion_tokens": int}

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def summarize_event(self, articles: list[Article]) -> dict:
        """返回 {"title": ..., "summary": ...}"""
        raise NotImplementedError

    def filter_relevant(self, titles: list[str]) -> list[bool]:
        """逐条判断标题是否与 AI 相关。"""
        raise NotImplementedError

    def daily_analysis(self, events: list[Event], recent_digest: str,
                       focus_areas: list[str], max_cards: int) -> dict:
        """返回 {"briefing": ..., "highlights": ..., "events": [{id, tier, insight}]}"""
        raise NotImplementedError


def _events_as_text(events: list[Event]) -> str:
    blocks = []
    for e in events:
        srcs = ", ".join(sorted({a.source_name for a in e.articles}))
        blocks.append(f"- id: {e.id}\n  标题: {e.title}\n  摘要: {e.summary}\n  来源: {srcs}")
    return "\n".join(blocks)


def _articles_as_text(articles: list[Article]) -> str:
    blocks = []
    for a in articles:
        blocks.append(f"【{a.source_name}】{a.title}\n{a.text[:1200]}")
    return "\n\n".join(blocks)


def _parse_json(raw: str) -> dict:
    """容错解析：剥掉可能的 ```json 围栏。"""
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    return json.loads(raw)


class OpenAILLM(BaseLLM):
    def __init__(self, settings: dict):
        from openai import OpenAI  # 延迟导入，mock 模式不需要该依赖可用

        self.client = OpenAI()  # 读 OPENAI_API_KEY 环境变量
        cfg = settings["llm"]
        self.fast_model = cfg["fast_model"]
        self.smart_model = cfg["smart_model"]
        self.embedding_model = cfg["embedding_model"]
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def _chat_json(self, model: str, prompt: str) -> dict:
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        if resp.usage:
            self.usage["prompt_tokens"] += resp.usage.prompt_tokens
            self.usage["completion_tokens"] += resp.usage.completion_tokens
        return _parse_json(resp.choices[0].message.content or "{}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 100):
            batch = [t[:2000] for t in texts[i:i + 100]]
            resp = self.client.embeddings.create(model=self.embedding_model, input=batch)
            vectors.extend(d.embedding for d in resp.data)
            if resp.usage:
                self.usage["prompt_tokens"] += resp.usage.prompt_tokens
        return vectors

    def summarize_event(self, articles: list[Article]) -> dict:
        prompt = load_prompt("event_summary").replace("{{", "\x00").replace("}}", "\x01") \
            .format(articles=_articles_as_text(articles)) \
            .replace("\x00", "{").replace("\x01", "}")
        out = self._chat_json(self.fast_model, prompt)
        return {"title": str(out.get("title", "")), "summary": str(out.get("summary", ""))}

    def filter_relevant(self, titles: list[str]) -> list[bool]:
        flags: list[bool] = []
        template = load_prompt("relevance_filter")
        for i in range(0, len(titles), 60):
            batch = titles[i:i + 60]
            items = "\n".join(f"{j}. {t}" for j, t in enumerate(batch))
            prompt = template.replace("{{", "\x00").replace("}}", "\x01") \
                .format(items=items).replace("\x00", "{").replace("\x01", "}")
            try:
                out = self._chat_json(self.fast_model, prompt)
                keep = {int(x) for x in out.get("relevant_ids", [])}
            except Exception as exc:
                log.warning("相关性过滤失败，该批全部保留: %s", exc)
                keep = set(range(len(batch)))
            flags.extend(j in keep for j in range(len(batch)))
        return flags

    def daily_analysis(self, events, recent_digest, focus_areas, max_cards):
        prompt = load_prompt("daily_analysis").replace("{{", "\x00").replace("}}", "\x01") \
            .format(
                events=_events_as_text(events),
                recent_digest=recent_digest or "（暂无档案，今天是第一次运行）",
                focus_areas="、".join(focus_areas) if focus_areas else "（未设置）",
                max_cards=max_cards,
            ).replace("\x00", "{").replace("\x01", "}")
        return self._chat_json(self.smart_model, prompt)


class MockLLM(BaseLLM):
    """无 key 时的本地验证实现：确定性输出，覆盖 UI 的全部状态。"""

    DIM = 256

    def __init__(self):
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def embed(self, texts: list[str]) -> list[list[float]]:
        # 词袋哈希向量：token 重合度近似余弦相似度，足以让近似标题聚到一起
        vectors = []
        for text in texts:
            v = [0.0] * self.DIM
            for token in re.findall(r"[\w一-鿿]+", text.lower()):
                idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.DIM
                v[idx] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors

    def summarize_event(self, articles: list[Article]) -> dict:
        first = articles[0]
        return {"title": first.title[:40], "summary": (first.text or first.title)[:150] + "……（mock 摘要）"}

    AI_PATTERN = re.compile(
        r"\b(ai|llm|gpt|claude|gemini|openai|anthropic|deepmind|agent|rag|"
        r"transformer|ml|model|inference)s?\b", re.IGNORECASE)
    AI_CJK = ("模型", "智能体", "大模型", "机器学习", "推理", "多模态")

    def filter_relevant(self, titles: list[str]) -> list[bool]:
        return [bool(self.AI_PATTERN.search(t)) or any(k in t for k in self.AI_CJK)
                for t in titles]

    def daily_analysis(self, events, recent_digest, focus_areas, max_cards):
        card = (
            "### 一句话本质\nmock 模式占位内容：此处为剥离营销话术后的技术/产品变化判断。\n\n"
            "### 为什么令人兴奋\n能力边界/成本量级的变化说明。\n\n"
            "### 产品机会\nPM 视角的新产品或功能形态。\n\n"
            "### 格局影响\n对各阵营与创业公司窗口的影响。\n\n"
            "### 冷静判断\ndemo 还是可上生产的评估。\n\n"
            "### 趋势坐标\n与最近两周事件档案的呼应。"
        )
        out_events = []
        for i, e in enumerate(events):
            tier = "must_read" if i < min(2, max_cards) else ("worth_reading" if i % 3 else "skim")
            out_events.append({"id": e.id, "tier": tier,
                               "insight": card if tier == "must_read" else None})
        return {
            "briefing": "（mock）今日导读占位：真实运行时由强模型总览全天事件。",
            "highlights": "（mock）今日看点占位：真实运行时做跨事件连线分析。",
            "events": out_events,
        }


def make_llm(settings: dict, mock: bool) -> BaseLLM:
    if mock:
        return MockLLM()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("缺少 OPENAI_API_KEY。本地验证请加 --mock，线上请配置 GitHub Secret。")
    return OpenAILLM(settings)
