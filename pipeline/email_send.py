"""每日邮件简报：当日精简版（导读 + 看点 + 必读事件）。

两种发送方式（settings.yaml 的 email.provider）：
  smtp   —— 普通邮箱 SMTP（QQ/163 等，凭据放 SMTP_USER / SMTP_PASS secrets）
  resend —— Resend API（凭据放 RESEND_API_KEY secret）
缺少对应凭据或 email.enabled=false 时静默跳过（记日志）。
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import markdown
import requests

from .models import DailyReport, normalize_insight_md

log = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com/emails"


ACCENT = "#b5432a"
MUTED = "#8a8a8a"
LINE = "#e5e3df"
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _source_links(e) -> str:
    return " · ".join(
        f'<a href="{a.url}" style="color:{MUTED};text-decoration:none">{a.source_name} ↗</a>'
        for a in e.articles
    )


def _insight_sections(text: str) -> list[tuple[str, str]]:
    """把洞察卡片拆成 (小节标题, 正文) 列表。"""
    sections = []
    for chunk in re.split(r"\n+###\s+", "\n" + normalize_insight_md(text)):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, body = chunk.partition("\n")
        sections.append((head.strip(), body.strip()))
    return sections


def _insight_html(text: str) -> str:
    rows = []
    for title, body in _insight_sections(text):
        rows.append(
            f'<p style="margin:10px 0 2px;font-size:12px;color:{ACCENT};'
            f'font-weight:700;letter-spacing:.08em">{title}</p>'
            f'<p style="margin:0;font-size:13.5px;color:#3a3a3a;line-height:1.65">{body}</p>'
        )
    return (
        f'<div style="background:#fdf0ec;border-radius:8px;padding:6px 16px 14px;margin:12px 0">'
        f'<p style="margin:10px 0 0;font-size:11px;color:{ACCENT};font-weight:700;'
        f'letter-spacing:.2em">洞 察</p>' + "".join(rows) + "</div>"
    )


def _section_head(name: str, count: int) -> str:
    return (
        f'<h2 style="font-size:15px;letter-spacing:.05em;color:#1a1a1a;'
        f'border-bottom:2px solid #1a1a1a;padding-bottom:6px;margin:32px 0 4px">'
        f'{name}<span style="color:{MUTED};font-size:12px;font-weight:400">　{count} 条</span></h2>'
    )


def build_email_html(report: DailyReport, site_url: str) -> str:
    """全量邮件：所有事件按分级结构化展示，不需要跳转即可读完当天内容。"""
    must = [e for e in report.events if e.tier == "must_read"]
    worth = [e for e in report.events if e.tier == "worth_reading"]
    skims = [e for e in report.events if e.tier == "skim"]
    weekday = ""
    try:
        from datetime import date
        weekday = WEEKDAYS[date.fromisoformat(report.date).weekday()]
    except ValueError:
        pass

    parts = [
        f'<div style="font-family:-apple-system,\'PingFang SC\',\'Hiragino Sans GB\','
        f'\'Microsoft YaHei\',sans-serif;max-width:640px;margin:0 auto;padding:0 4px;'
        f'color:#1a1a1a;line-height:1.7">',
        # ---- 头部速览 ----
        f'<h1 style="font-size:21px;margin:18px 0 2px">AI 每日简报'
        f'<span style="color:{MUTED};font-size:14px;font-weight:400">　{report.date} {weekday}</span></h1>',
        f'<p style="margin:0 0 4px;font-size:13px;color:{MUTED}">'
        f'今日 {len(report.events)} 个事件 · <strong style="color:{ACCENT}">{len(must)} 条必读</strong>'
        f' · {len(worth)} 条值得看 · {len(skims)} 条可略过</p>',
    ]
    if report.failed_sources:
        names = "、".join(f["name"] for f in report.failed_sources)
        parts.append(f'<p style="margin:2px 0;font-size:12.5px;color:{ACCENT}">'
                     f'⚠ {names} 今日抓取失败，信息可能不完整</p>')

    # ---- 导读 / 看点 ----
    for label, text in (("今日导读", report.briefing), ("今日看点", report.highlights)):
        if text:
            parts.append(
                f'<div style="background:#f7f6f4;border-radius:8px;padding:10px 16px;margin:14px 0">'
                f'<p style="margin:0 0 2px;font-size:12px;color:{ACCENT};font-weight:700;'
                f'letter-spacing:.15em">{label}</p>'
                f'<p style="margin:0;font-size:14px">{text}</p></div>'
            )

    # ---- 必读：编号 + 完整洞察 ----
    if must:
        parts.append(_section_head("必读", len(must)))
        for i, e in enumerate(must, 1):
            parts.append(
                f'<div style="border-left:3px solid {ACCENT};padding:4px 0 4px 14px;margin:20px 0">'
                f'<p style="margin:0;font-size:16.5px;line-height:1.5"><strong>'
                f'<span style="color:{ACCENT}">{i}</span>　{e.title}</strong></p>'
                f'<p style="margin:6px 0;font-size:14px;color:#333">{e.summary}</p>'
                + (_insight_html(e.insight) if e.insight else "")
                + f'<p style="margin:4px 0 0;font-size:12px">{_source_links(e)}</p></div>'
            )

    # ---- 值得看：标题 + 摘要，紧凑 ----
    if worth:
        parts.append(_section_head("值得看", len(worth)))
        for e in worth:
            parts.append(
                f'<div style="border-bottom:1px solid {LINE};padding:12px 0">'
                f'<p style="margin:0;font-size:14.5px"><strong>{e.title}</strong></p>'
                f'<p style="margin:4px 0;font-size:13.5px;color:#444">{e.summary}</p>'
                f'<p style="margin:0;font-size:12px">{_source_links(e)}</p></div>'
            )

    # ---- 可略过：一行一条 ----
    if skims:
        parts.append(_section_head("可略过", len(skims)))
        for e in skims:
            parts.append(
                f'<p style="margin:8px 0;font-size:13px;color:#555">'
                f'{e.title}　<span style="font-size:12px">{_source_links(e)}</span></p>'
            )

    # ---- 页脚 ----
    parts.append(f'<p style="font-size:12px;color:{MUTED};margin:28px 0 4px;'
                 f'border-top:1px solid {LINE};padding-top:12px">'
                 + (f'<a href="{site_url}" style="color:{MUTED}">历史归档 ↗</a> · ' if site_url else "")
                 + '由 AI-News-Delivery 自动生成 · 摘要与洞察由 LLM 生成，请核对原文</p></div>')
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
