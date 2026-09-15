# -*- coding: utf-8 -*-
"""流水线：采集 → 去重 → 初筛 → 人审 → 打包。

默认产出「法律AI每周资讯」（见《周报说明》）；product_mode=daily 时保留原日报能力。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from enrich import SECTION_LABELS, enrich_items
from curate import curate_items
from detail import enrich_details
from report_html import digest_to_html, digest_to_template_markdown, format_title
from review import apply_review
from sources.gov import collect_gov_sources
from sources.wechat import collect_wechat_sources
from sources.industry import collect_industry_sources
from sources.legal_tools import collect_legal_tool_sources
from summarize import attach_ai_summary, aggregate_sections_with_llm, rewrite_legal_focus_for_digest
from sections_strategy import reorganize_sections_by_strategy
from utils import (
    CST,
    append_jsonl,
    ensure_dirs,
    next_weekly_vol,
    normalize_published_fields,
    now_cst,
    project_root,
    read_jsonl,
    resolve_lookback_since,
    write_json,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)
        return dt
    except ValueError:
        return None


def filter_by_window(
    items: list[dict[str, Any]],
    since: datetime,
    *,
    also_by_collected: bool = True,
) -> list[dict[str, Any]]:
    """时间窗过滤。

    先规范化原文发布日（含 URL 路径纠偏）。
    有明确原文日且早于窗口 → 一律剔除，不用 collected_at 兜底
    （避免政务列表页反复挂出 2023 年旧文仍因「本周采到」入刊）。
    also_by_collected 仅在解析不出原文发布时间时生效。
    """
    kept: list[dict[str, Any]] = []
    dropped_stale = 0
    for item in items:
        row = normalize_published_fields(item)
        pub = _parse_dt(row.get("published_at"))
        col = _parse_dt(row.get("collected_at") or item.get("collected_at"))
        out = dict(item)
        out["published_at"] = row.get("published_at") or ""
        out["published_date"] = row.get("published_date") or ""
        out["date_source"] = row.get("date_source") or out.get("date_source") or ""

        if pub is not None:
            if pub >= since:
                kept.append(out)
            else:
                dropped_stale += 1
                logger.debug(
                    "剔除过期原文：%s（%s）",
                    (out.get("title") or "")[:40],
                    out.get("published_date"),
                )
            continue
        if also_by_collected and col is not None and col >= since:
            kept.append(out)
            continue
        if col is None:
            kept.append(out)
    if dropped_stale:
        logger.info(
            "时间窗剔除明确过期原文 %s 条（早于 %s）",
            dropped_stale,
            since.date() if hasattr(since, "date") else since,
        )
    return kept


def drop_stale_published(
    items: list[dict[str, Any]],
    since: datetime,
) -> list[dict[str, Any]]:
    """二次闸门：enrich/库回放后，仍按规范化原文日剔除过期条目。"""
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        row = normalize_published_fields(item)
        pub = _parse_dt(row.get("published_at"))
        out = dict(item)
        out["published_at"] = row.get("published_at") or out.get("published_at") or ""
        out["published_date"] = row.get("published_date") or out.get("published_date") or ""
        out["date_source"] = row.get("date_source") or out.get("date_source") or ""
        if pub is not None and pub < since:
            dropped += 1
            continue
        kept.append(out)
    if dropped:
        logger.info("二次时效闸门剔除过期原文 %s 条", dropped)
    return kept


def dedup(items: list[dict[str, Any]], existing_ids: set[str]) -> list[dict[str, Any]]:
    out = []
    seen = set(existing_ids)
    for item in items:
        iid = item.get("id")
        if not iid or iid in seen:
            continue
        # 无链接视为无效
        if not (item.get("url") or "").strip():
            logger.info("丢弃无链接条目：%s", item.get("title"))
            continue
        seen.add(iid)
        out.append(item)
    return out


def _group_sections(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "global_ai": [],
        "legal_ai": [],
        "two_institute": [],
    }
    rank = {"high": 0, "medium": 1, "low": 2}
    for item in items:
        sec = item.get("section") or "legal_ai"
        if sec not in groups:
            sec = "legal_ai"
        groups[sec].append(item)
    for key in groups:
        groups[key] = sorted(groups[key], key=lambda x: (rank.get(x.get("importance"), 9), -int(x.get("relevance_score") or 0)))
    return groups


def _balance_two_institute(
    sections: dict[str, list[dict[str, Any]]],
    min_ratio: float = 0.5,
) -> dict[str, list[dict[str, Any]]]:
    """尽量让两院法务板块条目占比接近建议值（通过排序展示，不硬删其他板块）。"""
    total = sum(len(v) for v in sections.values())
    if total == 0:
        return sections
    ti = len(sections.get("two_institute") or [])
    ratio = ti / total
    sections = dict(sections)
    sections["_meta"] = {"two_institute_ratio": round(ratio, 3), "target_ratio": min_ratio}
    return sections


def build_digest(items: list[dict[str, Any]], run_at: datetime) -> dict[str, Any]:
    """保留原日报结构。"""
    approved = [i for i in items if i.get("review_status") == "approved"]
    pending = [i for i in items if i.get("review_status") == "pending"]
    rejected = [i for i in items if i.get("review_status") == "rejected"]

    rank = {"high": 0, "medium": 1, "low": 2}
    approved_sorted = sorted(approved, key=lambda x: rank.get(x.get("importance"), 9))

    return {
        "generated_at": run_at.isoformat(),
        "title": f"法规情报日报 {run_at.strftime('%Y-%m-%d %H:%M')}",
        "counts": {
            "approved": len(approved_sorted),
            "pending": len(pending),
            "rejected": len(rejected),
            "total_in_batch": len(items),
        },
        "items": approved_sorted,
        "pending_items": pending,
    }


def build_weekly_digest(
    items: list[dict[str, Any]],
    run_at: datetime,
    cfg: dict[str, Any],
    since: datetime,
    vol: int,
) -> dict[str, Any]:
    """按《周报说明》固定模版打包周报。"""
    weekly_cfg = cfg.get("weekly") or {}
    brand = weekly_cfg.get("brand") or "法律AI每周资讯"
    audience = weekly_cfg.get("audience") or (
        "面向两院法务和管理层，按照两院适配行业、单位性质提供前沿法律咨询"
    )
    min_ratio = float(weekly_cfg.get("two_institute_min_ratio") or 0.5)

    # 周报对外展示：时间窗内入刊条目全部进入板块
    pool = list(items)
    approved = [i for i in items if i.get("review_status") == "approved"]
    pending = [i for i in items if i.get("review_status") == "pending"]
    rejected = [i for i in items if i.get("review_status") == "rejected"]
    sections = _balance_two_institute(_group_sections(pool), min_ratio)
    flash_items = [i for i in pool if i.get("is_flash")]

    start_year = since.year
    end_year = run_at.year
    if start_year == end_year:
        date_range = f"{since.strftime('%Y.%m.%d')} 至 {run_at.strftime('%m.%d')}"
    else:
        date_range = f"{since.strftime('%Y.%m.%d')} 至 {run_at.strftime('%Y.%m.%d')}"
    judgment_default = "关注 AI/数据监管变化对两院科研、采购与合规边界的传导。"
    title = format_title(brand, vol)

    return {
        "generated_at": run_at.isoformat(),
        "product_mode": "weekly",
        "vol": vol,
        "title": title,
        "counts": {
            "approved": len(approved),
            "pending": len(pending),
            "rejected": len(rejected),
            "total_in_batch": len(pool),
            "flash": len(flash_items),
            "by_section": {k: len(sections.get(k) or []) for k in ("global_ai", "legal_ai", "two_institute")},
            "sources": len({i.get("source") for i in pool if i.get("source")}),
        },
        "items": pool,
        "pending_items": [],
        "sections": {k: sections.get(k) or [] for k in ("global_ai", "legal_ai", "two_institute")},
        "section_labels": SECTION_LABELS,
        "flash_items": flash_items,
        "weekly": {
            "brand": brand,
            "vol": vol,
            "date_range": date_range,
            "audience": audience,
            "positioning": "",
            "judgment_clue": judgment_default,
            "mainline": "本期围绕 AI 监管、数据合规与两院管理场景筛选要点，供法务例会讨论。",
            "directions": weekly_cfg.get("directions") or [],
            "window_since": since.isoformat(),
            "section_meta": sections.get("_meta") or {},
        },
    }


def digest_to_markdown(digest: dict[str, Any]) -> str:
    """Markdown：周报严格走固定模版；日报保持原列表。"""
    if (digest.get("product_mode") or "") in ("weekly", "quarterly") or digest.get("sections"):
        return digest_to_template_markdown(digest)
    lines = [
        f"# {digest.get('title')}",
        "",
        f"生成时间：{digest.get('generated_at')}",
        f"可推送：{digest['counts']['approved']}｜待审：{digest['counts']['pending']}",
        "",
    ]

    ai = digest.get("ai_summary") or {}
    if ai.get("briefing"):
        mode = ai.get("mode") or ""
        label = "AI 整理总结" if mode == "llm" else "自动整理总结（规则）"
        lines.extend([f"## {label}", "", ai["briefing"], "", "---", ""])

    for i, item in enumerate(digest.get("items") or [], 1):
        tags = "、".join(item.get("tags") or [])
        lines.extend(
            [
                f"## {i}. {item.get('title')}",
                f"- 来源：{item.get('source')}（{item.get('source_type')}）",
                f"- 重要级：{item.get('importance')}｜标签：{tags}",
                f"- 摘要：{item.get('summary')}",
                f"- 链接：{item.get('url')}",
                "",
            ]
        )
    if digest.get("pending_items"):
        lines.append("## 待人审（未推送）")
        lines.append("")
        for item in digest["pending_items"]:
            lines.append(f"- {item.get('title')} → {item.get('url')}")
        lines.append("")
    return "\n".join(lines)


def recent_from_store(store_rows: list[dict[str, Any]], since: datetime, limit: int = 40) -> list[dict[str, Any]]:
    """从已入库记录里取回看窗口内条目，用于「无新增时仍能看周报/日报」。

    有明确原文发布日时只认发布日；不用采集日把旧文捞回来。
    """
    kept = []
    for item in reversed(store_rows):
        row = normalize_published_fields(item)
        pub = _parse_dt(row.get("published_at"))
        col = _parse_dt(row.get("collected_at"))
        if pub is not None:
            if pub < since:
                continue
        elif col is not None and col < since:
            continue
        # pub 在窗内，或无原文日但采集日在窗内 / 双空
        out = dict(item)
        out["published_at"] = row.get("published_at") or out.get("published_at") or ""
        out["published_date"] = row.get("published_date") or out.get("published_date") or ""
        out["date_source"] = row.get("date_source") or out.get("date_source") or ""
        kept.append(out)
        if len(kept) >= limit:
            break
    return list(reversed(kept))


def merge_by_id(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 id 合并多批条目，后写覆盖先写。"""
    out: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group or []:
            iid = row.get("id")
            if not iid:
                continue
            out[iid] = row
    return list(out.values())


