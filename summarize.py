# -*- coding: utf-8 -*-
"""对采集结果做整理总结：有 LLM 则调用；无密钥则用规则生成可读简报。"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from typing import Any

from utils import get_env_key, pick_best_published

logger = logging.getLogger(__name__)

# 收尾栏统一字段名（对外展示「法务部参考建议」，非「工作要点」）
WEEK_LEGAL_REFERENCE_LABEL = "法务部参考建议"

# 两院法务部职责（关注点/建议一律对齐此边界，避免写成业务部门口吻）
LEGAL_DEPT_DUTIES = (
    "人工智能全链条法律监管跟进；数据合规与个人信息保护中的法律判断协同；"
    "科研项目合规（横纵向、科技伦理、人遗、科研经费）；合同全生命周期管理；"
    "全品类用工合规；学生管理与未成年人保护；产业孵化与投资合规；院企合作与重大项目；"
    "国际学术与交流合规；基金会与公益合规；事业单位/民非监管合规；"
    "争议解决与风险事件应对；合规体系建设与业务赋能。"
    "（数据安全主责、知识产权管理主责不在法务，但合同与法律判断须把关。）"
)

LEGAL_DUTY_LENSES = (
    "AI/数据/算法监管与责任边界",
    "合同全周期与制度合规审核",
    "科研/人遗/科技伦理与成果转化相关法律把关",
    "学生与未成年人保护、用工与外聘合规",
    "争议解决、风险提示与合规体系建设",
)

# 对外文案语气：法务情报观察，不写危言耸听
TONE_RULE = (
    "文风要求：克制、专业、可讨论；像法务例会备忘，不要营销稿或危机通告。"
    "禁止：倒逼、重构、穿透化、黑箱化、深度博弈、责任对赌、阻断、强制嵌入、亟需、严峻、高压、"
    "常态化追责等夸张词。"
    "宜用：提示关注、建议对照、可考虑修订、纳入审查清单、便于跨部门会签、完善条款与边界。"
)


def soften_alarmist_zh(text: str) -> str:
    """把过激表述替换为更平实的法务用语（保留原意）。"""
    s = str(text or "")
    replacements = [
        (r"直接倒逼", "提示"),
        (r"倒逼", "提示"),
        (r"强制嵌入", "建议写入"),
        (r"前置阻断", "有助于减少"),
        (r"阻断", "减少"),
        (r"黑箱化", "不透明"),
        (r"责任对赌的深度博弈", "责任与权属条款的重点谈判"),
        (r"深度博弈", "重点谈判"),
        (r"责任对赌", "责任划分约定"),
        (r"算法责任穿透化", "算法责任约定趋细"),
        (r"个人追责常态化", "个人责任约定需更谨慎"),
        (r"数据合规前置化", "数据合规宜更早纳入审查"),
        (r"重构合规边界与风险隔离机制", "梳理并完善相关合同与制度边界"),
        (r"重构", "完善"),
        (r"亟需", "宜及时"),
        (r"严峻", "需关注"),
        (r"高压", "趋严"),
        (r"风险隔离机制", "风险边界安排"),
        (r"技术黑箱", "服务不透明条款"),
    ]
    for pat, rep in replacements:
        s = re.sub(pat, rep, s)
    return s.strip()


def legal_duty_text(cfg: dict[str, Any] | None = None) -> str:
    """优先读配置 weekly.legal_duty，否则用内置职责表述。"""
    if cfg:
        custom = ((cfg.get("weekly") or {}).get("legal_duty") or "").strip()
        if custom:
            return custom
    return LEGAL_DEPT_DUTIES


def legal_duty_prompt_block(cfg: dict[str, Any] | None = None) -> str:
    """写入各 LLM system/user 的职责约束块。"""
    duty = legal_duty_text(cfg)
    lenses = "；".join(LEGAL_DUTY_LENSES)
    return (
        f"两院法务部职责：{duty}\n"
        f"写法务关注点/思考问题/行动建议时，必须落到上述职责之一：{lenses}。"
        "禁止写成业务部门如何做科研/如何做产品的口吻；"
        "应写成法务如何把关、审合同/制度、划边界、协同内控、防纠纷。\n"
        f"{TONE_RULE}"
    )


def _items_for_brief(digest: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(digest.get("items") or [])
    pending = list(digest.get("pending_items") or [])
    # 总结时把待审也纳入「今日看到什么」，但标注待审
    return items + pending


def rule_based_briefing(digest: dict[str, Any], limit: int = 12) -> dict[str, Any]:
    """无 API 时的规则整理：按来源/标签归类 + 要点列表。"""
    items = _items_for_brief(digest)
    by_source: dict[str, list[str]] = defaultdict(list)
    tag_counter: Counter[str] = Counter()
    highlights: list[str] = []
    by_section: dict[str, int] = Counter()

    for it in items:
        src = it.get("source") or "未知来源"
        title = (it.get("title") or "").strip()
        if not title:
            continue
        by_source[src].append(title)
        for t in it.get("tags") or []:
            tag_counter[t] += 1
        sec = it.get("section") or "two_institute"
        by_section[sec] += 1
        if it.get("importance") == "high" or len(highlights) < 5:
            flag = "【待审】" if it.get("review_status") == "pending" else ""
            flash = "【快讯】" if it.get("is_flash") else ""
            highlights.append(f"{flash}{flag}{title}")

    product = digest.get("product_mode") or "weekly"
    # 规则兜底：对齐法务职责（合同/制度审核、风控边界、跨部门把关）
    top_titles = [h for h in highlights[:5] if h]
    top_scenes = [t for t, _ in tag_counter.most_common(3) if t and t != "未分类"]
    scene_txt = "、".join(top_scenes) if top_scenes else "科研合作、AI采购、数据合规"
    title_hint = "；".join(top_titles[:3]) if top_titles else "本期精选动态"
    week_think = (
        f"围绕「{title_hint}」，法务部应优先判断：哪些变化会在一个月内传导到"
        f"「{scene_txt}」相关的合同条款、制度审核节点或跨部门合规把关边界；"
        f"建议本周牵头对照本期原文梳理「{scene_txt}」场景的制度/合同缺口，"
        f"输出需修订的条款清单与跨部门会签把关要点，并指定争议风险跟踪人。"
    )
    week_action = ""

    if product == "weekly":
        weekly = digest.get("weekly") or {}
        parts = [
            f"本期共整理 {len(items)} 条（可推送 {digest.get('counts', {}).get('approved', 0)}，"
            f"待审 {digest.get('counts', {}).get('pending', 0)}）。",
            "",
            "【判断线索】" + (weekly.get("judgment_clue") or "关注 AI/数据监管变化对两院管理场景的传导。"),
            "",
            "【三大板块分布】",
            f"- 两院法务：{by_section.get('two_institute', 0)}（建议占比≥50%）",
            f"- 法律AI/合规实务：{by_section.get('legal_ai', 0)}",
            f"- 全球AI治理与产业动态：{by_section.get('global_ai', 0)}",
            "",
            "【来源分布】",
        ]
    else:
        parts = [
            f"本轮共整理 {len(items)} 条（可推送 {digest.get('counts', {}).get('approved', 0)}，"
            f"待审 {digest.get('counts', {}).get('pending', 0)}）。",
            "",
            "【来源分布】",
        ]
    for src, titles in by_source.items():
        parts.append(f"- {src}：{len(titles)} 条")

    if tag_counter:
        parts.append("")
        parts.append("【主题标签】")
        for tag, n in tag_counter.most_common(8):
            parts.append(f"- {tag}（{n}）")

    parts.append("")
    parts.append("【要点速览】")
    for h in highlights[:limit]:
        parts.append(f"- {h}")

    parts.append("")
    parts.append("（当前为规则整理。配置兼容 API 后可升级为 AI 综述。）")

    return {
        "mode": "rule",
        "briefing": "\n".join(parts),
        "highlights": highlights[:limit],
        "topics": [{"tag": t, "count": n} for t, n in tag_counter.most_common(8)],
        "judgment_clue": (digest.get("weekly") or {}).get("judgment_clue") or "",
        "mainline": (digest.get("weekly") or {}).get("mainline") or "",
        "week_think_question": week_think,
        "week_action_suggestion": week_action,
        "week_legal_reference": week_think,
    }


def _call_openai_compatible(
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: int = 60,
) -> str:
    import requests

    url = api_base.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


DEFAULT_ZGC_API_BASE = "https://llm.zgci.org/hub/v1"


def _llm_endpoints(cfg: dict[str, Any]) -> list[dict[str, str]]:
    """按优先级返回可用的 OpenAI 兼容端点。

    优先：ZGC Hub（https://llm.zgci.org/hub/v1 + 环境变量 ZGC_KEY，model=qwen）
    回退：DASHSCOPE_API_KEY → 通义 compatible-mode
    """
    llm = (cfg.get("enrich") or {}).get("llm") or {}
    endpoints: list[dict[str, str]] = []

    zgc_base = (
        (llm.get("api_base") or "").strip()
        or get_env_key("ZGC_API_BASE")
        or DEFAULT_ZGC_API_BASE
    )
    zgc_key = (llm.get("api_key") or "").strip() or get_env_key(llm.get("api_key_env") or "ZGC_KEY")
    zgc_model = (llm.get("model") or "").strip() or get_env_key("ZGC_MODEL") or "qwen"
    if zgc_key:
        endpoints.append({
            "name": "zgc",
            "api_base": zgc_base.rstrip("/"),
            "api_key": zgc_key,
            "model": zgc_model,
        })

    # 通义兜底
    dash_key = get_env_key("DASHSCOPE_API_KEY")
    if dash_key:
        endpoints.append({
            "name": "dashscope",
            "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": dash_key,
            "model": get_env_key("ZGC_FALLBACK_MODEL") or "qwen-plus",
        })

    return endpoints


def llm_briefing(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        logger.info("未找到可用 LLM 端点（需环境变量 ZGC_KEY，或 DASHSCOPE_API_KEY）")
        return None

    items = _items_for_brief(digest)[:40]
    payload = [
        {
            "title": i.get("title"),
            "source": i.get("source"),
            "tags": i.get("tags"),
            "importance": i.get("importance"),
            "url": i.get("url"),
            "review_status": i.get("review_status"),
            "section": i.get("section"),
            "impact_scenes": i.get("impact_scenes"),
            "key_info": (i.get("key_info") or i.get("summary") or "")[:180],
            "legal_focus": i.get("legal_focus"),
            "is_flash": i.get("is_flash"),
        }
        for i in items
    ]

    product = (cfg.get("product_mode") or digest.get("product_mode") or "weekly").lower()
    duty_block = legal_duty_prompt_block(cfg)
    if product == "weekly":
        system = (
            "你是中关村学院与中关村人工智能研究院（两院）法务部情报助理，撰写「法律AI每周资讯」综述。\n"
            f"{duty_block}\n"
            "周报强调筛选、判断和转化，不追求罗列。要求：\n"
            "1) 先用 1 句话给出「本周判断线索」（趋势+对法务合同/制度边界的含义；语气克制）\n"
            "2) 再用 1 句写「本期主线」（资讯如何落到合同审核、制度把关；勿夸张；与线索合计不超过两句引导）\n"
            "3) 按三大板块简述要点：两院法务 → 法律AI/合规实务 → 全球AI治理"
            "（两院法务是重头，篇幅应明显更多；聚焦法律判断与可转化动作，不写产业热闹）\n"
            "4) 「法务部参考建议」写成 3～5 条短建议（每条一行、可执行），"
            "必须点名本期具体标题/文件/采购场景，写清法务本周能动手做的核对/补条款动作；"
            "禁止假大空套话（如便于会签、全周期清单、赋能闭环）；"
            "禁止业务侧「怎么做科研/怎么做产品」式建议，禁止标题写成「工作要点」\n"
            "5) 不要编造法条编号、生效日期；不要给出最终法律意见\n"
            f"{TONE_RULE}\n"
            "输出纯中文 Markdown。文末单独输出：\n"
            "JUDGMENT_CLUE: …\n"
            "MAINLINE: …\n"
            "WEEK_REFERENCE:\n"
            "- …\n"
            "- …\n"
        )
    else:
        system = (
            "你是法务情报助理。根据输入的法规/政策条目列表，写一份给法务同事看的中文日更简报。"
            "要求：\n"
            "1) 先给 3～6 条「今日必看」要点（每条一句话，不要编造原文没有的信息）\n"
            "2) 再按主题分类简述（立法/行政/司法/其他）\n"
            "3) 标出需要人审或可能影响本司业务的条目（若无法判断则写「需承办人自行判断」）\n"
            "4) 不要编造法条编号、生效日期；没有的信息写「未知」\n"
            "5) 不要给出最终法律意见\n"
            "输出纯中文 Markdown，不要包代码块。"
        )
    user = "条目 JSON 如下：\n" + json.dumps(payload, ensure_ascii=False)
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)

    last_err: Exception | None = None
    for ep in endpoints:
        try:
            logger.info("尝试 LLM 总结：%s / %s", ep["name"], ep["model"])
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=timeout,
            )
            highlights = []
            for line in text.splitlines():
                s = line.strip()
                if s.startswith(("-", "*", "•")) or re.match(r"^\d+[\.、]", s):
                    highlights.append(re.sub(r"^[\d\.\-\*\•、\s]+", "", s)[:80])
                if len(highlights) >= 8:
                    break
            text = text.strip()
            judgment = ""
            mainline = ""
            week_think = ""
            week_action = ""
            week_reference = ""
            m1 = re.search(r"JUDGMENT_CLUE:\s*(.+)", text)
            m2 = re.search(r"MAINLINE:\s*(.+)", text)
            m3 = re.search(r"WEEK_REFERENCE:\s*([\s\S]+?)(?=\n[A-Z_]+:|\Z)", text)
            m3b = re.search(r"WEEK_THINK:\s*(.+)", text)
            m4b = re.search(r"WEEK_ACTION:\s*(.+)", text)
            week_items: list[str] = []
            if m1:
                judgment = m1.group(1).strip()
            if m2:
                mainline = m2.group(1).strip()
            if m3:
                week_reference = m3.group(1).strip()
                week_items = normalize_week_reference_items(week_reference)
                if week_items:
                    week_reference = "\n".join(week_items)
            elif m3b or m4b:
                week_think = (m3b.group(1).strip() if m3b else "")
                week_action = (m4b.group(1).strip() if m4b else "")
                week_reference = build_week_legal_reference(
                    question=week_think, action=week_action
                )
            briefing_body = re.sub(r"\n?JUDGMENT_CLUE:.*", "", text)
            briefing_body = re.sub(r"\n?MAINLINE:.*", "", briefing_body)
            briefing_body = re.sub(r"\n?WEEK_REFERENCE:[\s\S]*", "", briefing_body)
            briefing_body = re.sub(r"\n?WEEK_THINK:.*", "", briefing_body)
            briefing_body = re.sub(r"\n?WEEK_ACTION:.*", "", briefing_body).strip()
            return {
                "mode": "llm",
                "provider": ep["name"],
                "model": ep["model"],
                "briefing": briefing_body,
                "highlights": highlights,
                "topics": [],
                "judgment_clue": judgment,
                "mainline": mainline,
                "week_legal_reference": week_reference,
                "week_legal_reference_items": week_items,
                "week_think_question": week_think or week_reference,
                "week_action_suggestion": week_action,
            }
        except Exception as e:
            last_err = e
            logger.warning("LLM 端点失败 %s：%s", ep["name"], e)

    if last_err:
        logger.exception("全部 LLM 端点失败：%s", last_err)
    return None


_GENERIC_WEEK_MARKERS = (
    "本期哪些变化可能在一个月内转化为",
    "围绕本期主线开展内部讨论",
    "列入本周法务例会观察清单",
    "该动态是否触发两院在",
    "需承办人判断是否与两院",
    "本期本板块暂无",
)


def _is_generic_week_text(text: str) -> bool:
    s = (text or "").strip()
    if not s or s in ("—", "-", "待填写"):
        return True
    return any(m in s for m in _GENERIC_WEEK_MARKERS)


def build_week_legal_reference(
    *,
    reference: str = "",
    question: str = "",
    action: str = "",
) -> str:
    """合并/提取本期法务部参考建议（一条，对齐法务职责边界）。"""
    ref = re.sub(r"【[^】]*】", "", str(reference or "")).strip()
    if ref and not _is_generic_week_text(ref):
        return ref[:600]
    q = re.sub(r"【[^】]*】", "", str(question or "")).strip()
    a = re.sub(r"【[^】]*】", "", str(action or "")).strip()
    if q and a:
        q = q.rstrip("？?").rstrip("；;")
        if a.startswith(("，", "；", ";", "。")):
            return f"{q}{a}"[:600]
        return f"{q}；{a}"[:600]
    return (q or a or "")[:600]


def normalize_week_reference_items(value: Any, *, limit: int = 5) -> list[Any]:
    """把 LLM/配置里的参考建议规范成列表（字符串或含 tip/keyword/related_title 的对象）。"""
    items: list[Any] = []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        bullet_lines = [
            re.sub(r"^[\-\*\u2022•\d\.、\s]+", "", ln).strip()
            for ln in lines
            if ln.lstrip().startswith(("-", "*", "•")) or re.match(r"^\d+[\.、]", ln)
        ]
        if bullet_lines:
            raw = bullet_lines
        else:
            raw = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    else:
        raw = []
    for x in raw:
        if isinstance(x, dict):
            tip = soften_alarmist_zh(
                re.sub(r"【[^】]*】", "", str(x.get("tip") or x.get("text") or x.get("action") or "")).strip()
            )
            if not tip or _is_generic_week_text(tip):
                continue
            if tip[-1] not in "。！？!?":
                tip += "。"
            row = {
                "tip": tip[:120],
                "keyword": str(x.get("keyword") or "").strip()[:12],
                "related_title": str(
                    x.get("related_title") or x.get("source_title") or x.get("title") or ""
                ).strip()[:80],
            }
            items.append(row)
            if len(items) >= limit:
                break
            continue
        s = soften_alarmist_zh(re.sub(r"【[^】]*】", "", str(x or "")).strip())
        if not s or _is_generic_week_text(s):
            continue
        if s[-1] not in "。！？!?":
            s += "。"
        if s not in items:
            items.append(s[:120])
        if len(items) >= limit:
            break
    return items


def _week_qa_payload(digest: dict[str, Any], limit: int = 28) -> list[dict[str, Any]]:
    """抽取本期可讨论条目，供收尾问答专用调用。"""
    sections = digest.get("sections") or {}
    order = ("two_institute", "legal_ai", "global_ai")
    rows: list[dict[str, Any]] = []
    for key in order:
        for it in sections.get(key) or []:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            rows.append({
                "section": key,
                "title": title,
                "source": it.get("source") or "",
                "key_info": (it.get("key_info") or it.get("summary") or "")[:160],
                "legal_focus": (it.get("legal_focus") or "")[:120],
                "impact_scenes": it.get("impact_scenes") or [],
                "importance": it.get("importance") or "",
            })
            if len(rows) >= limit:
                return rows
    if not rows:
        for it in _items_for_brief(digest)[:limit]:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            rows.append({
                "section": it.get("section") or "",
                "title": title,
                "source": it.get("source") or "",
                "key_info": (it.get("key_info") or it.get("summary") or "")[:160],
                "legal_focus": (it.get("legal_focus") or "")[:120],
                "impact_scenes": it.get("impact_scenes") or [],
                "importance": it.get("importance") or "",
            })
    return rows


def llm_week_qa(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, str] | None:
    """单独调用 LLM，生成本期「法务部参考建议」（一条，扣住具体条目）。"""
    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        return None
    rows = _week_qa_payload(digest)
    if not rows:
        return None

    weekly = digest.get("weekly") or {}
    clue = weekly.get("judgment_clue") or (digest.get("ai_summary") or {}).get("judgment_clue") or ""
    mainline = weekly.get("mainline") or (digest.get("ai_summary") or {}).get("mainline") or ""

    system = (
        "你是中关村学院与中关村人工智能研究院（两院）法务部顾问。\n"
        f"{legal_duty_prompt_block(cfg)}\n"
        "请围绕三个问题思考后再作答："
        "①哪些变化真正以法律方式影响两院；"
        "②落到哪些具体合规动作（审合同/改制度/发提示/做培训）；"
        "③本周应主动推进什么（具体到合同模板条款或向某部门发风险提示）。\n"
        "只根据给定的本期周报条目，输出 JSON 对象，字段：\n"
        "week_legal_reference_items：对象数组，3～5 条；每项字段："
        "tip(短建议正文，必须可执行)、keyword(一个法律专业关键词)、"
        "related_title(必须是本期条目标题原文或明显截取，禁止虚构)；"
        "语气现实、克制；禁止假大空套话（便于会签、赋能、闭环、持续关注等）；"
        "禁止写成业务部门如何开展科研/产品。\n"
        "week_legal_reference：可选，把 tip 用换行拼成一段，便于兼容旧字段。\n"
        "不要编造法条编号。只输出 JSON，不要 Markdown。"
    )
    user = json.dumps(
        {
            "judgment_clue": clue,
            "mainline": mainline,
            "items": rows,
        },
        ensure_ascii=False,
    )
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)

    last_err: Exception | None = None
    for ep in endpoints:
        try:
            logger.info("尝试 LLM 周报收尾问答：%s / %s（%s 条）", ep["name"], ep["model"], len(rows))
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=timeout,
            )
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                last_err = ValueError("未解析到 JSON 对象")
                continue
            obj = json.loads(m.group(0))
            items = normalize_week_reference_items(
                obj.get("week_legal_reference_items")
                or obj.get("week_reference_items")
                or obj.get("week_legal_reference")
                or obj.get("week_reference")
                or ""
            )
            if not items:
                q = str(obj.get("week_think_question") or "").strip()
                a = str(obj.get("week_action_suggestion") or "").strip()
                ref = build_week_legal_reference(question=q, action=a)
                items = normalize_week_reference_items(ref)
            if not items or all(
                _is_generic_week_text(x.get("tip") if isinstance(x, dict) else x)
                for x in items
            ):
                last_err = ValueError("模型仍输出空泛套话")
                logger.warning("LLM 收尾参考建议过于空泛，换端点重试")
                continue
            joined = "\n".join(
                (x.get("tip") if isinstance(x, dict) else str(x)) for x in items
            )
            return {
                "week_legal_reference": joined[:600],
                "week_legal_reference_items": items,
                "week_think_question": joined[:400],
                "week_action_suggestion": "",
                "provider": ep["name"],
                "model": ep["model"],
            }
        except Exception as e:
            last_err = e
            logger.warning("LLM 收尾问答失败 %s：%s", ep["name"], e)

    if last_err:
        logger.warning("周报收尾问答全部失败：%s", last_err)
    return None


SECTION_LABELS_CN = {
    "global_ai": "全球AI治理与产业动态",
    "legal_ai": "法律AI/合规实务",
    "two_institute": "两院法务",
}


def _rule_aggregate_section(
    items: list[dict[str, Any]],
    section_key: str,
    max_clusters: int = 10,
) -> list[dict[str, Any]]:
    """无 LLM 时：按影响场景/标签粗聚合，标题改为「主题 + 要点」而非原文粘贴。"""
    if not items:
        return []
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        scenes = it.get("impact_scenes") or []
        tags = [t for t in (it.get("tags") or []) if t and t != "未分类"]
        key = str(scenes[0] if scenes else (tags[0] if tags else "综合动态"))
        buckets[key].append(it)

    out: list[dict[str, Any]] = []
    for theme, group in list(buckets.items())[:max_clusters]:
        group = sorted(
            group,
            key=lambda x: (0 if x.get("importance") == "high" else 1, x.get("title") or ""),
        )
        primary = group[0]
        titles = [str(g.get("title") or "").strip() for g in group if g.get("title")]
        sources = sorted({str(g.get("source") or "").strip() for g in group if g.get("source")})
        urls = [
            {
                "title": str(g.get("title") or "")[:60],
                "url": g.get("url") or "",
                "published_at": g.get("published_at") or g.get("published_date") or "",
                "published_date": g.get("published_date") or "",
            }
            for g in group
            if g.get("url")
        ][:6]
        key_bits = []
        for g in group[:4]:
            bit = (g.get("key_info") or g.get("summary") or "").strip()
            bit = re.sub(r"【[^】]*】", "", bit).strip()
            gtitle = re.sub(r"【[^】]*】", "", str(g.get("title") or "")).strip()
            # 禁止用标题/导航文案冒充关键信息
            if not bit or bit == gtitle:
                continue
            if bit.startswith(("垂类工具", "本期观察「", "来自 ")) or bit.count("｜") >= 2:
                continue
            if len(bit) < 18:
                continue
            key_bits.append(bit[:120])
        refined_title = f"{theme}：本期{len(group)}条相关动态要点"
        if len(group) == 1 and titles:
            # 单条也改写为提炼句，避免直接粘贴长标题
            t0 = re.sub(r"【[^】]*】", "", titles[0]).strip()
            refined_title = f"{theme}观察｜{t0[:36]}" if len(t0) > 36 else f"{theme}观察｜{t0}"
        legal_parts = [
            re.sub(r"【[^】]*】", "", str(g.get("legal_focus") or "")).strip()
            for g in group
            if (g.get("legal_focus") or "").strip()
        ]
        legal_focus = legal_parts[0] if legal_parts else ""
        row = dict(primary)
        row["id"] = f"agg-{section_key}-{make_agg_id(theme, len(group))}"
        row["title"] = refined_title
        row["original_titles"] = titles[:8]
        if key_bits:
            row["key_info"] = "；".join(key_bits)[:480]
        elif legal_focus:
            row["key_info"] = (
                f"本期围绕「{theme}」归拢{len(group)}条相关动态；"
                f"公开材料要点见法务关注点，不宜只看标题。"
            )[:480]
        else:
            row["key_info"] = (
                f"本期「{theme}」相关动态共{len(group)}条，"
                "需点开原文核对事实，避免只看标题。"
            )[:480]
        row["summary"] = row["key_info"][:160]
        row["sources_list"] = sources[:8]
        row["source"] = "、".join(sources[:4]) if sources else (primary.get("source") or "")
        if urls:
            row["url"] = urls[0].get("url") or primary.get("url") or ""
            extra = "；".join(f"{u['title']}" for u in urls[1:3] if u.get("title"))
            if extra:
                row["extended_source"] = (row.get("extended_source") or "") or f"同类原文：{extra}"
        if legal_focus:
            row["legal_focus"] = legal_focus[:280]
        # 聚合卡时间戳取成员中最新的原文发布日
        pub_iso, pub_day = pick_best_published(group)
        row["published_at"] = pub_iso
        row["published_date"] = pub_day
        row["date_source"] = "original" if pub_day else "missing"
        row["aggregated"] = True
        row["aggregate_count"] = len(group)
        row["member_ids"] = [g.get("id") for g in group if g.get("id")]
        row["source_urls"] = urls
        row["section"] = section_key
        out.append(row)
    return out


def make_agg_id(theme: str, n: int) -> str:
    import hashlib

    raw = f"{theme}|{n}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:10]


# 垂类法律工具 → 主题簇（与其他板块一样做提炼汇总，避免逐产品罗列）
_LEGAL_TOOL_THEMES: list[tuple[str, tuple[str, ...], dict[str, Any]]] = [
    (
        "合同起草与智能审查",
        ("合同", "合同库", "mylegalai", "法天使"),
        {
            "title": "合同审查类法律AI选型需前置数据留存、提示词泄露与输出责任划分审查",
            "key_info": (
                "本期归拢合同审查/起草类法律AI公开入口，可见智能审查、起草、对比、"
                "信息提取等能力介绍；多为产品功能说明，不能直接当作采购与责任条款，"
                "选型时需另行核对数据留存、提示词外泄与输出责任划分。"
            ),
            "legal_focus": (
                "合同审查/起草类工具直接触及两院合同全周期管理。法务部在采购与试用阶段应"
                "审查数据留存范围、提示词与合同文本外泄风险、AI输出错误的责任划分及开源"
                "组件许可，并将场景适用边界写入采购合同与内部使用制度。"
            ),
            "impact_scenes": ["AI系统采购", "合同全周期管理", "内部合规"],
            "tags": ["法律AI", "合同审查", "垂类工具"],
        },
    ),
    (
        "检索办案与律师工具",
        ("检索", "api", "办案", "律师", "元典", "智合", "alpha", "aipha"),
        {
            "title": "检索办案类法律科技接入需明确数据授权、幻觉风险与意见输出责任边界",
            "key_info": (
                "本期归拢检索办案类法律科技公开入口，多为法规/案例接口与能力介绍；"
                "接入前需核对数据来源授权、幻觉或过时法条风险提示，"
                "并明确工具输出仅供参考、正式意见须人工复核。"
            ),
            "legal_focus": (
                "法规案例检索与办案辅助工具影响制度依据核验与对外意见质量。法务部应确认"
                "数据来源授权、幻觉/过时法条风险提示、输出可否作为正式法律意见，并在"
                "对外合作与内部合规流程中明确人工复核节点与责任归属。"
            ),
            "impact_scenes": ["AI系统采购", "内部合规", "制度合规审核"],
            "tags": ["法律AI", "检索办案", "垂类工具"],
        },
    ),
    (
        "通用助手与Agent工作流",
        ("agent", "工作流", "办公", "通用大模型", "法务应用", "豆包", "扣子", "coze", "workbuddy"),
        {
            "title": "通用助手与Agent工作流落地需划定自动化权限、保密义务与采购合规边界",
            "key_info": (
                "本期归拢通用助手与Agent工作流相关公开入口，多为办公自动化与能力宣传；"
                "落地前需划定可自动化事项、账号权限、数据留存与保密边界，"
                "避免把演示能力直接写进正式业务流程。"
            ),
            "legal_focus": (
                "通用大模型与Agent平台可嵌入法务流程自动化，但易突破权限与保密边界。"
                "法务部应协同业务划定可自动化事项清单，在采购与使用规范中明确数据出境/"
                "留存、账号权限、提示词保密及不当自动化导致的违约与侵权责任。"
            ),
            "impact_scenes": ["AI系统采购", "内部合规", "制度合规审核"],
            "tags": ["Agent", "通用大模型", "垂类工具"],
        },
    ),
]


def _is_legal_tool_item(item: dict[str, Any]) -> bool:
    if (item.get("source_type") or "") == "legal_tools":
        return True
    title = str(item.get("title") or "")
    return "垂类法律工具" in title


def _legal_tool_theme_key(item: dict[str, Any]) -> str:
    blob = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("key_info") or ""),
            str(item.get("summary") or ""),
            " ".join(str(t) for t in (item.get("tags") or [])),
            str(item.get("source") or ""),
        ]
    ).lower()
    # 清单入口并入「通用助手」簇，作为延伸来源而非单独成条
    if "清单" in blob:
        return "通用助手与Agent工作流"
    for theme, keys, _meta in _LEGAL_TOOL_THEMES:
        if any(k.lower() in blob for k in keys):
            return theme
    return "通用助手与Agent工作流"


def aggregate_legal_tool_snapshots(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将分散的垂类工具观察快照汇总为提炼主题卡（风格对齐其他板块）。"""
    if not tools:
        return []
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in tools:
        buckets[_legal_tool_theme_key(it)].append(it)

    meta_map = {theme: meta for theme, _keys, meta in _LEGAL_TOOL_THEMES}
    out: list[dict[str, Any]] = []
    ordered_themes = [t[0] for t in _LEGAL_TOOL_THEMES] + [
        k for k in buckets if k not in {t[0] for t in _LEGAL_TOOL_THEMES}
    ]
    for theme in ordered_themes:
        group = buckets.get(theme) or []
        if not group:
            continue
        meta = meta_map.get(theme) or {
            "title": f"{theme}：本期法律科技工具观察要点",
            "key_info": (
                f"本期归拢「{theme}」相关公开入口，多为产品功能或接口说明；"
                "具体数据留存、授权与责任条款需对照采购文本另行核对。"
            ),
            "legal_focus": (
                "法务部可从采购与场景适用边界评估相关工具，关注数据留存、提示词泄露、"
                "开源组件与责任划分条款。"
            ),
            "impact_scenes": ["AI系统采购", "内部合规"],
            "tags": ["垂类工具", "法律AI"],
        }
        names: list[str] = []
        urls: list[dict[str, Any]] = []
        sources: list[str] = []
        originals: list[str] = []
        for g in group:
            t = re.sub(r"^垂类法律工具观察｜", "", str(g.get("title") or "")).strip()
            t = re.sub(r"^垂类法律工具清单参考｜", "", t).strip()
            t = re.sub(r"^垂类工具动态｜", "", t).strip()
            if t and t not in originals:
                originals.append(t)
            short = re.split(r"[（(]", t)[0].strip() if t else ""
            if (
                short
                and short not in names
                and "清单" not in short
                and "公开梳理" not in short
                and "功能介绍" not in short
                and "查看" not in short
            ):
                names.append(short)
            src = str(g.get("source") or "").strip()
            if src and src not in sources:
                sources.append(src)
            if g.get("url"):
                urls.append(
                    {
                        "title": short or t or src,
                        "url": g.get("url") or "",
                        "published_at": g.get("published_at") or "",
                        "published_date": g.get("published_date") or "",
                    }
                )

        # 关键信息写给人看的事实摘要，禁止把功能页标题串起来冒充
        brands = [s for s in sources if s and "垂类" not in s][:3]
        key_info = str(meta.get("key_info") or "").strip()
        if brands:
            brand_hint = "、".join(brands)
            if brand_hint not in key_info:
                key_info = f"{key_info.rstrip('。')}（主要来源：{brand_hint}）。"
        if not key_info:
            name_hint = "、".join(names[:4]) if names else theme
            key_info = (
                f"本期归拢{name_hint}等相关公开入口约{len(group)}处，"
                "多为功能/接口说明，需另行核对数据与责任条款。"
            )
        key_info = key_info[:480]
        primary = dict(group[0])
        primary["id"] = f"agg-legal_tools-{make_agg_id(theme, len(group))}"
        primary["title"] = meta["title"]
        primary["original_titles"] = originals[:10]
        primary["key_info"] = key_info
        primary["summary"] = key_info[:160]
        primary["legal_focus"] = meta["legal_focus"]
        primary["impact_scenes"] = list(meta.get("impact_scenes") or ["AI系统采购", "内部合规"])
        primary["impact_scene_tags"] = [f"#{s}" for s in primary["impact_scenes"]]
        primary["tags"] = list(meta.get("tags") or ["垂类工具", "法律AI"])
        primary["sources_list"] = sources[:10]
        primary["source"] = "、".join(sources[:4]) if sources else "垂类工具观察"
        primary["source_type"] = "legal_tools"
        primary["section"] = "legal_ai"
        primary["region"] = "国内"
        if urls:
            primary["url"] = urls[0].get("url") or primary.get("url") or ""
            primary["source_urls"] = urls[:10]
        pub_iso, pub_day = pick_best_published(group)
        primary["published_at"] = pub_iso
        primary["published_date"] = pub_day
        primary["date_source"] = "original" if pub_day else "missing"
        primary["aggregated"] = True
        primary["aggregate_count"] = len(group)
        primary["member_ids"] = [g.get("id") for g in group if g.get("id")]
        primary["tool_theme"] = theme
        out.append(primary)
    logger.info("垂类法律工具汇总：%s 条 → %s 张主题卡", len(tools), len(out))
    return out


