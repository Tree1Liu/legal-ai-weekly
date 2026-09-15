# -*- coding: utf-8 -*-
"""官网公开页采集器。

可做：人大网、中国政府网等「公开列表页」标题 + 链接，限速礼貌访问。
不可做：微信公众号未授权批量爬取、绕过登录/验证码/反爬。

说明：个人自用、非商业，不等于平台允许爬取微信；官网公开信息可按礼仪采集。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urljoin

from utils import CST, extract_date_from_url, make_id, now_cst, parse_source_datetime

logger = logging.getLogger(__name__)

# 内置样例：离线调试
SAMPLE_ITEMS = {
    "npc_law": [
        {
            "title": "（样例）关于修改《中华人民共和国公司法》的决定",
            "url": "https://www.npc.gov.cn/sample/company-law-amendment",
            "published_at": None,
        },
    ],
    "gov_cn_policy": [
        {
            "title": "（样例）国务院关于加强数字经济治理的意见",
            "url": "https://www.gov.cn/sample/digital-economy",
            "published_at": None,
        },
    ],
}

DATE_RE = re.compile(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})")


def _normalize_item(raw: dict[str, Any], source_name: str, source_id: str) -> dict[str, Any]:
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    published = raw.get("published_at")
    dt = None
    if published:
        if isinstance(published, datetime):
            dt = published if published.tzinfo else published.replace(tzinfo=CST)
            dt = dt.astimezone(CST) if dt.tzinfo else dt
        else:
            dt = parse_source_datetime(published)
    if not dt:
        dt = extract_date_from_url(url)
    # 无原文时间则留空，禁止用采集时刻冒充发布日
    pub_iso = dt.isoformat() if dt else ""
    pub_day = dt.strftime("%Y-%m-%d") if dt else ""

    return {
        "id": make_id(url, title),
        "title": title,
        "url": url,
        "source": source_name,
        "source_id": source_id,
        "source_type": "gov",
        "published_at": pub_iso,
        "published_date": pub_day,
        "source_published_at": str(published or ""),
        "date_source": "original" if dt else "missing",
        "raw": raw.get("raw") or title,
        "collected_at": now_cst().isoformat(),
        "summary": "",
        "tags": [],
        "importance": "medium",
        "need_human_review": True,
        "review_status": "pending",
        "reviewed_by": "",
    }


def _session():
    import requests

    s = requests.Session()
    s.headers.update(
        {
            # 标明用途，便于对方识别；勿伪装成无关爬虫集群
            "User-Agent": (
                "LegalAIWeekly/1.0 (+zgc-legal-research; respectful-fetcher; "
                "internal-digest)"
            ),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    return s


def _fetch_html(url: str, pause_seconds: float = 1.2, verify_ssl: bool = True) -> str:
    """限速 GET。pause 默认 ≥1 秒，避免打爆官网。"""
    if pause_seconds > 0:
        time.sleep(pause_seconds)
    sess = _session()
    logger.info("请求：%s", url)
    resp = sess.get(url, timeout=25, verify=verify_ssl)
    resp.raise_for_status()
    # 政府站常见 gbk / utf-8 混用
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _parse_date_text(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return datetime(y, mo, d, tzinfo=CST).isoformat()


def parse_npc_clist(html: str, list_url: str, limit: int = 40) -> list[dict[str, Any]]:
    """中国人大网立法栏目：ul.clist > li > a + span(日期)。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for li in soup.select("ul.clist li"):
        a = li.find("a", href=True)
        if not a:
            continue
        title = " ".join((a.get_text() or "").split())
        href = (a.get("href") or "").strip()
        if not title or not href or href.startswith("javascript"):
            continue
        url = urljoin(list_url, href)
        if url in seen:
            continue
        seen.add(url)
        span = li.find("span")
        published = _parse_date_text(span.get_text() if span else "")
        items.append({"title": title, "url": url, "published_at": published, "raw": title})
        if len(items) >= limit:
            break
    return items


def parse_gov_zhengce(html: str, list_url: str, limit: int = 40) -> list[dict[str, Any]]:
    """中国政府网政策页：抓取 /zhengce/content/ 下的政策链接。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 优先：最新政策区块里的 li
    candidates = soup.select("div.item li") or soup.select("li")
    for li in candidates:
        a = li.find("a", href=True)
        if not a:
            continue
        href = (a.get("href") or "").strip()
        title = " ".join((a.get_text() or "").split())
        if not title or len(title) < 6:
            continue
        url = urljoin(list_url, href)
        # 只要政策正文类链接，过滤导航
        if "/zhengce/content/" not in url and "content_" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        span = li.find("span")
        published = _parse_date_text(span.get_text() if span else "")
        items.append({"title": title, "url": url, "published_at": published, "raw": title})
        if len(items) >= limit:
            break

    # 兜底：全页扫描 content 链接
    if not items:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            url = urljoin(list_url, href)
            if "/zhengce/content/" not in url:
                continue
            title = " ".join((a.get_text() or "").split())
            if len(title) < 6 or url in seen:
                continue
            seen.add(url)
            items.append({"title": title, "url": url, "published_at": None, "raw": title})
            if len(items) >= limit:
                break
    return items


def parse_court_zixun(html: str, list_url: str, limit: int = 40) -> list[dict[str, Any]]:
    """最高人民法院资讯列表：/zixun/xiangqing/ 链接。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = " ".join((a.get_text() or "").split())
        if len(title) < 8:
            continue
        url = urljoin(list_url, href)
        if "/zixun/xiangqing/" not in url and "/xiangqing/" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "published_at": None, "raw": title})
        if len(items) >= limit:
            break
    return items