def run_pipeline(cfg: dict[str, Any], *, flash_only: bool = False) -> dict[str, Any]:
    paths = ensure_dirs(cfg)
    since = resolve_lookback_since(cfg)
    product = (cfg.get("product_mode") or "weekly").lower()
    weekly_cfg = cfg.get("weekly") or {}
    # 周报默认：时间窗内全量入刊（采集本轮 + 库内窗口），不只「新增」
    include_window_all = bool(weekly_cfg.get("include_window_all", True))
    window_limit = int(weekly_cfg.get("window_item_limit") or cfg.get("replay_limit") or 300)
    logger.info("流水线开始 product=%s，回看自 %s，全量窗口=%s", product, since.isoformat(), include_window_all)

    collected: list[dict[str, Any]] = []
    collected.extend(collect_gov_sources(cfg))
    collected.extend(collect_wechat_sources(cfg, paths.get("inbox_dir")))
    collected.extend(collect_industry_sources(cfg))
    collected.extend(collect_legal_tool_sources(cfg))
    windowed = filter_by_window(collected, since)

    store_path = paths["store_file"]
    existing = read_jsonl(store_path)
    existing_ids = {row.get("id") for row in existing if row.get("id")}
    fresh = dedup(windowed, existing_ids)
    logger.info(
        "采集 %s → 窗口内 %s → 去重新增 %s（库内已有 %s）",
        len(collected),
        len(windowed),
        len(fresh),
        len(existing_ids),
    )

    mode = "new"
    reviewed_all: list[dict[str, Any]] = []
    fresh_reviewed: list[dict[str, Any]] = []

    if fresh:
        enriched = enrich_items(fresh, cfg)
        fresh_reviewed = apply_review(enriched, cfg)
        append_jsonl(store_path, fresh_reviewed)
    else:
        mode = "replay"

    # 时间窗内库内条目（含刚写入的新增）
    store_now = read_jsonl(store_path) if fresh else existing
    in_window_store = recent_from_store(store_now, since, limit=window_limit)

    if product == "weekly":
        # 周报：本轮窗口采集（已 enrich 的用 reviewed；未入库的 windowed 也补 enrich）+ 库内窗口
        # 目标：区间内各源信息尽量都进刊，而不是只展示「本轮新增」
        need_enrich = []
        known = {r.get("id"): r for r in fresh_reviewed}
        for row in windowed:
            iid = row.get("id")
            if not iid:
                continue
            if iid in known:
                continue
            if include_window_all:
                # 全量窗：已在库且字段齐全则直接用库内
                hit = next((x for x in in_window_store if x.get("id") == iid), None)
                if hit and hit.get("section"):
                    known[iid] = hit
                    continue
            # 仅本轮采集窗（如法务公众号预览）：强制再 enrich，避免库内旧分类把条目筛没
            need_enrich.append(row)
        if need_enrich:
            extra = enrich_items(need_enrich, cfg)
            extra = apply_review(extra, cfg)
            for r in extra:
                known[r.get("id")] = r
        # 全量窗口：再并入库内时间窗条目；否则只用本轮采集窗
        if include_window_all:
            for row in in_window_store:
                iid = row.get("id")
                if iid and iid not in known:
                    known[iid] = row
                elif iid and known.get(iid) and not known[iid].get("section") and row.get("section"):
                    known[iid] = row

        # 缺周报字段的补一轮
        need_patch = [r for r in known.values() if not r.get("section")]
        if need_patch:
            patched = {p["id"]: p for p in enrich_items(need_patch, cfg)}
            for iid, row in list(known.items()):
                if iid in patched:
                    known[iid] = {**row, **{k: v for k, v in patched[iid].items() if k != "review_status"}}

        reviewed_all = drop_stale_published(list(known.values()), since)
        curated = curate_items(reviewed_all, cfg)
        if not curated:
            curated = reviewed_all[: max(20, int(weekly_cfg.get("max_items") or 60))]
        curated = drop_stale_published(curated, since)
        reviewed = enrich_details(curated, cfg)
        logger.info(
            "周报窗口汇总：采集窗 %s + 库内窗 → 合计 %s → 入刊 %s（来源数 %s）",
            len(windowed),
            len(reviewed_all),
            len(reviewed),
            len({r.get("source") for r in reviewed}),
        )
        if mode == "replay" and fresh_reviewed:
            mode = "new"
        elif not fresh and include_window_all:
            mode = "window"
    else:
        # 日报：仍以新增为主；无新增则回顾
        if fresh_reviewed:
            reviewed_all = fresh_reviewed
            reviewed = fresh_reviewed
        else:
            replay = recent_from_store(existing, since, limit=int(cfg.get("replay_limit") or 40))
            reviewed_all = replay
            reviewed = replay
            mode = "replay"
            logger.info("无新增，生成回顾包 %s 条", len(replay))

    if flash_only:
        pool = reviewed_all or reviewed or recent_from_store(store_now, since, limit=window_limit)
        reviewed = enrich_details([i for i in pool if i.get("is_flash")], cfg)
        mode = "flash"

    run_at = now_cst()
    if product == "weekly":
        meta_rel = (cfg.get("paths") or {}).get("weekly_meta_file") or "data/weekly_meta.json"
        meta_path = project_root() / meta_rel
        if flash_only:
            vol = 0
            try:
                import json

                if meta_path.exists():
                    vol = int(json.loads(meta_path.read_text(encoding="utf-8")).get("last_vol") or 0)
            except Exception:
                vol = 0
        elif (cfg.get("weekly") or {}).get("test_issue"):
            # 测试期：不递增正式期号
            vol = 0
            try:
                import json

                if meta_path.exists():
                    vol = int(json.loads(meta_path.read_text(encoding="utf-8")).get("last_vol") or 0)
            except Exception:
                vol = 0
            logger.info("测试期周报：不递增期号，当前 last_vol=%s", vol)
        else:
            vol = next_weekly_vol(meta_path)
        digest = build_weekly_digest(reviewed, run_at, cfg, since, vol or 1)
        wcfg = cfg.get("weekly") or {}
        if wcfg.get("test_issue"):
            weekly = dict(digest.get("weekly") or {})
            weekly["test_issue"] = True
            weekly["issue_label"] = (wcfg.get("issue_label") or "测试期").strip() or "测试期"
            digest["weekly"] = weekly
        if flash_only:
            digest["title"] = f"重大监管快讯 {run_at.strftime('%Y-%m-%d %H:%M')}"
            digest["note"] = "临时快讯推送（不等周报）。满足重大监管动态判断标准的条目。"
        elif mode in ("replay", "window") and not fresh:
            digest["note"] = (
                f"本轮无新链接入库，已汇总时间窗内已有条目（自 {since.strftime('%Y-%m-%d %H:%M')}）。"
            )
    else:
        digest = build_digest(reviewed, run_at)
        digest["product_mode"] = "daily"
        if mode == "replay":
            digest["title"] = f"法规情报回顾 {run_at.strftime('%Y-%m-%d %H:%M')}（今日无新增）"
            digest["note"] = (
                "本轮没有发现新链接（可能都已入库）。"
                "这是回看窗口内已有内容的回顾包。"
            )

    digest["mode"] = mode
    if product == "weekly" and not flash_only:
        digest = aggregate_sections_with_llm(digest, cfg)
        digest = reorganize_sections_by_strategy(digest, cfg)
        digest = rewrite_legal_focus_for_digest(digest, cfg)
    digest = attach_ai_summary(digest, cfg)

    day = run_at.strftime("%Y%m%d_%H%M")
    prefix = "flash" if flash_only else ("weekly" if product == "weekly" else "digest")
    json_path = paths["digest_dir"] / f"{prefix}-{day}.json"
    md_path = paths["digest_dir"] / f"{prefix}-{day}.md"
    write_json(json_path, digest)
    md_text = digest_to_markdown(digest)
    # 周报/季度严格固定模版，备注不插入正文头部
    if digest.get("note") and product == "daily":
        md_text = f"> {digest['note']}\n\n" + md_text
    md_path.write_text(md_text, encoding="utf-8")

    brief_path = paths["digest_dir"] / f"briefing-{day}.md"
    ai = digest.get("ai_summary") or {}
    brief_body = (ai.get("briefing") or "（无总结）")
    if digest.get("note"):
        brief_body = f"> {digest['note']}\n\n" + brief_body
    brief_path.write_text(
        f"# {digest.get('title')}\n\n" + brief_body + "\n",
        encoding="utf-8",
    )

    html_path = None
    if product == "weekly":
        html_path = paths["digest_dir"] / f"{prefix}-{day}.html"
        html_body = digest_to_html(digest)
        html_path.write_text(html_body, encoding="utf-8")
        # 固定最新指针，避免打开到旧期/套话版本
        latest_html = paths["digest_dir"] / "weekly-latest.html"
        latest_html.write_text(html_body, encoding="utf-8")
        latest_json = paths["digest_dir"] / "weekly-latest.json"
        write_json(latest_json, digest)
        latest_md = paths["digest_dir"] / "weekly-latest.md"
        latest_md.write_text(digest_to_template_markdown(digest), encoding="utf-8")

    # 兼容面板：另存一份 digest-*.json 指针（最新周报也用 digest 前缀软链式复制）
    compat_json = paths["digest_dir"] / f"digest-{day}.json"
    if compat_json != json_path:
        write_json(compat_json, digest)
    compat_md = paths["digest_dir"] / f"digest-{day}.md"
    if compat_md != md_path:
        compat_md.write_text(md_text, encoding="utf-8")

    logger.info(
        "已生成%s（%s，总结=%s）：%s",
        "快讯" if flash_only else ("周报" if product == "weekly" else "日报"),
        mode,
        (ai.get("mode") or "none"),
        json_path,
    )

    digest["_paths"] = {
        "json": str(json_path),
        "md": str(md_path),
        "briefing": str(brief_path),
        "html": str(html_path) if html_path else "",
        "compat_json": str(compat_json),
    }
    digest["_stats"] = {
        "collected": len(collected),
        "windowed": len(windowed),
        "fresh": len(fresh),
        "store": len(existing_ids),
        "in_digest": len(reviewed),
        "sources_in_digest": len({r.get("source") for r in reviewed if r.get("source")}),
        "mode": mode,
        "product_mode": product,
        "summary_mode": ai.get("mode"),
        "flash_only": flash_only,
    }
    return digest
