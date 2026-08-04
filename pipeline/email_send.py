"""每日邮件简报：当日精简版（导读 + 看点 + 必读事件）。

两种发送方式（settings.yaml 的 email.provider）：
  smtp   —— 普通邮箱 SMTP（QQ/163 等，凭据放 SMTP_USER / SMTP_PASS secrets）
  resend —— Resend API（凭据放 RESEND_API_KEY secret）
缺少对应凭据或 email.enabled=false 时静默跳过（记日志）。
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import markdown
import requests

from .models import DailyReport, normalize_insight_md

log = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


TIER_META = {
    "must_read": ("必读", "#b5432a"),
    "worth_reading": ("值得看", "#8a6d1d"),
    "skim": ("可略过", "#999999"),
}


def _source_links(e) -> str:
    return " · ".join(
        f'<a href="{a.url}" style="color:#6b6b6b">{a.source_name}</a>' for a in e.articles
    )


def _event_block(e, color: str) -> str:
    return (
        f'<div style="border-left:3px solid {color};padding:2px 14px;margin:16px 0">'
        f'<p style="margin:4px 0;font-size:16px"><strong>{e.title}</strong></p>'
        f'<p style="margin:4px 0;font-size:14px">{e.summary}</p>'
        + (f'<div style="font-size:13px;color:#444;background:#fdf0ec;'
           f'border-radius:6px;padding:2px 12px;margin:8px 0">'
           f'{markdown.markdown(normalize_insight_md(e.insight))}</div>' if e.insight else "")
        + f'<p style="margin:4px 0;font-size:12.5px">{_source_links(e)}</p></div>'
    )


def build_email_html(report: DailyReport, site_url: str) -> str:
    """全量邮件：所有事件按分级展示，不需要跳转即可读完当天内容。"""
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

    for tier in ("must_read", "worth_reading"):
        events = [e for e in report.events if e.tier == tier]
        if not events:
            continue
        name, color = TIER_META[tier]
        parts.append(f'<h2 style="font-size:16px;border-bottom:2px solid #1a1a1a;'
                     f'padding-bottom:6px;margin:26px 0 6px">{name}'
                     f'<span style="color:#999;font-size:13px;font-weight:400">（{len(events)}）</span></h2>')
        parts.extend(_event_block(e, color) for e in events)

    # 可略过：紧凑列表，一行一条
    skims = [e for e in report.events if e.tier == "skim"]
    if skims:
        parts.append(f'<h2 style="font-size:16px;border-bottom:2px solid #1a1a1a;'
                     f'padding-bottom:6px;margin:26px 0 6px">可略过'
                     f'<span style="color:#999;font-size:13px;font-weight:400">（{len(skims)}）</span></h2>')
        rows = "".join(
            f'<p style="margin:6px 0;font-size:13px;color:#555">· {e.title}'
            f'　<span style="font-size:12px">{_source_links(e)}</span></p>'
            for e in skims
        )
        parts.append(rows)

    if site_url:
        parts.append(f'<p style="font-size:13px;color:#999;margin-top:24px">'
                     f'<a href="{site_url}" style="color:#999">历史归档 →</a></p>')
    parts.append('<p style="color:#999;font-size:12px">由 AI-News-Delivery 自动生成 · 摘要与洞察由 LLM 生成，请核对原文</p></div>')
    return "\n".join(parts)


def _send_smtp(cfg: dict, subject: str, html: str) -> bool:
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not user or not password:
        log.info("未配置 SMTP_USER/SMTP_PASS，跳过邮件发送")
        return False

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("AI News Delivery", "utf-8")), user))
    msg["To"] = cfg["to"]

    host = cfg.get("smtp_host", "smtp.qq.com")
    port = int(cfg.get("smtp_port", 465))
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    with server:
        server.login(user, password)
        server.sendmail(user, [cfg["to"]], msg.as_string())
    log.info("邮件已通过 SMTP 发送至 %s", cfg["to"])
    return True


def _send_resend(cfg: dict, subject: str, html: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        log.info("未配置 RESEND_API_KEY，跳过邮件发送")
        return False
    resp = requests.post(
        RESEND_API,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": cfg["from"], "to": [cfg["to"]], "subject": subject, "html": html},
        timeout=30,
    )
    if resp.status_code >= 300:
        log.error("邮件发送失败 %s: %s", resp.status_code, resp.text[:300])
        return False
    log.info("邮件已发送至 %s", cfg["to"])
    return True


def send_daily_email(report: DailyReport, settings: dict) -> bool:
    cfg = settings.get("email", {})
    if not cfg.get("enabled"):
        log.info("邮件未启用，跳过")
        return False

    must = sum(1 for e in report.events if e.tier == "must_read")
    subject = f"AI 每日简报 {report.date}：{len(report.events)} 个事件，{must} 条必读"
    html = build_email_html(report, settings["site"].get("base_url", ""))
    try:
        if cfg.get("provider", "smtp") == "smtp":
            return _send_smtp(cfg, subject, html)
        return _send_resend(cfg, subject, html)
    except Exception as exc:
        log.error("邮件发送失败: %s", exc)
        return False
