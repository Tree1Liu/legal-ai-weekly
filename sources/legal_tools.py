# -*- coding: utf-8 -*-
"""垂类法律工具观察采集。

关注 MyLegalAI / 法天使 / 元典 / 智合 / 豆包 / 扣子 / WorkBuddy / Alpha 等
公开产品页与清单页；不做未授权爬取。微信清单可投递至 inbox。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

from utils import make_id, now_cst, parse_source_datetime

logger = logging.getLogger(__name__)

# 内置观察清单（可被 config.legal_tools_watchlist 覆盖/追加）
DEFAULT_WATCHLIST: list[dict[str, Any]] = [
    {
        "id": "mylegalai",
        "name": "MyLegalAI",
        "vendor": "法天使",
        "url": "https://www.mylegalai.cn/",
        "tags": ["法律AI", "合同", "垂类工具"],
        "note": "法天使 Legal AI 产品；合同审查/起草等能力观察入口",
    },
    {
        "id": "fatianshi",
        "name": "法天使",
        "vendor": "法天使",
        "url": "https://www.fatianshi.cn/",
        "tags": ["法律AI", "合同库", "垂类工具"],
        "note": "中国合同库与合同助手；关注模板、审查点与 AI 搜合同迭代",
    },
    {
        "id": "yuandian",
        "name": "元典",
        "vendor": "华宇元典",
        "url": "https://open.chineselaw.com/",
        "home_url": "https://yuandian.ailaw.cn/YuandianThinkTank/index.html",
        "tags": ["法律AI", "检索", "API", "垂类工具"],
        "note": "元典智库/开放平台；法规案例检索、幻觉检测与智慧法务能力",
    },
    {
        "id": "zhihe",
        "name": "智合",
        "vendor": "智合",
        "url": "https://www.zhihe.law/",
        "tags": ["法律AI", "办案", "垂类工具"],
        "note": "法律科技/智合系产品与内容观察（站点若变更以人工 inbox 为准）",
    },
    {
        "id": "doubao",
        "name": "豆包",
        "vendor": "字节跳动",
        "url": "https://www.doubao.com/",
        "tags": ["通用大模型", "法务应用", "垂类工具"],
        "note": "通用助手在法务场景的可用性与合规边界观察",
    },
    {
        "id": "coze",
        "name": "扣子",
        "vendor": "字节跳动",
        "url": "https://www.coze.cn/",
        "tags": ["Agent", "工作流", "垂类工具"],
        "note": "Agent/工作流搭建平台；关注法务流程自动化落地",
    },
    {
        "id": "workbuddy",
        "name": "WorkBuddy",
        "vendor": "WorkBuddy",
        "url": "https://www.workbuddy.ai/",
        "tags": ["办公AI", "法务提效", "垂类工具"],
        "note": "办公/协作向 AI 助手；关注与法务知识管理结合点",
    },
    {
        "id": "alpha",
        "name": "Alpha",
        "vendor": "Alpha",
        "url": "https://www.alphalawyer.cn/",
        "aliases": ["AIpha", "Alpha智能"],
        "tags": ["法律AI", "律师工具", "垂类工具"],
        "note": "法律检索/文书等律师向工具（品牌名含 Alpha/AIpha 写法）",
    },
]

# 清单/导航源：优先公开列表
DEFAULT_PORTALS: list[dict[str, Any]] = [
    {
        "id": "mylegalai_portal",
        "name": "MyLegalAI 官网",
        "list_url": "https://www.mylegalai.cn/",
        "enabled": True,
        "mode": "portal",
        "default_section": "legal_ai",
        "limit": 8,
    },
    {
        "id": "mylegalai_features",
        "name": "MyLegalAI 功能页",
        "list_url": "https://www.mylegalai.cn/features",
        "enabled": True,
        "mode": "portal",
        "default_section": "legal_ai",
        "limit": 6,
    },
    {
        "id": "fatianshi_home",
        "name": "法天使官网",
        "list_url": "https://www.fatianshi.cn/",
        "enabled": True,
        "mode": "portal",
        "default_section": "legal_ai",
        "limit": 8,
    },
    {
        "id": "yuandian_open",
        "name": "元典开放平台",
        "list_url": "https://open.chineselaw.com/",
        "enabled": True,
        "mode": "portal",
        "default_section": "legal_ai",
        "limit": 6,
    },
]


def watchlist(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    custom = (cfg.get("legal_tools_watchlist") or []) if cfg else []
    if not custom:
        return list(DEFAULT_WATCHLIST)
    # 配置覆盖同 id，其余追加
    by_id = {str(x.get("id")): dict(x) for x in DEFAULT_WATCHLIST if x.get("id")}
    for row in custom:
        rid = str(row.get("id") or row.get("name") or "").strip()
        if not rid:
            continue
        base = by_id.get(rid, {"id": rid})
        base.update(row)
        by_id[rid] = base
    return list(by_id.values())


def tool_name_pattern(cfg: dict[str, Any] | None = None) -> str:
    """供分类/相关性命中的工具名正则。"""
    names: list[str] = []
    for t in watchlist(cfg or {}):
        names.append(re_escape(str(t.get("name") or "")))
        for a in t.get("aliases") or []:
            names.append(re_escape(str(a)))
        if t.get("vendor"):
            names.append(re_escape(str(t["vendor"])))
    names.extend(
        [
            "MyLegalAI",
            "法天使",
            "元典",
            "智合",
            "豆包",
            "扣子",
            "Coze",
            "WorkBuddy",
            "AIpha",
            "Alpha律师",
            "法律科技",
            "合同助手",
        ]
    )
    names = [n for n in names if n]
    return "|".join(dict.fromkeys(names))


def re_escape(s: str) -> str:
    return re.escape(s) if s else ""


def _normalize(
    title: str,
    url: str,
    source_name: str,
    source_id: str,
    *,
    summary: str = "",
    tags: list[str] | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip() or url
    url = (url or "").strip()
    # 站点快照多数无发布日：留空展示为 —，不用采集时刻冒充
    raw_pub = (published_at or "").strip()
    dt = parse_source_datetime(raw_pub)
    return {
        "id": make_id(url, title),
        "title": title,
        "url": url,
        "source": source_name,
        "source_id": source_id,
        "source_type": "legal_tools",
        "default_section": "legal_ai",
        "section": "legal_ai",
        "published_at": dt.isoformat() if dt else "",
        "published_date": dt.strftime("%Y-%m-%d") if dt else "",
        "source_published_at": raw_pub,
        "date_source": "original" if dt else "missing",
        "raw": title,
        "collected_at": now_cst().isoformat(),
        "summary": (summary or "")[:240],
        # 无实质摘要时留空，禁止用标题冒充关键信息
        "key_info": (summary[:300] if summary and summary.strip() != title else ""),
        "tags": tags or ["垂类工具", "法律AI"],
        "importance": "medium",
        "need_human_review": True,
        "review_status": "pending",
        "reviewed_by": "",
        "region": "国内",
        "impact_scenes": ["AI系统采购", "内部合规"],
        "impact_scene_tags": ["#AI系统采购", "#内部合规"],
    }


def _fetch(url: str, pause: float = 0.8, verify_ssl: bool = True) -> str:
    import requests

    if pause > 0:
        time.sleep(pause)
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": "LegalAIWeekly/1.0 (+zgc-legal-research; legal-tools-watch)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    resp = sess.get(url, timeout=25, verify=verify_ssl)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def collect_portal(source: dict[str, Any]) -> list[dict[str, Any]]:
    """从公开门户页抓取有意义的功能/产品链接标题。"""
    from bs4 import BeautifulSoup

    list_url = (source.get("list_url") or "").strip()
    if not list_url:
        return []
    html = _fetch(list_url, float(source.get("pause_seconds") or 0.8), source.get("verify_ssl", True))
    soup = BeautifulSoup(html, "html.parser")
    name = source.get("name") or source.get("id") or "legal_tools"
    sid = source.get("id") or "legal_tools"
    limit = int(source.get("limit") or 8)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    keywords = ("合同", "审查", "起草", "检索", "法务", "法律", "AI", "智能", "文书", "合规", "案例", "法规")
    for a in soup.find_all("a", href=True):
        title = " ".join((a.get_text() or "").split())
        href = (a.get("href") or "").strip()
        if not title or len(title) < 6 or len(title) > 60:
            continue
        if not any(k in title for k in keywords):
            continue
        if title in ("了解更多", "立即体验", "登录", "注册"):
            continue
        url = urljoin(list_url, href)
        if url in seen or url.rstrip("/") == list_url.rstrip("/"):
            continue
        seen.add(url)
        items.append(
            _normalize(
                f"垂类工具动态｜{title}",
                url,
                name,
                sid,
                summary=f"来自 {name} 公开页：{title}",
                tags=["垂类工具", "法律AI", "产品动态"],
            )
        )
        if len(items) >= limit:
            break
    logger.info("垂类工具门户采集 %s：%s 条", name, len(items))
    return items


def collect_watchlist_snapshots(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """为观察清单中每个工具生成一条「观察快照」入法律AI板块。"""
    out: list[dict[str, Any]] = []
    for tool in watchlist(cfg):
        if tool.get("enabled") is False:
            continue
        url = (tool.get("url") or tool.get("home_url") or "").strip()
        if not url:
            continue
        name = tool.get("name") or tool.get("id") or "工具"
        vendor = tool.get("vendor") or ""
        note = tool.get("note") or f"持续观察 {name} 产品迭代与法务场景适用边界。"
        title = f"垂类法律工具观察｜{name}" + (f"（{vendor}）" if vendor and vendor != name else "")
        tags = list(tool.get("tags") or ["垂类工具", "法律AI"])
        out.append(
            _normalize(
                title,
                url,
                f"工具观察-{name}",
                f"watch_{tool.get('id') or name}",
                summary=note,
                tags=tags,
            )
        )
    # 清单文章入口（用户提供）
    out.append(
        _normalize(
            "垂类法律工具清单参考｜行业公开梳理（微信）",
            "https://mp.weixin.qq.com/s/CeYJOQAOEFkGfN8gElCHTg",
            "工具观察清单",
            "watch_wechat_list",
            summary=(
                "用户指定观察清单入口：覆盖 MyLegalAI/法天使、元典、智合、豆包、扣子、"
                "WorkBuddy、Alpha 等垂类与通用工具。建议法务关注合同审查、检索文书、"
                "Agent 工作流与采购合规边界。"
            ),
            tags=["垂类工具", "法律AI", "清单"],
        )
    )
    logger.info("垂类工具观察快照：%s 条", len(out))
    return out


def collect_legal_tool_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """采集配置中的 legal_tools 源 + 默认观察快照。"""
    out: list[dict[str, Any]] = []
    # 1) 观察清单快照（保证法律AI板块每周有工具视角）
    if (cfg.get("weekly") or {}).get("legal_tools_snapshots", True):
        try:
            out.extend(collect_watchlist_snapshots(cfg))
        except Exception as e:
            logger.warning("工具观察快照失败：%s", e)

    # 2) 门户列表
    portals = (cfg.get("sources") or {}).get("legal_tools") or DEFAULT_PORTALS
    for source in portals:
        if not source.get("enabled", True):
            continue
        mode = (source.get("mode") or "portal").lower()
        try:
            if mode in ("portal", "http", "list"):
                out.extend(collect_portal(source))
            else:
                logger.warning("未知 legal_tools mode=%s，跳过 %s", mode, source.get("id"))
        except Exception as e:
            logger.warning("legal_tools 源失败 %s：%s", source.get("id"), e)
    return out
