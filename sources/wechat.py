# -*- coding: utf-8 -*-
"""公众号采集（准自动，不做未授权账号爬虫）。

支持：
1) inbox      —— 文本文件粘贴
2) queue      —— data/inbox/auto_queue.jsonl（合规系统或人工写入）
3) rss        —— 已有合规 RSS 地址时全自动拉新
4) social_api —— 两院已购公众号数据接口（内网 social-posts/wechat-mp）

无人值守请使用已授权 RSS、合规数据接口或将链接写入 inbox。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from utils import CST, make_id, now_cst, parse_source_datetime, project_root, resolve_lookback_since

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s]+", re.I)


def _normalize(
    title: str,
    url: str,
    source_name: str,
    source_id: str,
    published_at: str | None = None,
    account: str = "",
    *,
    summary: str = "",
    category: str = "",
    default_section: str = "",
) -> dict[str, Any]:
    title = (title or "").strip() or url
    url = (url or "").strip()
    tags: list[str] = []
    if account:
        tags.append(account)
    if category and category not in tags:
        tags.append(category)
    raw_pub = (published_at or "").strip()
    dt = parse_source_datetime(raw_pub)
    summary = (summary or "").strip()
    row: dict[str, Any] = {
        "id": make_id(url or title, title),
        "title": title,
        "url": url,
        "source": source_name if not account else f"{source_name}-{account}",
        "source_id": source_id,
        "source_type": "wechat",
        "account": account,
        "published_at": dt.isoformat() if dt else "",
        "published_date": dt.strftime("%Y-%m-%d") if dt else "",
        "source_published_at": raw_pub,
        "date_source": "original" if dt else "missing",
        "raw": title,
        "collected_at": now_cst().isoformat(),
        "summary": summary[:240],
        "key_info": summary[:300] if summary else "",
        "tags": tags,
        "importance": "medium",
        "need_human_review": True,
        "review_status": "pending",
        "reviewed_by": "",
        "region": "国内",
    }
    if default_section:
        row["default_section"] = default_section
        row["section"] = default_section
    return row


def _match_watch_name(text: str, watch_names: list[str]) -> str:
    for name in watch_names:
        if name and name in (text or ""):
            return name
    return ""


def _iso_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(CST).strftime("%Y-%m-%d")


def collect_social_api(source: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """两院已购公众号库：GET /api/social-posts/wechat-mp。"""
    api_base = (source.get("api_base") or "http://10.1.132.21:8001").rstrip("/")
    api_path = source.get("api_path") or "/api/social-posts/wechat-mp"
    timeout = float(source.get("timeout_seconds") or 25)
    page_size = int(source.get("page_size") or 50)
    max_pages = int(source.get("max_pages") or 6)
    max_items = int(source.get("limit") or source.get("max_items") or 120)
    keyword = (source.get("keyword") or "").strip()
    category = (source.get("category") or "").strip()
    watch_names = [
        str(x).strip()
        for x in (source.get("watch_names") or source.get("account_names") or [])
        if str(x).strip()
    ]
    default_section = (source.get("default_section") or "").strip()
    name = source.get("name") or source.get("id") or "wechat_social_api"

    since = resolve_lookback_since(cfg)
    until = now_cst()
    date_from = (source.get("date_from") or "").strip() or _iso_date(since)
    date_to = (source.get("date_to") or "").strip() or _iso_date(until)

    items: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages and len(items) < max_items:
        params: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "sort_by": source.get("sort_by") or "published_at",
            "order": source.get("order") or "desc",
            "page": page,
            "page_size": min(page_size, max_items - len(items)),
        }
        if keyword:
            params["keyword"] = keyword
        if category:
            params["category"] = category
        # 名单不太长时交给接口侧模糊匹配
        if watch_names and len(",".join(watch_names)) <= 800:
            params["account_names"] = ",".join(watch_names)

        url = f"{api_base}{api_path}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "LegalAIWeekly/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
        except urllib.error.HTTPError as e:
            logger.warning("公众号 social_api HTTP %s：%s", e.code, url[:120])
            break
        except Exception as e:
            logger.warning("公众号 social_api 失败：%s", e)
            break

        rows = payload.get("items") or []
        if not rows:
            break
        for row in rows:
            title = str(row.get("title") or "").strip()
            link = str(row.get("post_url") or row.get("url") or "").strip()
            if not title and not link:
                continue
            account = str(
                row.get("author_display_name") or row.get("author_username") or ""
            ).strip()
            if watch_names:
                if not account:
                    continue
                ok = any(w in account or account in w for w in watch_names)
                if not ok:
                    continue
            published = row.get("published_at") or row.get("crawled_at")
            summary = str(row.get("content_text") or row.get("summary") or "").strip()
            cat = str(row.get("source_category") or category or "").strip()
            items.append(
                _normalize(
                    title,
                    link,
                    name,
                    source.get("id") or "wechat_social_api",
                    published,
                    account,
                    summary=summary,
                    category=cat,
                    default_section=default_section,
                )
            )
            if len(items) >= max_items:
                break

        total_pages = int(payload.get("total_pages") or 0)
        if total_pages and page >= total_pages:
            break
        if len(rows) < int(params["page_size"]):
            break
        page += 1

    logger.info(
        "公众号 social_api 采集 %s：%s 条（%s～%s，账号筛 %s）",
        name,
        len(items),
        date_from,
        date_to,
        len(watch_names) or "全部",
    )
    return items


def collect_queue(inbox_dir: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    """读取一键投递 / 机器人写入的 auto_queue.jsonl。"""
    path = inbox_dir / "auto_queue.jsonl"
    name = source.get("name", source["id"])
    watch_names = source.get("watch_names") or []
    if not path.exists():
        logger.info("公众号队列为空（尚无 %s）", path.name)
        return []

    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = (row.get("url") or "").strip()
        if not url:
            continue
        title = (row.get("title") or "").strip() or url
        published = row.get("received_at") or row.get("published_at")
        account = (row.get("account") or "").strip() or _match_watch_name(
            f"{title} {row.get('raw','')}", watch_names
        )
        items.append(_normalize(title, url, name, source["id"], published, account))

    logger.info("公众号队列采集 %s：%s 条", name, len(items))
    return items


def collect_inbox(inbox_dir: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 inbox：支持 .txt（每行 URL 或「标题|URL」）。"""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    readme = inbox_dir / "README.txt"
    if not readme.exists():
        readme.write_text(
            "补充入队说明：\n"
            "1) 本目录放 .txt，每行 URL 或「标题|URL」\n"
            "2) 亦可启用 sources.wechat mode=social_api 对接两院已购公众号库\n"
            "3) 配置合规 rss_url 后改 mode=rss\n",
            encoding="utf-8",
        )

    name = source.get("name", source["id"])
    watch_names = source.get("watch_names") or []
    items: list[dict[str, Any]] = []
    for path in sorted(inbox_dir.glob("*.txt")):
        if path.name.upper().startswith("README"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                title, url = [x.strip() for x in line.split("|", 1)]
            else:
                m = URL_RE.search(line)
                if not m:
                    continue
                url = m.group(0)
                title = line.replace(url, "").strip() or url
            account = _match_watch_name(title, watch_names)
            items.append(_normalize(title, url, name, source["id"], account=account))

    logger.info("公众号 inbox 采集 %s：%s 条", name, len(items))
    return items


def collect_rss(source: dict[str, Any]) -> list[dict[str, Any]]:
    """RSS：仅当配置了合法可访问的 rss_url 时全自动。"""
    try:
        import feedparser
    except ImportError as e:
        raise RuntimeError(
            "RSS 模式需要 feedparser：C:\\python\\python.exe -m pip install feedparser"
        ) from e

    url = source.get("rss_url") or ""
    if not url:
        logger.warning("rss_url 为空，跳过 %s", source.get("id"))
        return []

    feed = feedparser.parse(url)
    name = source.get("name", source["id"])
    items = []
    for entry in feed.entries[:50]:
        title = getattr(entry, "title", "") or ""
        link = getattr(entry, "link", "") or ""
        published = None
        if getattr(entry, "published", None):
            published = entry.published
        items.append(_normalize(title, link, name, source["id"], published))
    logger.info("公众号 RSS 采集 %s：%s 条", name, len(items))
    return items


def collect_wechat_sources(cfg: dict[str, Any], inbox_dir: Path | None = None) -> list[dict[str, Any]]:
    if inbox_dir is None:
        inbox_dir = project_root() / "data" / "inbox"
    out: list[dict[str, Any]] = []
    for source in cfg.get("sources", {}).get("wechat", []):
        if not source.get("enabled", True):
            continue
        mode = source.get("mode", "queue")
        if mode == "inbox":
            out.extend(collect_inbox(inbox_dir, source))
        elif mode == "queue":
            # 队列 + 文本 inbox 一并收，避免旧习惯失效
            out.extend(collect_queue(inbox_dir, source))
            out.extend(collect_inbox(inbox_dir, source))
        elif mode == "rss":
            try:
                out.extend(collect_rss(source))
            except Exception as e:
                logger.exception("公众号 RSS 失败 %s: %s", source.get("id"), e)
        elif mode in ("social_api", "api", "purchased_api"):
            try:
                out.extend(collect_social_api(source, cfg))
            except Exception as e:
                logger.exception("公众号 social_api 失败 %s: %s", source.get("id"), e)
        else:
            logger.warning("未知 wechat mode=%s，跳过 %s", mode, source.get("id"))
    return out
