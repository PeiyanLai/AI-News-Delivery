"""每日邮件简报：当日精简版（导读 + 看点 + 必读事件），经 Resend 发送。

未配置 RESEND_API_KEY 或 email.enabled=false 时静默跳过（记日志）。
"""
from __future__ import annotations

import logging
import os

import markdown
import requests

from .models import DailyReport

log = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


def build_email_html(report: DailyReport, site_url: str) -> str:
    must_reads = [e for e in report.events if e.tier == "must_read"]
    parts = [
        f'<div style="font-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
        f'max-width:640px;margin:0 auto;color:#1a1a1a;line-height:1.7">',
        f'<h1 style="font-size:20px">AI 每日简报 · {report.date}</h1>',
    ]
    if report.failed_sources:
        names = "、".join(f["name"] for f in report.failed_sources)
        parts.append(f'<p style="color:#b5432a;font-size:13px">⚠ 今日 {names} 抓取失败，信息可能不完整</p>')
    if report.briefing:
        parts.append(f'<p><strong style="color:#b5432a">今日导读</strong><br>{report.briefing}</p>')
    if report.highlights:
        parts.append(f'<p><strong style="color:#b5432a">今日看点</strong><br>{report.highlights}</p>')

    for e in must_reads:
        link = e.articles[0].url if e.articles else "#"
        parts.append(
            f'<div style="border-left:3px solid #b5432a;padding:2px 14px;margin:18px 0">'
            f'<p style="margin:4px 0"><strong>{e.title}</strong></p>'
            f'<p style="margin:4px 0;font-size:14px">{e.summary}</p>'
            + (f'<div style="font-size:13px;color:#444">{markdown.markdown(e.insight)}</div>' if e.insight else "")
            + f'<p style="margin:4px 0;font-size:13px"><a href="{link}">阅读原文 →</a></p></div>'
        )

    other = sum(1 for e in report.events if e.tier != "must_read")
    if site_url:
        parts.append(f'<p style="font-size:14px">另有 {other} 条动态，'
                     f'<a href="{site_url}">在 Dashboard 查看全部 →</a></p>')
    parts.append('<p style="color:#999;font-size:12px">由 AI-News-Delivery 自动生成 · 摘要与洞察由 LLM 生成，请核对原文</p></div>')
    return "\n".join(parts)


def send_daily_email(report: DailyReport, settings: dict) -> bool:
    cfg = settings.get("email", {})
    if not cfg.get("enabled"):
        log.info("邮件未启用，跳过")
        return False
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        log.info("未配置 RESEND_API_KEY，跳过邮件发送")
        return False

    must = sum(1 for e in report.events if e.tier == "must_read")
    subject = f"AI 每日简报 {report.date}：{len(report.events)} 个事件，{must} 条必读"
    resp = requests.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": cfg["from"],
            "to": [cfg["to"]],
            "subject": subject,
            "html": build_email_html(report, settings["site"].get("base_url", "")),
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        log.error("邮件发送失败 %s: %s", resp.status_code, resp.text[:300])
        return False
    log.info("邮件已发送至 %s", cfg["to"])
    return True
