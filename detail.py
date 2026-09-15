# -*- coding: utf-8 -*-
"""详情页摘要与延伸来源：把关键信息写实（在原有标题摘要之上增强）。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _session():
    import requests

    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "LegalAIWeekly/1.0 (+zgc-legal-research; detail-enrich)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    return s


def fetch_page_snippet(url: str, *, timeout: int = 12, verify_ssl: bool = True) -> str:
    """拉取正文页，提取 meta description 或首段文字。失败返回空串。"""
    text, _pub = fetch_page_snippet_and_date(url, timeout=timeout, verify_ssl=verify_ssl)
    return text


def fetch_page_snippet_and_date(
    url: str, *, timeout: int = 12, verify_ssl: bool = True
) -> tuple[str, str]:
    """拉取正文页摘要；顺带解析「发布时间」等字段，返回 (snippet, YYYY-MM-DD或空)。"""
    if not url or not url.startswith("http"):
        return "", ""
    try:
        from bs4 import BeautifulSoup

        resp = _session().get(url, timeout=timeout, verify=verify_ssl)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        pub_day = ""
        m = re.search(
            r"发布(?:时间|日期)\s*[：:]\s*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
            soup.get_text(" ", strip=True),
        )
        if not m:
            m = re.search(
                r"(20\d{2})-(\d{1,2})-(\d{1,2})\s+\d{1,2}:\d{2}",
                html[:4000],
            )
        if m:
            try:
                y, mo, d = map(int, m.groups()[:3])
                pub_day = f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                pub_day = ""

        meta = ""
        for attrs in (
            {"name": "description"},
            {"name": "Description"},
            {"property": "og:description"},
        ):
            node = soup.find("meta", attrs=attrs)
            if node and node.get("content"):
                meta = " ".join(str(node["content"]).split())
                if len(meta) >= 20:
                    break

        paras: list[str] = []
        for p in soup.find_all(["p", "div"], limit=40):
            t = " ".join((p.get_text() or "").split())
            if len(t) < 40 or len(t) > 500:
                continue
            if re.search(r"版权|ICP|浏览器|点击下载|分享到", t):
                continue
            paras.append(t)
            if len(paras) >= 3:
                break

        if meta and paras:
            return (meta + " " + paras[0])[:280], pub_day
        if meta:
            return meta[:280], pub_day
        if paras:
            return " ".join(paras[:2])[:280], pub_day
        return "", pub_day
    except Exception as e:
        logger.info("详情摘要失败 %s：%s", url[:80], e)
    return "", ""


def match_extended_sources(item: dict[str, Any], cfg: dict[str, Any]) -> str:
    """按关键词匹配配置中的延伸阅读来源。"""
    rules = (cfg.get("extended_sources") or []) if isinstance(cfg.get("extended_sources"), list) else []
    text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('raw', '')}"
    hits: list[str] = []
    for rule in rules:
        kws = rule.get("keywords") or []
        label = rule.get("label") or rule.get("url") or ""
        url = rule.get("url") or ""
        if not kws:
            continue
        if any(re.search(k, text, re.I) for k in kws):
            if url:
                hits.append(f"{label} {url}".strip())
            elif label:
                hits.append(str(label))
        if len(hits) >= 2:
            break
    return "；".join(hits)


def enrich_details(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """在原有 enrich 结果上补充详情摘要与延伸来源。"""
    detail_cfg = cfg.get("detail_enrich") or {}
    if not detail_cfg.get("enabled", True):
        return items
    max_n = int(detail_cfg.get("max_items") or 15)
    pause = float(detail_cfg.get("pause_seconds") or 0.8)
    timeout = int(detail_cfg.get("timeout_seconds") or 12)

    out: list[dict[str, Any]] = []
    fetched = 0
    for item in items:
        row = dict(item)
        # 延伸来源：规则匹配（不依赖网络）
        if not row.get("extended_source"):
            ext = match_extended_sources(row, cfg)
            if ext:
                row["extended_source"] = ext

        need_date = not (row.get("published_date") or "").strip()
        need_detail = fetched < max_n and (
            not row.get("key_info")
            or row.get("key_info") == row.get("title")
            or len(str(row.get("key_info") or "")) < 40
            or need_date
        )
        if need_detail and row.get("url"):
            host = urlparse(row["url"]).netloc.lower()
            verify = "legaldaily" not in host
            if pause > 0:
                time.sleep(pause)
            snippet, pub_day = fetch_page_snippet_and_date(
                row["url"], timeout=timeout, verify_ssl=verify
            )
            fetched += 1
            if snippet and (
                not row.get("key_info")
                or row.get("key_info") == row.get("title")
                or len(str(row.get("key_info") or "")) < 40
            ):
                row["key_info"] = snippet
                if not row.get("summary") or row.get("summary") == row.get("title"):
                    row["summary"] = snippet[:120]
                row["detail_enriched"] = True
            if pub_day and need_date:
                row["published_date"] = pub_day
                row["published_at"] = f"{pub_day}T00:00:00+08:00"
                row["date_source"] = "original"
                row["source_published_at"] = row.get("source_published_at") or pub_day
        out.append(row)
    logger.info("详情摘要：尝试 %s 条，写入 key_info", fetched)
    return out
