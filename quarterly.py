# -*- coding: utf-8 -*-
"""季度合集：汇总近一季度周报，提炼趋势与两院应对建议。"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from report_html import digest_to_html, digest_to_template_markdown, format_positioning
from summarize import _call_openai_compatible, _llm_endpoints
from utils import now_cst, project_root, write_json

logger = logging.getLogger(__name__)


def _load_weekly_digests(digest_dir: Path, months: int = 3) -> list[dict[str, Any]]:
    since = now_cst() - timedelta(days=int(months * 31))
    files = sorted(digest_dir.glob("weekly-*.json")) + sorted(digest_dir.glob("digest-*.json"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (data.get("product_mode") or "") not in ("weekly", "") and "法律AI每周资讯" not in str(data.get("title") or ""):
            # 仍允许 digest 兼容文件
            if not data.get("sections"):
                continue
        gen = data.get("generated_at") or ""
        try:
            from datetime import datetime
            from utils import CST

            dt = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            if dt < since:
                continue
        except Exception:
            pass
        key = data.get("title") or path.name
        if key in seen:
            continue
        seen.add(key)
        data["_file"] = path.name
        out.append(data)
    out.sort(key=lambda d: d.get("generated_at") or "")
    return out


def _collect_items(digests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in digests:
        for it in d.get("items") or []:
            iid = it.get("id") or it.get("url") or it.get("title")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            items.append(it)
        for sec_items in (d.get("sections") or {}).values():
            for it in sec_items or []:
                iid = it.get("id") or it.get("url") or it.get("title")
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                items.append(it)
    return items


def _rule_quarterly(items: list[dict[str, Any]], digests: list[dict[str, Any]]) -> dict[str, Any]:
    tag_c: Counter[str] = Counter()
    scene_c: Counter[str] = Counter()
    dir_c: Counter[str] = Counter()
    for it in items:
        for t in it.get("tags") or []:
            tag_c[t] += 1
        for s in it.get("impact_scenes") or []:
            scene_c[s] += 1
        for d in it.get("directions") or []:
            dir_c[d] += 1

    highlights = []
    for it in items:
        if it.get("is_flash") or it.get("importance") == "high":
            highlights.append(it.get("title") or "")
        if len(highlights) >= 10:
            break

    parts = [
        f"本季度共回溯 {len(digests)} 期周报，去重后 {len(items)} 条精选动态。",
        "",
        "【季度趋势】",
        "- 高频标签：" + "、".join(f"{t}({n})" for t, n in tag_c.most_common(6)),
        "- 高频影响场景：" + "、".join(f"#{s}({n})" for s, n in scene_c.most_common(6)),
        "- 选题方向：" + "、".join(f"{t}({n})" for t, n in dir_c.most_common(6)),
        "",
        "【要点回顾】",
    ]
    for h in highlights:
        parts.append(f"- {h}")
    parts.extend(
        [
            "",
            "【两院应对建议（规则草案）】",
            "1. 对照高频影响场景，更新内部 AI/数据合规检查清单。",
            "2. 将反复出现的监管主题纳入法务例会固定议题。",
            "3. 对涉及算法备案、数据跨境、科研合作的在推项目做专项复核。",
            "4. 保留本季度 HTML/MD 作为向领导汇报的附件素材。",
        ]
    )
    return {
        "mode": "rule",
        "briefing": "\n".join(parts),
        "judgment_clue": "季度维度上看，监管与场景压力正从「单点政策」转向「项目全流程嵌入」。",
        "mainline": "建议以高频场景为轴，形成可汇报的趋势判断与行动清单。",
        "trends": [{"tag": t, "count": n} for t, n in tag_c.most_common(8)],
        "scenes": [{"scene": s, "count": n} for s, n in scene_c.most_common(8)],
    }


def _llm_quarterly(items: list[dict[str, Any]], digests: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        return None
    payload = {
        "issues": [{"title": d.get("title"), "mainline": (d.get("weekly") or {}).get("mainline")} for d in digests[-12:]],
        "items": [
            {
                "title": i.get("title"),
                "section": i.get("section"),
                "impact_scenes": i.get("impact_scenes"),
                "tags": i.get("tags"),
                "is_flash": i.get("is_flash"),
            }
            for i in items[:60]
        ],
    }
    system = (
        "你是两院法务助理，撰写「法律AI资讯季度合集」。要求：\n"
        "1) 提炼 3～5 条季度趋势（看见趋势也看见风险）\n"
        "2) 给出面向领导的两院应对建议（可讨论、可落地，不作最终法律意见）\n"
        "3) 点名高频影响场景\n"
        "输出中文 Markdown。末尾两行：JUDGMENT_CLUE: … 与 MAINLINE: …"
    )
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)
    for ep in endpoints:
        try:
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                timeout=timeout,
            )
            judgment = ""
            mainline = ""
            m1 = re.search(r"JUDGMENT_CLUE:\s*(.+)", text)
            m2 = re.search(r"MAINLINE:\s*(.+)", text)
            if m1:
                judgment = m1.group(1).strip()
            if m2:
                mainline = m2.group(1).strip()
            body = re.sub(r"\n?JUDGMENT_CLUE:.*", "", text)
            body = re.sub(r"\n?MAINLINE:.*", "", body).strip()
            return {
                "mode": "llm",
                "provider": ep["name"],
                "model": ep["model"],
                "briefing": body,
                "judgment_clue": judgment,
                "mainline": mainline,
            }
        except Exception as e:
            logger.warning("季度 LLM 失败 %s：%s", ep["name"], e)
    return None


def build_quarterly(cfg: dict[str, Any]) -> dict[str, Any]:
    paths = cfg.get("paths") or {}
    digest_dir = project_root() / (paths.get("digest_dir") or "data/digests")
    digests = _load_weekly_digests(digest_dir, months=int((cfg.get("quarterly") or {}).get("months") or 3))
    items = _collect_items(digests)
    run_at = now_cst()

    summary = _llm_quarterly(items, digests, cfg) or _rule_quarterly(items, digests)
    # 取高相关条目作合集正文（最多 30）
    show = sorted(
        items,
        key=lambda x: (0 if x.get("is_flash") else 1, x.get("importance") != "high", -int(x.get("relevance_score") or 0)),
    )[:30]

    sections = {"global_ai": [], "legal_ai": [], "two_institute": []}
    for it in show:
        sec = it.get("section") or "two_institute"
        if sec not in sections:
            sec = "two_institute"
        sections[sec].append(it)

    brand = ((cfg.get("weekly") or {}).get("brand") or "法律AI每周资讯") + "·季度合集"
    audience = (cfg.get("weekly") or {}).get("audience") or ""
    clue = summary.get("judgment_clue") or "季度趋势回顾"
    digest = {
        "generated_at": run_at.isoformat(),
        "product_mode": "quarterly",
        "title": f"{brand} {run_at.strftime('%Y')}Q{(run_at.month - 1)//3 + 1}",
        "counts": {
            "approved": len(show),
            "pending": 0,
            "rejected": 0,
            "total_in_batch": len(items),
            "issues": len(digests),
        },
        "items": show,
        "pending_items": [],
        "sections": sections,
        "flash_items": [i for i in show if i.get("is_flash")],
        "weekly": {
            "brand": brand,
            "vol": f"Q{(run_at.month - 1)//3 + 1}",
            "date_range": f"近{(cfg.get('quarterly') or {}).get('months') or 3}个月",
            "audience": audience,
            "positioning": format_positioning(audience or "面向两院法务和管理层，按照两院适配行业、单位性质提供前沿法律咨询", clue),
            "judgment_clue": clue,
            "mainline": summary.get("mainline") or "",
        },
        "ai_summary": summary,
        "mode": "quarterly",
        "source_issues": [{"title": d.get("title"), "file": d.get("_file")} for d in digests],
    }

    day = run_at.strftime("%Y%m%d_%H%M")
    json_path = digest_dir / f"quarterly-{day}.json"
    md_path = digest_dir / f"quarterly-{day}.md"
    html_path = digest_dir / f"quarterly-{day}.html"
    write_json(json_path, digest)
    md_path.write_text(digest_to_template_markdown(digest), encoding="utf-8")
    html_path.write_text(digest_to_html(digest), encoding="utf-8")
    # 兼容面板
    write_json(digest_dir / f"digest-{day}.json", digest)

    digest["_paths"] = {"json": str(json_path), "md": str(md_path), "html": str(html_path), "briefing": str(md_path)}
    digest["_stats"] = {"issues": len(digests), "items": len(items), "summary_mode": summary.get("mode")}
    logger.info("季度合集已生成：%s（回溯 %s 期）", json_path, len(digests))
    return digest