def parse_legaldaily(html: str, list_url: str, limit: int = 40) -> list[dict[str, Any]]:
    """法治日报官网首页/频道：抓取 content_*.html 类稿件链接。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = " ".join((a.get_text() or "").split())
        if len(title) < 8:
            continue
        url = urljoin(list_url, href)
        if "legaldaily.com.cn" not in url:
            continue
        if "content_" not in url and "/content/" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "published_at": None, "raw": title})
        if len(items) >= limit:
            break
    return items


def parse_generic_list(
    html: str,
    list_url: str,
    limit: int = 40,
    *,
    url_contains: list[str] | None = None,
    url_exclude: list[str] | None = None,
    title_min_len: int = 8,
    host_must: str = "",
    title_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """通用公开列表解析：按域名/路径关键词过滤链接。"""
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse

    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    host_must = (host_must or "").lower()
    url_contains = [x for x in (url_contains or []) if x]
    url_exclude = [x for x in (url_exclude or []) if x]
    title_keywords = [x for x in (title_keywords or []) if x]

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = " ".join((a.get_text() or "").strip().split())
        if len(title) < title_min_len:
            continue
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(list_url, href)
        if url in seen:
            continue
        parsed = urlparse(url)
        if host_must and host_must not in (parsed.netloc or "").lower():
            continue
        if url_contains and not any(k in url for k in url_contains):
            continue
        if url_exclude and any(k in url for k in url_exclude):
            continue
        if title_keywords and not any(k.lower() in title.lower() for k in title_keywords):
            # 列表页可能混杂导航；无关键词时跳过（源配置开启时）
            continue
        seen.add(url)
        published = _parse_date_text(title) or _parse_date_text(a.parent.get_text() if a.parent else "")
        items.append({"title": title, "url": url, "published_at": published, "raw": title})
        if len(items) >= limit:
            break
    return items


# 按 source.id 绑定解析器；也可在 config 里用 parser 字段覆盖
PARSERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "npc_law": parse_npc_clist,
    "gov_cn_policy": parse_gov_zhengce,
    "court_news": parse_court_zixun,
    "legaldaily": parse_legaldaily,
    "generic_list": parse_generic_list,
}


def collect_sample(source: dict[str, Any]) -> list[dict[str, Any]]:
    sid = source["id"]
    name = source.get("name", sid)
    rows = SAMPLE_ITEMS.get(sid, [])
    logger.info("官网样例采集 %s：%s 条", name, len(rows))
    return [_normalize_item(r, name, sid) for r in rows]


def collect_http(source: dict[str, Any]) -> list[dict[str, Any]]:
    """按配置拉取公开列表页并解析。"""
    list_url = source["list_url"]
    limit = int(source.get("limit") or 40)
    pause = float(source.get("pause_seconds") or 1.2)
    verify_ssl = bool(source.get("verify_ssl", True))
    html = _fetch_html(list_url, pause_seconds=pause, verify_ssl=verify_ssl)

    parser_name = source.get("parser") or source["id"]
    parser = PARSERS.get(parser_name)
    if parser_name == "generic_list" or parser is parse_generic_list:
        rows = parse_generic_list(
            html,
            list_url,
            limit,
            url_contains=source.get("url_contains") or [],
            url_exclude=source.get("url_exclude") or ["javascript"],
            title_min_len=int(source.get("title_min_len") or 8),
            host_must=source.get("host_must") or "",
            title_keywords=source.get("title_keywords") or [],
        )
    elif parser is None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        selector = source.get("item_selector") or "a"
        rows = []
        for a in soup.select(selector)[: limit * 3]:
            title = " ".join((a.get_text() or "").split())
            href = (a.get("href") or "").strip()
            if not title or not href or len(title) < int(source.get("title_min_len") or 8):
                continue
            url = urljoin(list_url, href)
            must = source.get("url_contains") or []
            if must and not any(k in url for k in must):
                continue
            rows.append({"title": title, "url": url, "raw": title})
            if len(rows) >= limit:
                break
    else:
        rows = parser(html, list_url, limit)

    name = source.get("name", source["id"])
    logger.info("官网采集 %s：解析到 %s 条", name, len(rows))
    out = [_normalize_item(r, name, source["id"]) for r in rows]
    # 标记权威/行业类别，供周报筛选
    for row in out:
        row["source_tier"] = source.get("tier") or "authority"
        row["source_org"] = source.get("org") or name
    return out


def collect_gov_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source in cfg.get("sources", {}).get("gov", []):
        if not source.get("enabled", True):
            continue
        mode = source.get("mode", "sample")
        if mode == "sample":
            out.extend(collect_sample(source))
        elif mode == "http":
            try:
                out.extend(collect_http(source))
            except Exception as e:
                logger.exception("官网采集失败 %s: %s", source.get("id"), e)
        else:
            logger.warning("未知 gov mode=%s，跳过 %s", mode, source.get("id"))
    return out
