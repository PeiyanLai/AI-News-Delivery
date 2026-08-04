"""流水线入口。

用法：
  python -m pipeline.main run                # 正式运行（需 OPENAI_API_KEY）
  python -m pipeline.main run --mock         # mock LLM，本地验证
  python -m pipeline.main run --fixtures pipeline/fixtures/sample_articles.json --mock
  python -m pipeline.main render             # 仅从 data/ 重建静态站
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import archive
from .cluster import cluster_articles
from .config import load_settings, load_sources
from .email_send import send_daily_email
from .fetchers import fetch_all
from .insight import analyze_day, summarize_events
from .llm import make_llm
from .models import Article, DailyReport
from .render import render_site

log = logging.getLogger("pipeline")


def load_fixtures(path: str) -> list[Article]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Article(**{k: a[k] for k in
                       ("source_id", "source_name", "category", "title", "url", "published_at", "text")})
            for a in raw]


def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    tz = ZoneInfo(settings.get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    today = args.date or now.date().isoformat()

    # 1. 抓取
    if args.fixtures:
        articles, failed, empty = load_fixtures(args.fixtures), [], []
        log.info("fixtures: %d articles", len(articles))
    else:
        sources = load_sources()
        articles, failed, empty = fetch_all(sources, settings["fetch"]["lookback_hours"])
    fetched_count = len(articles)

    # 2. 跨天去重（fixtures 演示模式不读写 seen 记录）
    seen = {} if args.fixtures else archive.load_seen()
    articles = [a for a in articles if a.url not in seen]
    max_n = settings["llm"]["max_articles_per_run"]
    articles.sort(key=lambda a: a.published_at, reverse=True)
    if len(articles) > max_n:
        log.warning("文章数 %d 超上限，截取最新 %d 篇", len(articles), max_n)
        articles = articles[:max_n]

    # 3. 聚合 → 摘要 → 分级与洞察
    llm = make_llm(settings, mock=args.mock)
    events = cluster_articles(articles, llm, settings["clustering"]["similarity_threshold"])
    summarize_events(events, llm)
    digest = archive.recent_digest(today, settings["insight"]["trend_context_days"])
    briefing, highlights = analyze_day(
        events, llm, digest, settings.get("focus_areas") or [],
        settings["insight"]["max_cards"],
    )

    report = DailyReport(
        date=today, generated_at=now.isoformat(timespec="seconds"),
        briefing=briefing, highlights=highlights, events=events,
        failed_sources=failed, empty_sources=empty, mock=args.mock,
        stats={
            "articles_fetched": fetched_count,
            "articles_new": len(articles),
            "tokens": llm.usage,
        },
    )
    report.sort_events()

    # 4. 落盘 + 渲染 + 邮件
    path = archive.save_report(report)
    log.info("日报已写入 %s", path)
    if not args.fixtures:
        for a in articles:
            seen[a.url] = today
        archive.save_seen(seen, today)
    render_site(settings)
    log.info("Dashboard 已生成到 docs/")
    if not args.no_email:
        send_daily_email(report, settings)

    must = sum(1 for e in events if e.tier == "must_read")
    print(f"\n完成：{fetched_count} 篇抓取 → {len(articles)} 篇新文章 → {len(events)} 个事件"
          f"（必读 {must}）；失败源 {len(failed)} 个；tokens={llm.usage}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="执行完整流水线")
    p_run.add_argument("--date", help="覆盖运行日期 YYYY-MM-DD（默认按配置时区的今天）")
    p_run.add_argument("--mock", action="store_true", help="用 mock LLM，无需 API key")
    p_run.add_argument("--fixtures", help="从 JSON 文件读文章，跳过网络抓取")
    p_run.add_argument("--no-email", action="store_true", help="跳过邮件发送")

    sub.add_parser("render", help="仅从 data/ 重建静态站")

    args = parser.parse_args()
    if args.cmd == "render":
        render_site(load_settings())
        print("docs/ 已重建")
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