def fold_legal_tools_into_summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从法律AI板块条目中抽出工具观察，汇总后插回板块前部。"""
    tools: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for it in items or []:
        # 已带 tool_theme 的汇总卡先跳过，最后统一重算，避免重复
        if it.get("tool_theme") and it.get("source_type") == "legal_tools":
            continue
        if _is_legal_tool_item(it):
            tools.append(it)
        else:
            others.append(it)

    if len(tools) < 2:
        return items

    cards = aggregate_legal_tool_snapshots(tools)
    return cards + others


def _llm_aggregate_section(
    items: list[dict[str, Any]],
    section_key: str,
    cfg: dict[str, Any],
    max_clusters: int,
) -> list[dict[str, Any]] | None:
    """调用大模型对板块条目做同类汇总，标题为提炼句。条目多时分批调用。"""
    endpoints = _llm_endpoints(cfg)
    if not endpoints or not items:
        return None

    weekly = cfg.get("weekly") or {}
    chunk_size = int(weekly.get("aggregate_chunk_size") or 18)
    if len(items) <= chunk_size:
        return _llm_aggregate_chunk(items, section_key, cfg, max_clusters, endpoints)

    # 分批聚合后再合并一轮，增加 LLM 调用次数、降低超长 JSON 截断
    merged: list[dict[str, Any]] = []
    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        part = _llm_aggregate_chunk(
            chunk, section_key, cfg, max(4, max_clusters // 2 + 1), endpoints
        )
        if part:
            merged.extend(part)
        else:
            merged.extend(_rule_aggregate_section(chunk, section_key, max_clusters))
    if len(merged) <= max_clusters:
        return merged
    # 二次压缩
    second = _llm_aggregate_chunk(merged, section_key, cfg, max_clusters, endpoints)
    return second or merged[:max_clusters]


def _llm_aggregate_chunk(
    items: list[dict[str, Any]],
    section_key: str,
    cfg: dict[str, Any],
    max_clusters: int,
    endpoints: list[dict[str, str]],
) -> list[dict[str, Any]] | None:
    """单批聚合。"""
    if not items:
        return None

    slim = []
    for i, it in enumerate(items):
        slim.append({
            "idx": i,
            "id": it.get("id"),
            "title": it.get("title"),
            "source": it.get("source"),
            "key_info": (it.get("key_info") or it.get("summary") or "")[:140],
            "legal_focus": (it.get("legal_focus") or "")[:100],
            "impact_scenes": it.get("impact_scenes") or [],
            "tags": (it.get("tags") or [])[:4],
            "url": it.get("url") or "",
            "importance": it.get("importance") or "",
        })

    label = SECTION_LABELS_CN.get(section_key, section_key)
    duty_block = legal_duty_prompt_block(cfg)
    system = (
        "你是两院法务部周报编辑。对给定公开资讯做「同类聚合」分析。\n"
        f"{duty_block}\n"
        "主题相近的合并为一条；标题必须是你提炼的法务观察句，严禁照搬原文标题；"
        "key_info 用 2～3 句中文汇总同类事实与差异（若原文为英文须译成中文后再写，禁止整段英文）；"
        "legal_focus 必须从法务部职责出发写 1～2 句中文："
        "侧重合规边界与跨部门把关、合同/制度审核、纠纷与权益风险、内控协同——"
        "不要写成业务部门如何落地科研或产品。\n"
        f"本板块为「{label}」，最多输出 {max_clusters} 条聚合卡。"
        "只输出 JSON 数组，元素字段："
        "member_idxs(原 idx 数组), title, key_info, legal_focus, impact_scenes(字符串数组), "
        "sources(来源名字符串数组，逐一列出勿合并成一句)。"
        "不要 Markdown，不要【】标记。字段值勿含未转义双引号。"
    )
    user = json.dumps({"items": slim}, ensure_ascii=False)
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)
    timeout = max(timeout, 120)

    last_err: Exception | None = None
    for ep in endpoints:
        try:
            logger.info(
                "尝试 LLM 板块聚合：%s / %s（%s→最多%s）",
                ep["name"],
                ep["model"],
                len(slim),
                max_clusters,
            )
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                timeout=timeout,
            )
            m = re.search(r"\[.*\]", text, re.S)
            if not m:
                last_err = ValueError("未解析到 JSON 数组")
                continue
            try:
                clusters = json.loads(m.group(0))
            except json.JSONDecodeError:
                # 宽松修复：截到最后一个完整对象
                raw = m.group(0)
                cut = raw.rfind("}")
                if cut > 0:
                    try:
                        clusters = json.loads(raw[: cut + 1] + "]")
                    except json.JSONDecodeError as e:
                        last_err = e
                        continue
                else:
                    last_err = ValueError("JSON 无法修复")
                    continue
            if not isinstance(clusters, list) or not clusters:
                last_err = ValueError("聚合结果为空")
                continue

            out: list[dict[str, Any]] = []
            used: set[int] = set()
            for c in clusters[:max_clusters]:
                if not isinstance(c, dict):
                    continue
                idxs = c.get("member_idxs") or c.get("idxs") or []
                idxs = [int(x) for x in idxs if isinstance(x, (int, float, str)) and str(x).isdigit()]
                idxs = [i for i in idxs if 0 <= i < len(items)]
                if not idxs:
                    continue
                used.update(idxs)
                group = [items[i] for i in idxs]
                primary = group[0]
                title = re.sub(r"【[^】]*】", "", str(c.get("title") or "")).strip()
                if not title:
                    continue
                raw_titles = {(it.get("title") or "").strip() for it in group}
                if len(group) > 1 and title in raw_titles:
                    theme = (c.get("impact_scenes") or ["综合"])[0]
                    title = f"{theme}：{title[:28]}等{len(group)}条动态"
                key_info = re.sub(r"【[^】]*】", "", str(c.get("key_info") or "")).strip()
                legal = re.sub(r"【[^】]*】", "", str(c.get("legal_focus") or "")).strip()
                scenes = c.get("impact_scenes") or primary.get("impact_scenes") or []
                if isinstance(scenes, str):
                    scenes = [scenes]
                sources = []
                for g in group:
                    for part in re.split(r"[、/,，;；|]+", str(g.get("source") or "")):
                        part = part.strip()
                        if part and part not in sources:
                            sources.append(part)
                llm_sources = c.get("sources") or c.get("source")
                if isinstance(llm_sources, list):
                    for part in llm_sources:
                        part = str(part).strip()
                        if part and part not in sources:
                            sources.append(part)
                elif isinstance(llm_sources, str) and llm_sources.strip():
                    for part in re.split(r"[、/,，;；|]+", llm_sources.strip()):
                        part = part.strip()
                        if part and part not in sources:
                            sources.append(part)
                urls = [
                    {
                        "title": str(g.get("title") or "")[:120],
                        "url": g.get("url") or "",
                        "published_at": g.get("published_at") or g.get("published_date") or "",
                        "published_date": g.get("published_date") or "",
                    }
                    for g in group
                    if g.get("url") or g.get("title")
                ][:8]
                orig_titles = [
                    re.sub(r"【[^】]*】", "", str(g.get("title") or "")).strip()
                    for g in group
                    if (g.get("title") or "").strip()
                ]
                # 若成员本身已是聚合卡，带上其原文标题
                for g in group:
                    for ot in g.get("original_titles") or []:
                        ot = re.sub(r"【[^】]*】", "", str(ot)).strip()
                        if ot and ot not in orig_titles:
                            orig_titles.append(ot)
                row = dict(primary)
                row["id"] = f"agg-{section_key}-{make_agg_id(title, len(group))}"
                row["title"] = title[:80]
                row["original_titles"] = orig_titles[:8]
                row["key_info"] = key_info[:480] or title
                row["summary"] = row["key_info"][:160]
                row["legal_focus"] = legal[:280]
                row["impact_scenes"] = list(scenes)[:6]
                row["impact_scene_tags"] = [f"#{s}" for s in row["impact_scenes"]] or ["#内部合规"]
                row["sources_list"] = sources[:8]
                row["source"] = "、".join(sources[:4]) if sources else (primary.get("source") or "")
                if urls:
                    row["url"] = urls[0].get("url") or ""
                    if len(urls) > 1:
                        row["extended_source"] = "同类原文：" + "；".join(
                            u["title"] for u in urls[1:4] if u.get("title")
                        )
                pub_iso, pub_day = pick_best_published(group)
                row["published_at"] = pub_iso
                row["published_date"] = pub_day
                row["date_source"] = "original" if pub_day else "missing"
                row["aggregated"] = True
                row["aggregate_count"] = len(group)
                row["member_ids"] = [g.get("id") for g in group if g.get("id")]
                row["source_urls"] = urls
                row["section"] = section_key
                out.append(row)

            for i, it in enumerate(items):
                if i in used:
                    continue
                row = dict(it)
                t = re.sub(r"【[^】]*】", "", str(row.get("title") or "")).strip()
                t = re.sub(r"^(一图读懂[:：]?|图解[:：]?)", "", t).strip() or t
                if not row.get("original_titles") and t:
                    row["original_titles"] = [t]
                if not row.get("sources_list"):
                    row["sources_list"] = [
                        p.strip()
                        for p in re.split(r"[、/,，;；|]+", str(row.get("source") or ""))
                        if p.strip()
                    ]
                row["title"] = t
                row["section"] = section_key
                out.append(row)
                if len(out) >= max_clusters + 4:
                    break
            if out:
                return out[: max_clusters + 4]
        except Exception as e:
            last_err = e
            logger.warning("LLM 板块聚合失败 %s：%s", ep["name"], e)

    if last_err:
        logger.warning("板块 %s 聚合全部失败：%s", section_key, last_err)
    return None


def _looks_mostly_english(text: str) -> bool:
    """判断关键信息是否以英文为主（需译成中文）。"""
    s = (text or "").strip()
    if len(s) < 24:
        return False
    letters = sum(1 for ch in s if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    if letters < 20:
        return False
    return letters > cjk * 2


def translate_key_info_to_zh(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """英文关键信息批量译成中文（多调一次大模型）。"""
    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        return digest

    digest = dict(digest)
    sections = dict(digest.get("sections") or {})
    need: list[tuple[str, int, str]] = []
    for key, items in sections.items():
        for idx, it in enumerate(items or []):
            ki = str(it.get("key_info") or it.get("summary") or "").strip()
            if _looks_mostly_english(ki):
                need.append((key, idx, ki[:500]))
    if not need:
        return digest

    payload = [{"i": n, "text": t} for n, (_, _, t) in enumerate(need)]
    system = (
        "将下列英文资讯摘要译成简洁中文（法务可读，2～4句）。"
        "只输出 JSON 数组，元素字段：i(原序号整数), zh(中文译文)。不要英文原文。"
    )
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)
    for ep in endpoints:
        try:
            logger.info("尝试英译中关键信息：%s 条 via %s", len(payload), ep["name"])
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                timeout=timeout,
            )
            m = re.search(r"\[.*\]", text, re.S)
            if not m:
                continue
            arr = json.loads(m.group(0))
            mapping: dict[int, str] = {}
            for obj in arr:
                if not isinstance(obj, dict):
                    continue
                try:
                    mapping[int(obj.get("i"))] = str(obj.get("zh") or "").strip()
                except (TypeError, ValueError):
                    continue
            for n, (sec, idx, _) in enumerate(need):
                zh = mapping.get(n) or ""
                if not zh:
                    continue
                row = dict(sections[sec][idx])
                row["key_info"] = zh[:480]
                row["summary"] = zh[:160]
                row["key_info_translated"] = True
                sections[sec][idx] = row
            digest["sections"] = sections
            digest["items"] = [
                it for k in ("global_ai", "legal_ai", "two_institute") for it in (sections.get(k) or [])
            ]
            logger.info("已完成关键信息英译中 %s/%s", len(mapping), len(need))
            return digest
        except Exception as e:
            logger.warning("关键信息英译中失败 %s：%s", ep["name"], e)
    return digest


def aggregate_sections_with_llm(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """对三大板块做同类内容聚合；标题改为提炼句，并多调用大模型分析。"""
    weekly_cfg = cfg.get("weekly") or {}
    if not weekly_cfg.get("aggregate_sections", True):
        return digest

    digest = dict(digest)
    sections = dict(digest.get("sections") or {})
    max_clusters = int(weekly_cfg.get("aggregate_max_per_section") or 10)
    min_to_agg = int(weekly_cfg.get("aggregate_min_items") or 3)
    new_sections: dict[str, list] = {}
    flat: list[dict[str, Any]] = []

    for key in ("global_ai", "legal_ai", "two_institute"):
        items = list(sections.get(key) or [])
        # 法律AI：先抽出垂类工具，避免被监管动态稀释或逐条残留
        tool_items: list[dict[str, Any]] = []
        if key == "legal_ai":
            kept: list[dict[str, Any]] = []
            for it in items:
                if _is_legal_tool_item(it) and not it.get("tool_theme"):
                    tool_items.append(it)
                else:
                    kept.append(it)
            items = kept

        if len(items) < min_to_agg:
            cleaned = []
            for it in items:
                row = dict(it)
                t = re.sub(r"【[^】]*】", "", str(row.get("title") or "")).strip() or row.get("title")
                row["title"] = t
                if not row.get("original_titles") and t:
                    row["original_titles"] = [str(t)]
                if not row.get("sources_list"):
                    row["sources_list"] = [
                        p.strip()
                        for p in re.split(r"[、/,，;；|]+", str(row.get("source") or ""))
                        if p.strip()
                    ]
                cleaned.append(row)
            clustered = cleaned
        else:
            clustered = _llm_aggregate_section(items, key, cfg, max_clusters)
            if not clustered:
                clustered = _rule_aggregate_section(items, key, max_clusters)
                logger.info("板块 %s 使用规则聚合：%s → %s", key, len(items), len(clustered))
            else:
                logger.info("板块 %s LLM 聚合：%s → %s", key, len(items), len(clustered))

        if key == "legal_ai" and tool_items:
            tool_cards = aggregate_legal_tool_snapshots(tool_items)
            clustered = tool_cards + list(clustered or [])
        elif key == "legal_ai":
            clustered = fold_legal_tools_into_summaries(list(clustered or []))

        new_sections[key] = clustered
        flat.extend(clustered)

    digest["sections"] = new_sections
    digest["items"] = flat
    digest["sections_raw_backup"] = {
        k: [{"id": i.get("id"), "title": i.get("title")} for i in (sections.get(k) or [])]
        for k in ("global_ai", "legal_ai", "two_institute")
    }
    counts = dict(digest.get("counts") or {})
    counts["by_section"] = {k: len(new_sections.get(k) or []) for k in ("global_ai", "legal_ai", "two_institute")}
    counts["aggregated"] = sum(1 for i in flat if i.get("aggregated"))
    digest["counts"] = counts
    # 英文关键信息再译成中文
    digest = translate_key_info_to_zh(digest, cfg)
    return digest


def rewrite_legal_focus_for_digest(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """综合「法务部职责 + 本期资讯内容」重写关注点、本期聚焦与收尾建议。"""
    endpoints = _llm_endpoints(cfg)
    digest = dict(digest)
    sections = dict(digest.get("sections") or {})
    if not endpoints:
        logger.warning("无 LLM，跳过按职责+资讯综合重写")
        return digest

    duty_block = legal_duty_prompt_block(cfg)
    duty = legal_duty_text(cfg)
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)
    timeout = max(timeout, 120)
    sec_label = {
        "global_ai": "全球AI治理与产业动态",
        "legal_ai": "法律AI/合规实务",
        "two_institute": "两院法务",
    }

    # —— 1) 逐板块：综合职责 + 本条资讯重写 legal_focus ——
    for sec_key in ("global_ai", "legal_ai", "two_institute"):
        items = list(sections.get(sec_key) or [])
        if not items:
            continue
        slim = []
        for i, it in enumerate(items):
            slim.append({
                "idx": i,
                "title": it.get("title"),
                "original_titles": (it.get("original_titles") or [])[:4],
                "key_info": (it.get("key_info") or it.get("summary") or "")[:280],
                "sources": (it.get("sources_list") or _split_source_names(it.get("source")))[:5],
                "impact_scenes": it.get("impact_scenes") or [],
            })
        system = (
            "你是两院法务部律师。任务：综合「法务部职责」与「本条资讯事实」重写法务关注点。\n"
            f"{duty_block}\n"
            "要求：\n"
            "1) 必须先理解本条 key_info/title 说了什么，再映射到职责中的具体动作"
            "（合同条款、制度规则、会签材料、风险提示、纠纷预防、责任边界）；\n"
            "2) legal_focus 写 2 句中文：第1句点出本条触发的具体法律/合规问题，"
            "第2句写可执行把关动作（在XX类合同加/改XX条款、向XX部门发XX提示、核查XX存量安排）；\n"
            "3) 禁止空话：建议持续关注、提高意识、需承办人判断、视情况处理、建议相关部门重视；\n"
            "4) 禁止业务部门如何做科研/产品的口吻；不要编造资讯里没有的文件名或法条编号。\n"
            "只输出 JSON 数组，元素：idx, legal_focus。"
        )
        for ep in endpoints:
            try:
                logger.info("综合职责+资讯重写关注点：%s %s条 via %s", sec_key, len(slim), ep["name"])
                text = _call_openai_compatible(
                    ep["api_base"],
                    ep["api_key"],
                    ep["model"],
                    [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"section": sec_label.get(sec_key, sec_key), "items": slim},
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    timeout=timeout,
                )
                m = re.search(r"\[.*\]", text, re.S)
                if not m:
                    continue
                try:
                    arr = json.loads(m.group(0))
                except json.JSONDecodeError:
                    raw = m.group(0)
                    cut = raw.rfind("}")
                    if cut < 0:
                        continue
                    arr = json.loads(raw[: cut + 1] + "]")
                mapping: dict[int, str] = {}
                for obj in arr:
                    if not isinstance(obj, dict):
                        continue
                    try:
                        mapping[int(obj.get("idx"))] = re.sub(
                            r"【[^】]*】", "", str(obj.get("legal_focus") or "")
                        ).strip()
                    except (TypeError, ValueError):
                        continue
                new_items = []
                for i, it in enumerate(items):
                    row = dict(it)
                    if mapping.get(i):
                        row["legal_focus"] = mapping[i][:320]
                    new_items.append(row)
                sections[sec_key] = new_items
                logger.info("板块 %s 综合重写关注点 %s/%s", sec_key, len(mapping), len(items))
                break
            except Exception as e:
                logger.warning("综合重写关注点失败 %s/%s：%s", sec_key, ep["name"], e)

    digest["sections"] = sections
    digest["items"] = [
        it for k in ("global_ai", "legal_ai", "two_institute") for it in (sections.get(k) or [])
    ]

    # —— 2) 综合职责 + 全期资讯：重写本期聚焦 + 收尾问答 ——
    overview_items = []
    for k in ("two_institute", "legal_ai", "global_ai"):
        for it in sections.get(k) or []:
            overview_items.append({
                "section": sec_label.get(k, k),
                "title": it.get("title"),
                "key_info": (it.get("key_info") or "")[:160],
                "legal_focus": (it.get("legal_focus") or "")[:140],
            })
            if len(overview_items) >= 18:
                break
        if len(overview_items) >= 18:
            break

    system2 = (
        "你是两院法务部负责人助理。请综合「法务部职责」与「本期资讯要点」输出 JSON，字段：\n"
        "judgment_clue：1句本期判断线索（哪些法律规则变化真正影响两院；语气克制）；\n"
        "mainline：1句本期主线（如何传导到合同/制度/风险提示；勿夸张；与线索合计作两句引导）；\n"
        "week_legal_reference_items：3～5 条（对象数组），字段 tip/keyword/related_title；"
        "tip 须可执行（模板加条款/发提示/核查存量）；related_title 必须对应本期真实条目标题；\n"
        "week_legal_reference：可选兼容字段，由 tip 换行拼接。\n"
        f"法务部职责：{duty}\n"
        f"{TONE_RULE}\n"
        "禁止空泛套话与业务落地口吻；不要编造法条编号。只输出 JSON。"
    )
    for ep in endpoints:
        try:
            logger.info("综合职责+全期资讯重写聚焦与收尾 via %s", ep["name"])
            text = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": system2},
                    {"role": "user", "content": json.dumps({"items": overview_items}, ensure_ascii=False)},
                ],
                timeout=timeout,
            )
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                continue
            obj = json.loads(m.group(0))
            weekly = dict(digest.get("weekly") or {})
            ai = dict(digest.get("ai_summary") or {})

            def _clean(v: Any) -> str:
                return re.sub(r"【[^】]*】", "", str(v or "")).strip()

            clue = soften_alarmist_zh(_clean(obj.get("judgment_clue")))
            mainline = soften_alarmist_zh(_clean(obj.get("mainline")))
            items = normalize_week_reference_items(
                obj.get("week_legal_reference_items")
                or obj.get("week_reference_items")
                or obj.get("week_legal_reference")
                or obj.get("week_reference")
                or ""
            )
            if not items:
                items = normalize_week_reference_items(
                    build_week_legal_reference(
                        question=_clean(obj.get("week_think_question")),
                        action=_clean(obj.get("week_action_suggestion")),
                    )
                )
            if clue:
                weekly["judgment_clue"] = clue[:220]
                ai["judgment_clue"] = weekly["judgment_clue"]
            if mainline:
                weekly["mainline"] = mainline[:480]
                ai["mainline"] = weekly["mainline"]
            if items:
                joined = "\n".join(
                    (x.get("tip") if isinstance(x, dict) else str(x)) for x in items
                )
                weekly["week_legal_reference_items"] = items
                ai["week_legal_reference_items"] = items
                weekly["week_legal_reference"] = joined[:600]
                ai["week_legal_reference"] = weekly["week_legal_reference"]
                weekly["week_think_question"] = joined[:400]
                ai["week_think_question"] = weekly["week_think_question"]
                weekly["week_action_suggestion"] = ""
                ai["week_action_suggestion"] = ""
            digest["weekly"] = weekly
            digest["ai_summary"] = ai
            logger.info("已综合重写本期聚焦与收尾问答")
            break
        except Exception as e:
            logger.warning("综合重写聚焦/收尾失败 %s：%s", ep["name"], e)
    else:
        # 兜底：至少刷新收尾问答
        qa = llm_week_qa(digest, cfg)
        if qa:
            weekly = dict(digest.get("weekly") or {})
            weekly["week_legal_reference"] = qa.get("week_legal_reference") or ""
            weekly["week_legal_reference_items"] = qa.get("week_legal_reference_items") or []
            weekly["week_think_question"] = qa.get("week_think_question") or weekly["week_legal_reference"]
            weekly["week_action_suggestion"] = ""
            digest["weekly"] = weekly
            ai = dict(digest.get("ai_summary") or {})

            ai["week_legal_reference"] = weekly["week_legal_reference"]
            ai["week_think_question"] = weekly["week_think_question"]
            ai["week_action_suggestion"] = ""
            digest["ai_summary"] = ai
    return digest


def _split_source_names(raw: Any) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    return [p.strip() for p in re.split(r"[、/,，;；|]+", s) if p.strip()]


def attach_ai_summary(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """给 digest 挂上 summary 字段；优先 LLM，失败则规则。收尾问答单独强制生成。"""
    enrich_cfg = cfg.get("enrich") or {}
    prefer = (enrich_cfg.get("summary_mode") or "auto").lower()  # auto | llm | rule

    result = None
    if prefer in ("auto", "llm"):
        result = llm_briefing(digest, cfg)
        if result is None and prefer == "llm":
            logger.warning("summary_mode=llm 但调用失败，回退规则整理")

    if result is None:
        result = rule_based_briefing(digest)

    # 收尾栏：周报模式下单独强制调用 LLM（不依赖综述里是否顺带写出）
    if prefer in ("auto", "llm") and (digest.get("product_mode") or "weekly") == "weekly":
        qa = llm_week_qa(digest, cfg)
        if qa:
            result = dict(result)
            items = qa.get("week_legal_reference_items") or []
            if not isinstance(items, list):
                items = []
            if not items:
                items = normalize_week_reference_items(
                    qa.get("week_legal_reference")
                    or build_week_legal_reference(
                        question=qa.get("week_think_question") or "",
                        action=qa.get("week_action_suggestion") or "",
                    )
                )
            # items 可能是 tip 字符串，也可能是 {tip, keyword, related_title}
            if items:
                ref = "\n".join(
                    (x.get("tip") if isinstance(x, dict) else str(x)) for x in items
                )
            else:
                ref = (
                    qa.get("week_legal_reference")
                    or build_week_legal_reference(
                        question=qa.get("week_think_question") or "",
                        action=qa.get("week_action_suggestion") or "",
                    )
                )
            result["week_legal_reference"] = ref
            result["week_legal_reference_items"] = items
            result["week_think_question"] = ref
            result["week_action_suggestion"] = ""
            result["week_qa_provider"] = qa.get("provider")
            result["week_qa_model"] = qa.get("model")

            logger.info(
                "已写入 AI 法务部参考建议（%s/%s）",
                qa.get("provider"),
                qa.get("model"),
            )
        elif _is_generic_week_text(
            str(result.get("week_legal_reference") or result.get("week_think_question") or "")
        ):
            logger.warning("未能生成有效 AI 法务部参考建议，将使用规则兜底（可能仍偏空泛）")

    digest = dict(digest)
    digest["ai_summary"] = result
    weekly = dict(digest.get("weekly") or {})
    audience = weekly.get("audience") or "面向两院法务和管理层，按照两院适配行业、单位性质提供前沿法律咨询"
    if result.get("judgment_clue"):
        weekly["judgment_clue"] = soften_alarmist_zh(
            re.sub(r"【[^】]*】", "", str(result["judgment_clue"])).strip()
        )
    if result.get("mainline"):
        weekly["mainline"] = soften_alarmist_zh(
            re.sub(r"【[^】]*】", "", str(result["mainline"])).strip()
        )
    items = result.get("week_legal_reference_items") or weekly.get("week_legal_reference_items") or []
    if not isinstance(items, list):
        items = []
    if not items:
        items = normalize_week_reference_items(
            result.get("week_legal_reference")
            or weekly.get("week_legal_reference")
            or ""
        )
    ref = build_week_legal_reference(
        reference=str(result.get("week_legal_reference") or weekly.get("week_legal_reference") or ""),
        question=str(result.get("week_think_question") or weekly.get("week_think_question") or ""),
        action=str(result.get("week_action_suggestion") or weekly.get("week_action_suggestion") or ""),
    )
    if items:
        cleaned: list[Any] = []
        for x in items:
            if isinstance(x, dict):
                tip = soften_alarmist_zh(str(x.get("tip") or "").strip())
                if not tip or _is_generic_week_text(tip):
                    continue
                cleaned.append(
                    {
                        "tip": tip[:120],
                        "keyword": str(x.get("keyword") or "").strip()[:12],
                        "related_title": str(x.get("related_title") or "").strip()[:80],
                    }
                )
            else:
                s = soften_alarmist_zh(str(x).strip())
                if s and not _is_generic_week_text(s):
                    cleaned.append(s)
            if len(cleaned) >= 5:
                break
        if cleaned:
            weekly["week_legal_reference_items"] = cleaned
            ref = "\n".join(
                (x.get("tip") if isinstance(x, dict) else str(x)) for x in cleaned
            )
    if ref and not _is_generic_week_text(ref):
        ref = soften_alarmist_zh(ref)
        weekly["week_legal_reference"] = ref
        weekly["week_think_question"] = ref
        weekly["week_action_suggestion"] = ""
    # 定位仅供 AI 理解，不再写入对外字段

    weekly["audience"] = re.sub(r"【[^】]*】", "", audience).split("【")[0].strip() or audience
    weekly.pop("positioning", None)
    # 测试期标记透传
    wcfg = cfg.get("weekly") or {}
    if wcfg.get("test_issue"):
        weekly["test_issue"] = True
        weekly["issue_label"] = (wcfg.get("issue_label") or "测试期").strip() or "测试期"
    elif wcfg.get("issue_label"):
        weekly["issue_label"] = str(wcfg.get("issue_label")).strip()
    if digest.get("title") and "vol.【" not in str(digest.get("title")):
        from report_html import format_title

        weekly.setdefault("brand", "法律AI每周资讯")
        digest["title"] = format_title(weekly.get("brand") or "法律AI每周资讯", weekly.get("vol") or digest.get("vol") or 1)
    digest["weekly"] = weekly
    return digest
