# -*- coding: utf-8 -*-
"""钉钉群机器人推送：发送周报摘要 + HTML/MD 路径提示。

正式「在线文档」需钉钉开放平台文档 API；本模块先落地群通知，便于周报节奏跑通。
支持 CloudStudio 部署最新周报为公网链接，点击可直接在手机浏览器查看。
"""

from __future__ import annotations

import logging
import json
import re
from typing import Any

from utils import get_env_key

logger = logging.getLogger(__name__)


def _build_summary(digest: dict[str, Any], cloudstudio_url: str | None = None) -> dict[str, Any]:
    """极简 actionCard：只保留标题、时间、卡片链接。"""
    weekly = digest.get("weekly") or {}
    title = digest.get("title") or "法律AI每周资讯"
    vol = digest.get("vol")
    vol_label = f" 第{vol}期" if vol else ""
    subtitle = f"**{title}**{vol_label}"

    weekly_meta = weekly.get("date_range", "")

    # 直接用 date_range（已格式化为 2026.08.28 至 09.04）
    date_display = weekly_meta

    # 只放标题 + 时间 + 链接
    content_parts = [subtitle, "", f"📅 {date_display}"]
    if cloudstudio_url:
        content_parts.append(f"[**点击查看完整周报**]({cloudstudio_url})")

    text = "\n".join(content_parts)

    return {
        "title": subtitle,
        "text": text,
    }


def _build_markdown(digest: dict[str, Any]) -> str:
    """优先用固定模版正文；过长则截断并提示打开本地 MD/HTML。"""
    try:
        from report_html import digest_to_template_markdown

        text = digest_to_template_markdown(digest)
    except Exception:
        text = str(digest.get("title") or "法律AI每周资讯")
    paths = digest.get("_paths") or {}
    # 钉钉单条不宜过长
    if len(text) > 3500:
        text = text[:3400] + "\n\n…（正文已截断，请打开本地 HTML/MD 全文）\n"
    html = paths.get("html") or ""
    md = paths.get("md") or ""
    if html or md:
        text += "\n\n**本地产出**\n"
        if html:
            text += f"- HTML：`{html}`\n"
        if md:
            text += f"- Markdown：`{md}`\n"
    return text


def push_dingtalk(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    dt = cfg.get("dingtalk") or {}
    if not dt.get("enabled", False):
        return {"ok": True, "skipped": True, "reason": "dingtalk.disabled"}

    dry_run = bool(cfg.get("dry_run", True))
    webhook = (dt.get("webhook") or "").strip() or get_env_key(dt.get("webhook_env") or "DINGTALK_WEBHOOK")
    title = digest.get("title") or "法律AI每周资讯"
    use_action_card = dt.get("use_action_card", True)

    # 尝试获取 CloudStudio 公网链接（从上次部署缓存或配置）
    cloudstudio_url = None
    cs_cfg = cfg.get("cloudstudio") or {}
    if cs_cfg.get("last_url"):
        cloudstudio_url = cs_cfg["last_url"]
        logger.info("使用上次 CloudStudio 部署链接：%s", cloudstudio_url)

    if use_action_card:
        card = _build_summary(digest, cloudstudio_url)
        markdown_text = card["text"]
    else:
        markdown_text = _build_markdown(digest)

    if dry_run:
        preview = markdown_text[:800] if len(markdown_text) > 800 else markdown_text
        print(f"\n{'='*60}")
        print(f"【钉钉推送预览 - {card['title']}")
        print(f"{'='*60}")
        print(preview)
        if len(markdown_text) > 800:
            print(f"\n... (已截断，共 {len(markdown_text)} 字符)")
        print(f"{'='*60}")
        logger.info("dry_run=true，跳过钉钉真实推送。标题=%s webhook=%s", title, bool(webhook))
        return {"ok": True, "dry_run": True, "preview_chars": len(markdown_text)}

    if not webhook:
        logger.error("钉钉 webhook 未配置（dingtalk.webhook 或环境变量）")
        return {"ok": False, "error": "webhook_missing"}

    try:
        import requests

        push_style = (dt.get("push_style") or "link").strip().lower()

        if push_style == "link" and cloudstudio_url:
            # 分享链接卡片：钉钉 link 消息，渲染为「标题 + 摘要 + 链接」卡片
            weekly = digest.get("weekly") or {}
            date_range = (weekly.get("date_range") or "").strip()
            card_text = f"{title}"
            if date_range:
                card_text += f" · {date_range}"
            payload = {
                "msgtype": "link",
                "link": {
                    "title": title[:64],
                    "text": card_text[:200],
                    "messageUrl": cloudstudio_url,
                },
            }
        elif use_action_card:
            payload = {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": card["title"],
                    "text": markdown_text,
                    "singleTitle": "点击这里查看完整周报" if cloudstudio_url else "打开本地 HTML 全文",
                    "singleURL": cloudstudio_url or "",
                },
            }
        else:
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": title[:64], "text": markdown_text},
            }
        # 可选 @all
        if dt.get("at_all"):
            payload["at"] = {"isAtAll": True}
        resp = requests.post(webhook, json=payload, timeout=int(dt.get("timeout_seconds") or 15))
        ok = 200 <= resp.status_code < 300
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        if isinstance(body, dict) and body.get("errcode") not in (None, 0):
            ok = False
        logger.info("钉钉推送 status=%s ok=%s body=%s", resp.status_code, ok, str(body)[:200])
        return {"ok": ok, "status_code": resp.status_code, "body": body}
    except Exception as e:
        logger.exception("钉钉推送失败：%s", e)
        return {"ok": False, "error": str(e)}