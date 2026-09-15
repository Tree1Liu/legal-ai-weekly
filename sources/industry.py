# -*- coding: utf-8 -*-
"""国内外 LLM 厂商与开源社区公开资讯（RSS / 公开列表）。

仅拉取对方公开 feed 或列表页，礼貌限速；不绕过登录与反爬。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin

from utils import make_id, now_cst, parse_source_datetime

logger = logging.getLogger(__name__)


def _normalize(
    title: str,
    url: str,
    source_name: str,
    source_id: str,
    *,
    published_at: str | None = None,
    default_section: str = "global_ai",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    title = (title or "").strip() or url
    url = (url or "").strip()
    # 只保留能解析出的原文时间；禁止用采集时刻冒充发布日
    raw_pub = (published_at or "").strip()
    dt = parse_source_datetime(raw_pub)
    pub_iso = dt.isoformat() if dt else ""
    pub_day = dt.strftime("%Y-%m-%d") if dt else ""
    return {
        "id": make_id(url, title),
        "title": title,
        "url": url,
        "source": source_name,
        "source_id": source_id,
        "source_type": "industry",
        "default_section": default_section,
        "section": default_section,
        "published_at": pub_iso,
        "published_date": pub_day,
        "source_published_at": raw_pub,
        "date_source": "original" if dt else "missing",
        "raw": title,
        "collected_at": now_cst().isoformat(),
        "summary": "",
        "tags": tags or ["开源社区", "LLM"],
        "importance": "medium",
        "need_human_review": True,
        "review_status": "pending",
        "reviewed_by": "",
        "region": "国际" if default_section == "global_ai" else "国内",
    }


def collect_rss(source: dict[str, Any]) -> list[dict[str, Any]]:
    """RSS：OpenAI / Anthropic / Hugging Face / GitHub 等公开 feed。"""
    try:
        import feedparser
    except ImportError as e:
        raise RuntimeError(
            "industry RSS 需要 feedparser：C:\\python\\python.exe -m pip install feedparser"
        ) from e

    url = (source.get("rss_url") or "").strip()
    if not url:
        logger.warning("rss_url 为空，跳过 %s", source.get("id"))
        return []

    pause = float(source.get("pause_seconds") or 0.8)
    if pause > 0:
        time.sleep(pause)

    feed = feedparser.parse(url)
    name = source.get("name") or source.get("id") or "industry"
    sid = source.get("id") or "industry"
    section = source.get("default_section") or "global_ai"
    limit = int(source.get("limit") or 20)
    tags = source.get("tags") or ["开源社区", "LLM"]
    items: list[dict[str, Any]] = []
    for entry in (feed.entries or [])[:limit]:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        published = None
        for attr in ("published", "updated"):
            raw = getattr(entry, attr, None)
            if raw:
                published = str(raw)
                break
        if not link:
            continue
        items.append(
            _normalize(
                title,
                link,
                name,
                sid,
                published_at=published,
                default_section=section,
                tags=list(tags),
            )
        )
    logger.info("行业/LLM RSS 采集 %s：%s 条", name, len(items))
    return items


def collect_http_list(source: dict[str, Any]) -> list[dict[str, Any]]:
    """简易公开列表页：用选择器抓 a[href]（配置 link_selector）。"""
    import requests
    from bs4 import BeautifulSoup

    list_url = (source.get("list_url") or "").strip()
    if not list_url:
        return []
    pause = float(source.get("pause_seconds") or 1.0)
    if pause > 0:
        time.sleep(pause)
    verify = source.get("verify_ssl", True)
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": "LegalAIWeekly/1.0 (+zgc-legal-research; industry-rss)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
    )
    resp = sess.get(list_url, timeout=25, verify=verify)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    selector = source.get("link_selector") or "a[href]"
    name = source.get("name") or source.get("id") or "industry"
    sid = source.get("id") or "industry"
    section = source.get("default_section") or "global_ai"
    limit = int(source.get("limit") or 15)
    tags = source.get("tags") or ["开源社区", "LLM"]
    href_contains = source.get("href_contains") or ""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select(selector):
        href = (a.get("href") or "").strip()
        title = " ".join((a.get_text() or "").split())
        if not href or not title or len(title) < 8:
            continue
        url = urljoin(list_url, href)
        if href_contains and href_contains not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append(
            _normalize(
                title,
                url,
                name,
                sid,
                default_section=section,
                tags=list(tags),
            )
        )
        if len(items) >= limit:
            break
    logger.info("行业/LLM 列表采集 %s：%s 条", name, len(items))
    return items


def collect_industry_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """采集 sources.industry 配置的 LLM/开源社区源。"""
    out: list[dict[str, Any]] = []
    for source in (cfg.get("sources") or {}).get("industry") or []:
        if not source.get("enabled", True):
            continue
        mode = (source.get("mode") or "rss").lower()
        try:
            if mode == "rss":
                out.extend(collect_rss(source))
            elif mode in ("http", "list"):
                out.extend(collect_http_list(source))
            else:
                logger.warning("未知 industry mode=%s，跳过 %s", mode, source.get("id"))
        except Exception as e:
            logger.warning("industry 源失败 %s：%s", source.get("id"), e)
    return out
