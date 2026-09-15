# -*- coding: utf-8 -*-
"""周报 HTML/MD：三大板块 + 固定字段条目卡。

结构：
- 刊头（标题 / 副题 / 期号日期）
- 本期聚焦 Hero 卡
- 三大独立板块（全球AI动态 / 法律AI法律科技 / 两院法务）
- 条目横排卡片：角标 + 标题行简栏 + 来源/关键信息/法务关注点/影响场景
- 法务部参考建议（收尾，多条短建议列表）
- 页脚免责声明

对外产出不展示内部流程元素。
"""

from __future__ import annotations

import html
import re
from typing import Any

DEFAULT_AUDIENCE = "面向两院法务和管理层，按照两院适配行业、单位性质提供前沿法律咨询"
DEFAULT_SUBTITLE = "两院法务 · AI 与全球合规观察"

from sections_strategy import SECTION_STRATEGY
from summarize import WEEK_LEGAL_REFERENCE_LABEL, build_week_legal_reference, soften_alarmist_zh
from utils import format_display_date

SECTION_META = {
    "global_ai": {
        "label": SECTION_STRATEGY["global_ai"]["label"],
        "positioning": SECTION_STRATEGY["global_ai"]["positioning"],
        "tags": SECTION_STRATEGY["global_ai"]["tags"],
        "accent": "#1e4f9c",
    },
    "legal_ai": {
        "label": SECTION_STRATEGY["legal_ai"]["label"],
        "positioning": SECTION_STRATEGY["legal_ai"]["positioning"],
        "tags": SECTION_STRATEGY["legal_ai"]["tags"],
        "accent": "#1e4f9c",
    },
    "two_institute": {
        "label": SECTION_STRATEGY["two_institute"]["label"],
        "positioning": SECTION_STRATEGY["two_institute"]["positioning"],
        "tags": SECTION_STRATEGY["two_institute"]["tags"],
        "accent": "#1e4f9c",
    },
}

# 导航与版面顺序：两院法务 → 法律AI/科技 → 全球动态
SECTION_ORDER = ("two_institute", "legal_ai", "global_ai")


def _split_zh_sentences(text: str) -> list[str]:
    """按中文句末标点切分，保留句号。"""
    raw = re.sub(r"\s+", "", (text or "").strip())
    if not raw:
        return []
    parts = re.findall(r"[^。！？!?]+[。！？!?]?", raw)
    out: list[str] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        if s[-1] not in "。！？!?":
            s += "。"
        out.append(s)
    return out


def _guide_blurb(*parts: str, max_sentences: int = 2) -> str:
    """压缩为引导短文：最多两句，起导读作用。"""
    sentences: list[str] = []
    for part in parts:
        for s in _split_zh_sentences(part):
            if s and s not in sentences:
                sentences.append(s)
            if len(sentences) >= max_sentences:
                return "".join(sentences[:max_sentences])
    return "".join(sentences[:max_sentences])


def _clip_guide_sentence(text: str, max_chars: int = 48) -> str:
    """单句过长时优先按逗号取完整分句，避免生硬截断。"""
    s = (text or "").strip()
    if not s:
        return ""
    if s[-1] not in "。！？!?":
        s += "。"
    body = s[:-1]
    if len(body) <= max_chars:
        return s
    # 先按句内逗号取完整意思；再退回顿号
    for sep in ("，", "；", "、"):
        i = body.find(sep)
        if 10 <= i <= max_chars:
            return body[:i] + "。"
    cut = body[:max_chars]
    for sep in ("，", "、", "；", "：", ",", " "):
        i = cut.rfind(sep)
        if i >= 10:
            return cut[:i] + "。"
    return cut.rstrip("，、；：, ") + "。"


def _focus_pair(*parts: str) -> tuple[str, str]:
    """本期聚焦拆成主句 + 补充句，便于扫读。"""
    sentences = _split_zh_sentences(_guide_blurb(*parts, max_sentences=2))
    # 主句稍长以成完整意思，补充句更短
    lead = _clip_guide_sentence(sentences[0], 52) if sentences else ""
    sub = _clip_guide_sentence(sentences[1], 28) if len(sentences) > 1 else ""
    if not lead:
        lead = "关注 AI/数据监管对两院管理场景的传导。"
    return lead, sub


def _esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def strip_ai_markers(text: Any) -> str:
    """去掉仅供 AI 理解的【…】标记及「定位」等内部前缀，不展示给读者。"""
    s = str(text if text is not None else "")
    if not s:
        return ""
    s = re.sub(r"【[^】]*】", "", s)
    s = re.sub(r"^\s*定位\s*[:：]\s*", "", s)
    for prefix in ("法务视角：", "法务视角·", "法务视角 "):
        if s.startswith(prefix):
            s = s[len(prefix) :]
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _vol_str(vol: Any) -> str:
    s = str(vol or "1")
    return s.zfill(2) if s.isdigit() else s


def format_title(brand: str, vol: Any) -> str:
    b = (brand or "法律AI每周资讯").strip()
    # 去掉历史残留的 Vol.xx，对外标题不再展示期号
    b = re.sub(r"\s*Vol\.\s*\d+\s*$", "", b, flags=re.I).strip()
    return b or "法律AI每周资讯"


def format_positioning(audience: str, judgment_clue: str) -> str:
    """内部兼容：仅返回受众句，不再拼接【判断线索】（线索走本期聚焦）。"""
    base = (audience or DEFAULT_AUDIENCE).strip()
    if "【" in base:
        base = base.split("【", 1)[0].strip()
    return strip_ai_markers(base) or DEFAULT_AUDIENCE


def _category_tag(item: dict[str, Any]) -> str:
    tags = [str(t) for t in (item.get("tags") or []) if t and t != "未分类"]
    scenes = [str(s) for s in (item.get("impact_scenes") or []) if s]
    parts = (tags[:2] or scenes[:2] or ["资讯"])
    return " | ".join(p.upper() if re.match(r"^[A-Za-z]", p) else p for p in parts)


def _keywords_line(item: dict[str, Any]) -> str:
    bits: list[str] = []
    for t in (item.get("tags") or [])[:3]:
        if t and t != "未分类":
            bits.append(str(t))
    for s in (item.get("impact_scenes") or [])[:2]:
        if s and str(s) not in bits:
            bits.append(str(s))
    if not bits:
        bits = ["详情"]
    return " | ".join(bits)


def _clean_key_info(text: str) -> str:
    """去掉页面导航/日期来源行等噪音，保留可读摘要。"""
    s = (text or "").strip()
    if not s:
        return ""
    # 去掉常见页眉页脚碎片
    s = re.sub(r"日期[：:]\s*\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[^\n]*", " ", s)
    s = re.sub(r"来源[：:]\s*[^\n]{0,40}", " ", s)
    s = re.sub(r"分享[：:]\s*\S*", " ", s)
    s = re.sub(r"首页\s*学习新时代.*?(关于我们)?", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ：:|-")
    return s[:400] if s else ""


def _is_key_info_title_dump(text: str) -> bool:
    """判断关键信息是否只是标题/入口堆砌，给人看没有信息增量。"""
    s = (text or "").strip()
    if not s or s in ("—", "-"):
        return True
    if "本期观察「" in s and ("入口" in s or "垂类工具" in s):
        return True
    if s.count("垂类工具动态") >= 2 or s.count("公开页：") >= 2:
        return True
    if s.count("｜") >= 2 and ("功能介绍" in s or "查看" in s):
        return True
    parts = [p.strip() for p in re.split(r"[；;]", s) if p.strip()]
    if len(parts) >= 4:
        shortish = sum(1 for p in parts if len(p) <= 36)
        if shortish >= max(3, int(len(parts) * 0.7)):
            return True
    return False


def _humanize_key_info(item: dict[str, Any], raw: str) -> str:
    """把不可读的标题堆砌改写成给人看的关键摘要。"""
    cleaned = _clean_key_info(raw)
    title = strip_ai_markers(item.get("title") or "").strip()
    if cleaned and cleaned != title and not _is_key_info_title_dump(cleaned):
        return cleaned

    sources = _split_sources(item.get("sources_list") or item.get("source"))
    brands = [s for s in sources if s and "垂类" not in s][:3]
    originals = _original_titles_of(item)
    caps: list[str] = []
    for t in originals:
        t = re.sub(r"^垂类工具动态｜", "", t).strip()
        t = re.sub(r"^垂类法律工具观察｜", "", t).strip()
        t = re.sub(r"^查看\s*", "", t).strip()
        if not t or "清单" in t:
            continue
        # 能力名取短句，避免整段标题
        short = re.split(r"[（(｜|]", t)[0].strip()
        short = re.sub(r"(功能介绍|接口)$", "", short).strip()[:16]
        if short and short not in caps and short != title:
            caps.append(short)
        if len(caps) >= 4:
            break

    n = int(item.get("aggregate_count") or len(originals) or 0)
    is_tools = (item.get("source_type") or "") == "legal_tools" or any(
        "垂类" in str(x) for x in (originals[:2] or [raw[:20]])
    )
    if is_tools:
        brand = "、".join(brands) if brands else "相关产品"
        cap = "、".join(caps) if caps else "功能介绍"
        count = n or max(len(caps), 1)
        return (
            f"本期归拢{brand}等公开入口约{count}处，覆盖{cap}等能力宣传；"
            f"页面多为功能说明，不能直接当作采购与责任条款。"
        )[:280]

    if title:
        return (
            f"本期动态围绕「{title[:40]}」；"
            f"公开材料需点开原文核对事实，避免只看标题或入口名。"
        )[:220]
    return "公开材料信息不足，需点开原文核对。"


_GENERIC_LEGAL = (
    "需承办人判断是否与两院",
    "建议对照现行制度评估",
)


def _is_generic_legal_focus(text: str) -> bool:
    s = (text or "").strip()
    if not s or s in ("—", "-"):
        return True
    return any(m in s for m in _GENERIC_LEGAL)


def _split_sources(raw: Any) -> list[str]:
    """将来源拆成逐条列表（支持、/，;；及已有 list）。"""
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if str(x).strip()]
    else:
        s = str(raw or "").strip()
        if not s or s == "—":
            return []
        parts = re.split(r"[、/,，;；|]+", s)
        parts = [p.strip() for p in parts if p.strip()]
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _original_titles_of(item: dict[str, Any]) -> list[str]:
    """聚合条目的原文标题列表。"""
    titles: list[str] = []
    for t in item.get("original_titles") or []:
        t = strip_ai_markers(t)
        if t:
            titles.append(t)
    if not titles:
        for u in item.get("source_urls") or []:
            if isinstance(u, dict):
                t = strip_ai_markers(u.get("title") or "")
                if t:
                    titles.append(t)
    # 去重保序；去掉与提炼标题完全相同的
    refined = strip_ai_markers(item.get("title") or "")
    seen: set[str] = set()
    out: list[str] = []
    for t in titles:
        if t == refined or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _source_links_of(item: dict[str, Any]) -> list[dict[str, str]]:
    """原文网站列表：用链接代替「详情」。每项含 label（可选）与 url。"""
    sources = _split_sources(item.get("sources_list") or item.get("source"))
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    surls = [
        u
        for u in (item.get("source_urls") or [])
        if isinstance(u, dict) and str(u.get("url") or "").strip()
    ]
    if surls:
        for i, u in enumerate(surls):
            url = str(u.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            label = sources[i] if i < len(sources) else ""
            links.append({"label": label, "url": url})
    primary = str(item.get("url") or "").strip()
    if primary and primary not in seen:
        label = sources[0] if sources else ""
        links.append({"label": label, "url": primary})
    # 有来源名但尚无任何链接时，仍返回名称（无 url）
    if not links and sources:
        for s in sources:
            links.append({"label": s, "url": ""})
    return links


def _item_fields(item: dict[str, Any]) -> dict[str, Any]:
    """条目固定字段（与《周报说明》一致；不含条目级思考/行动）。"""
    # 时间戳必须来自原文可解析日期，禁止 [:10] 截断 RFC2822
    date_disp = format_display_date(item)
    scenes = item.get("impact_scene_tags") or [f"#{s}" for s in (item.get("impact_scenes") or [])]
    if not scenes:
        scenes = ["—"]
    key_info = _humanize_key_info(
        item,
        str(item.get("key_info") or item.get("summary") or ""),
    )
    legal = strip_ai_markers(item.get("legal_focus") or "")
    if _is_generic_legal_focus(legal):
        legal = ""
    title = strip_ai_markers(item.get("title") or "") or "（无标题）"
    sources = _split_sources(item.get("sources_list") or item.get("source"))
    source_links = _source_links_of(item)
    return {
        "title": title,
        "original_titles": _original_titles_of(item),
        "date": date_disp,
        "region": strip_ai_markers(item.get("region") or "—") or "—",
        "sources": sources,
        "source_links": source_links,
        "source": "、".join(sources) if sources else "—",
        "extended_source": (item.get("extended_source") or "—").strip() or "—",
        "key_info": key_info or "—",
        "legal_focus": legal,
        "impact_scenes": " ".join(scenes),
        "category": _category_tag(item),
        "url": (item.get("url") or ""),
        "importance": (item.get("importance") or "medium"),
    }


def _thumb_svg(index: int) -> str:
    """返回条目左侧色边颜色（用于 border-left）。"""
    colors = ["#1e4f9c", "#0f766e", "#b45309", "#6d28d9", "#be123c", "#0369a1"]
    return colors[index % len(colors)]


def _item_anchor_id(item: dict[str, Any]) -> str:
    """条目页内锚点 id（供参考建议跳转定位）。"""
    raw = str(item.get("id") or "").strip()
    if not raw:
        title = strip_ai_markers(item.get("title") or "").strip()[:48]
        raw = re.sub(r"\s+", "-", title) if title else "x"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-_")[:96]
    if not safe:
        safe = "x"
    if safe[0].isdigit():
        safe = "n-" + safe
    return f"item-{safe}"


def _card_html(item: dict[str, Any], idx: int, *, section_key: str = "") -> str:
    """横排卡片：默认折叠看标题行；展开只保留来源/延伸/关键/关注点/场景。"""
    # 交叉指引：一行提示，不展开全文
    if item.get("is_section_pointer"):
        tip = _esc(strip_ai_markers(item.get("title") or "交叉指引"))
        return f"""
    <article class="news-row pointer-row" data-collapsed="0">
      <div class="pointer-line">{tip}</div>
    </article>
    """

    f = _item_fields(item)
    title_plain = _esc(f["title"])
    anchor = _item_anchor_id(item)
    sec = (section_key or item.get("section") or "").strip()
    sec_attr = f' data-sec="{_esc(sec)}"' if sec else ""

    legal_html = ""
    if f["legal_focus"]:
        legal_html = (
            f'<p class="field"><strong>法务关注点</strong>'
            f'<span class="field-sep">：</span>{_esc(f["legal_focus"])}</p>'
        )

    # 来源：一行，来源名超链接，分号隔开（不展示网址文本）
    source_links = f.get("source_links") or []
    sources = f.get("sources") or []
    link_bits: list[str] = []
    for link in source_links[:8]:
        url = (link.get("url") or "").strip()
        label = (link.get("label") or "").strip()
        if not label and url:
            try:
                from urllib.parse import urlparse

                host = (urlparse(url).netloc or "").removeprefix("www.")
                label = host or "原文"
            except Exception:
                label = "原文"
        if not label:
            label = "原文"
        if url:
            link_bits.append(
                f'<a class="src-link" href="{_esc(url)}" target="_blank" rel="noopener" '
                f'onclick="event.stopPropagation()">{_esc(label)}</a>'
            )
        elif label != "原文":
            link_bits.append(_esc(label))
    if not link_bits and sources:
        link_bits = [_esc(s) for s in sources[:8]]

    # 展开区：来源与日期同一行（日期跟在来源后）
    date_disp = f["date"] if f["date"] and f["date"] != "—" else ""
    if link_bits and date_disp:
        source_date_html = f'<p class="note">{"；".join(link_bits)} · {_esc(date_disp)}</p>'
    elif link_bits:
        source_date_html = f'<p class="note">{"；".join(link_bits)}</p>'
    elif date_disp:
        source_date_html = f'<p class="note">{_esc(date_disp)}</p>'
    else:
        source_date_html = ""

    # 标题下静注：仅关键词（多枚）；日期与来源放到展开区
    keywords = _item_keywords(item, limit=4)
    meta_line = " · ".join(keywords) if keywords else ""
    meta_html = (
        f'<div class="sum-meta">{_esc(meta_line)}</div>' if meta_line else ""
    )

    # 序号：板块内从 1 开始连续编号（idx < 0 表示不编号，如交叉指引）
    num_html = (
        f'<span class="sum-num" aria-hidden="true">{idx + 1}</span>' if idx >= 0 else ""
    )

    return f"""
    <article class="news-row" id="{_esc(anchor)}" data-collapsed="1"{sec_attr}>
      <button type="button" class="news-toggle" aria-expanded="false" title="展开/折叠本条">
        {num_html}
        <div class="news-summary">
          <div class="sum-title">{title_plain}</div>
          {meta_html}
        </div>
        <span class="chev" aria-hidden="true"></span>
      </button>
      <div class="news-body">
        {source_date_html}
        <p class="field"><strong>关键信息</strong><span class="field-sep">：</span>{_esc(f['key_info'])}</p>
        {legal_html}
      </div>
    </article>
    """


def _section_html(key: str, items: list[dict[str, Any]], *, active: bool = False) -> str:
    """单个板块面板：点哪个看哪个；条目默认折叠。标题由上方 Tab 承担，面板内不再重复。"""
    if not items:
        cards = '<p class="empty">本期本板块暂无精选</p>'
    else:
        parts: list[str] = []
        n = 0
        for it in items:
            if it.get("is_section_pointer"):
                parts.append(_card_html(it, -1, section_key=key))
            else:
                parts.append(_card_html(it, n, section_key=key))
                n += 1
        cards = "".join(parts)
    hidden_attr = "" if active else " hidden"
    return f"""
    <section class="sec-panel" id="{key}" data-sec="{key}"{hidden_attr}>
      <div class="sec-list">{cards}</div>
    </section>
    """


def _section_nav_html(sections: dict[str, Any], active_key: str | None = None) -> str:
    """三板块导航：点哪个只显示哪个板块（不并排堆叠）。"""
    buttons: list[str] = []
    for key in SECTION_ORDER:
        meta = SECTION_META[key]
        items = sections.get(key) or []
        n = len([it for it in items if not it.get("is_section_pointer")])
        active_cls = " is-active" if active_key and key == active_key else ""
        count_html = f'<span class="tab-count">{n}</span>' if n else ""
        buttons.append(
            f'<button type="button" class="sec-tab{active_cls}" data-sec="{key}"'
            f' aria-selected="{"true" if active_cls else "false"}">'
            f'{_esc(meta["label"])}{count_html}</button>'
        )
    return f'<nav class="sec-nav" aria-label="三大板块">{"".join(buttons)}</nav>'


def _collect_week_legal_reference(digest: dict[str, Any]) -> str:
    """汇总本期法务部参考建议（一条，对齐法务职责）。"""
    weekly = digest.get("weekly") or {}
    ai = digest.get("ai_summary") or {}
    sections = digest.get("sections") or {}
    pool: list[dict[str, Any]] = []
    for k in SECTION_ORDER:
        pool.extend(sections.get(k) or [])

    reference = build_week_legal_reference(
        reference=weekly.get("week_legal_reference") or ai.get("week_legal_reference") or "",
        question=weekly.get("week_think_question") or ai.get("week_think_question") or "",
        action=weekly.get("week_action_suggestion") or ai.get("week_action_suggestion") or "",
    )
    if reference:
        return reference

    # 兜底：从条目级字段拼一条参考建议
    generic_q = "该动态是否触发两院在"
    generic_a = "列入本周法务例会观察清单"
    question = ""
    tips: list[str] = []
    for it in pool:
        if not question:
            q = (it.get("think_questions") or "").strip()
            if q and q != "—" and generic_q not in q:
                question = q
        a = (it.get("action_suggestions") or "").strip()
        if a and a != "—" and generic_a not in a and a not in tips:
            tips.append(a)
        if question and tips:
            break

    if not question:
        clue = weekly.get("judgment_clue") or ai.get("judgment_clue") or ""
        titles = [str(it.get("title") or "").strip() for it in pool if it.get("title")]
        title_hint = "；".join(titles[:3]) if titles else ""
        if clue and title_hint:
            question = (
                f"结合本期判断线索「{clue}」与重点动态「{title_hint}」，"
                f"法务部应优先在合同条款、制度审核节点或跨部门把关环节划定合规边界，"
                f"并牵头梳理需修订的条款清单与会签要点。"
            )
        elif clue:
            question = (
                f"结合本期判断线索「{clue}」，法务部应优先复盘制度审核、"
                f"合同全周期管理与跨部门会签把关节点，并输出把关清单。"
            )
        else:
            question = (
                "本期哪些变化可能在一个月内转化为两院的合同审核、制度修订或跨部门合规把关义务？"
                "法务部应优先跟进相关边界，并指定争议风险跟踪人。"
            )
    action = "；".join(tips[:3]) if tips else ""
    if not action:
        mainline = weekly.get("mainline") or ai.get("mainline") or ""
        action = (
            "由法务部牵头对照本期主线，梳理需修订的制度/合同条款与跨部门会签把关要点，"
            "并指定争议风险跟踪人。"
            + (f"（主线：{mainline}）" if mainline else "")
        )
    return build_week_legal_reference(question=question, action=action)


_FLUFF_MARKERS = (
    "便于跨部门会签",
    "便于业务部门",
    "便于技术部门",
    "便于财务",
    "便于技术、财务与科研部门同步会签",
    "便于技术、财务与科研部门",
    "便于跨部门会签明确",
    "防范履约争议与数据安全监管风险",
    "防范履约争议",
    "防范潜在纠纷",
    "防范权属与侵权争议",
    "同步对齐",
    "高度重视",
    "切实做好",
    "赋能",
    "闭环管理",
    "全周期审查清单",
    "跨部门会签并把关",
    "维护合法权益",
    "上述动作旨在",
    "以合规边界把控支撑",
)

# 句尾假大空尾巴：匹配到就砍掉
_FLUFF_TAIL_RE = re.compile(
    r"(?:"
    r"便于[^。]{0,40}|"
    r"以防[^。]{0,30}|"
    r"防范[^。]{0,30}|"
    r"前置阻断[^。]{0,40}|"
    r"支撑两院[^。]{0,40}"
    r")$"
)


def _strip_fluff_phrases(text: str) -> str:
    """去掉假大空套话，保留具体动作。"""
    s = (text or "").strip()
    if not s:
        return ""
    # 去掉「针对《…》，建议法务部」这类铺垫
    s = re.sub(r"^针对[^，。]{0,80}，?", "", s)
    s = re.sub(r"^(?:建议)?法务部(?:将|应|需|可考虑)?", "", s)
    s = re.sub(r"^可考虑", "", s)
    s = re.sub(r"^建议", "", s)
    for fluff in _FLUFF_MARKERS:
        s = s.replace(fluff, "")
    s = _FLUFF_TAIL_RE.sub("", s)
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"（主线：[^）]*）", "", s)
    return s.strip(" ，,；;：:。")


def _is_fluffy_tip(text: str) -> bool:
    s = (text or "").strip()
    if len(s) < 8:
        return True
    fluff_hits = sum(1 for m in _FLUFF_MARKERS if m in s)
    has_object = any(
        x in s
        for x in (
            "合同", "条款", "协议", "采购", "备案", "授权", "数据",
            "名单", "制度", "模板", "验收", "SLA", "权属", "开源",
        )
    )
    if fluff_hits >= 1 and not has_object:
        return True
    if fluff_hits >= 2:
        return True
    if s.startswith(("本期哪些", "由法务部牵头对照本期主线")):
        return True
    # 全是抽象动词、没有可核对对象
    if re.fullmatch(r".{0,6}(?:关注|重视|加强|完善|推进).{0,8}", s):
        return True
    return False


def _normalize_tip_bullet(text: str, *, max_chars: int = 46) -> str:
    """压成一条短建议。"""
    s = soften_alarmist_zh(strip_ai_markers(text or "")).strip()
    s = _strip_fluff_phrases(s)
    if not s or _is_fluffy_tip(s):
        return ""
    s = _clip_guide_sentence(s, max_chars)
    if not s or _is_fluffy_tip(s):
        return ""
    return s


def _item_keywords(item: dict[str, Any], *, limit: int = 4) -> list[str]:
    """条目标题注脚用：整理多个短关键词，便于注释主题。"""
    skip = {
        "未分类", "垂类工具", "资讯", "交叉指引", "法律AI", "国内", "中国",
        "观察", "行业动态", "全球", "国际",
    }
    out: list[str] = []

    def _add(raw: Any) -> None:
        s = re.sub(r"^#", "", str(raw or "")).strip()
        s = re.sub(r"\s+", "", s)
        if not s or s in skip or len(s) > 14:
            return
        if s not in out:
            out.append(s)

    for t in item.get("tags") or []:
        _add(t)
        if len(out) >= limit:
            return out[:limit]
    for s in item.get("impact_scenes") or []:
        _add(s)
        if len(out) >= limit:
            return out[:limit]
    for d in item.get("directions") or []:
        # 选题方向偏长，截短到可注脚长度
        ds = str(d or "").strip()
        if "与" in ds:
            ds = ds.split("与", 1)[0].strip()
        _add(ds[:10])
        if len(out) >= limit:
            return out[:limit]

    title = strip_ai_markers(item.get("title") or "")
    blob = f"{title} {item.get('key_info') or ''} {item.get('legal_focus') or ''}"
    lexicon = (
        "AI裁判", "算法侵权", "责任分配", "算法备案", "数据权属", "智能体",
        "合同审查", "提示词", "开源许可", "成果转化", "科研经费", "反垄断",
        "垄断协议", "国防动员", "科技处罚", "数据出境", "个人信息", "数据安全",
        "法律科技", "云服务", "重点实验室", "知识产权", "产学研", "劳动用工",
        "校园安全", "采购合规", "供应商", "幻觉风险", "模型训练", "Agent",
        "裁判规则", "侵权责任",
    )
    for kw in lexicon:
        if kw.lower() in blob.lower():
            _add(kw)
            if len(out) >= limit:
                return out[:limit]

    # 仍不足时从标题抽中文短语补齐
    if len(out) < 2:
        for frag in re.findall(r"[\u4e00-\u9fff]{2,8}", title):
            if frag in ("明确", "提示", "关注", "发布", "推进", "召开"):
                continue
            _add(frag)
            if len(out) >= limit:
                break
    if not out:
        short = re.split(r"[，,：:｜|（(]", title, maxsplit=1)[0].strip()
        short = re.sub(r"^(本期|关于)", "", short).strip()
        if re.match(r"^[A-Za-z]", short or ""):
            out.append("行业动态")
        elif short:
            out.append(short[:8])
        else:
            out.append("观察")
    return out[:limit]


def _item_keyword(item: dict[str, Any]) -> str:
    """兼容旧调用：取注脚关键词列表的首个。"""
    kws = _item_keywords(item, limit=1)
    return kws[0] if kws else "观察"


def _pool_digest_items(digest: dict[str, Any]) -> list[dict[str, Any]]:
    sections = digest.get("sections") or {}
    pool: list[dict[str, Any]] = []
    for key in SECTION_ORDER:
        for it in sections.get(key) or []:
            if it.get("is_section_pointer"):
                continue
            row = dict(it)
            row["_section"] = key
            if not row.get("section"):
                row["section"] = key
            pool.append(row)
    return pool


def _match_related_item(
    tip: str,
    pool: list[dict[str, Any]],
    *,
    hint_title: str = "",
    used_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """把建议关联回本期真实条目，找不到则返回 None（禁止无中生有）。"""
    used_ids = used_ids or set()
    blob = f"{tip} {hint_title}"
    candidates = list(pool)

    def _score(it: dict[str, Any]) -> int:
        t = strip_ai_markers(it.get("title") or "")
        score = 0
        iid = str(it.get("id") or "")
        if iid and iid in used_ids:
            score -= 2  # 已用过的略降权，避免三条全挂同一条
        for m in re.finditer(r"《([^》]{4,40})》", blob):
            frag = m.group(1).strip()
            if frag in t or t in frag:
                score += 8
        for m in re.finditer(r"「([^」]{4,24})」", blob):
            frag = m.group(1).strip()
            if frag in t or t.startswith(frag):
                score += 6
        tip_compact = re.sub(r"\s+", "", tip)
        for kw in (
            "采购", "备案", "合同", "授权", "验收", "开源", "数据权属",
            "智能体", "Agent", "反垄断", "成果转化", "科研", "指引",
            "留痕", "接口",
        ):
            if kw in tip_compact and kw in t:
                score += 2
        kw = _item_keyword(it)
        if kw and kw in tip_compact:
            score += 3
        if hint_title and (hint_title[:12] in t or t[:12] in hint_title):
            score += 4
        return score

    ranked = sorted((( _score(it), it) for it in candidates), key=lambda x: -x[0])
    if not ranked or ranked[0][0] < 3:
        return None
    return ranked[0][1]


def _tip_row_from_item(item: dict[str, Any], tip_body: str) -> dict[str, str] | None:
    tip = _normalize_tip_bullet(tip_body, max_chars=46)
    if not tip:
        # 可能已带「标题」：前缀，再压一次
        tip = _normalize_tip_bullet(re.sub(r"^「[^」]+」：", "", tip_body), max_chars=46)
    if not tip:
        return None
    title = strip_ai_markers(item.get("title") or "").strip()
    short_t = re.split(r"[，,：:（(]", title, maxsplit=1)[0].strip()[:22]
    sources = _split_sources(item.get("sources_list") or item.get("source"))
    sec = str(item.get("_section") or item.get("section") or "").strip()
    return {
        "tip": tip,
        "keyword": _item_keyword(item),
        "related_title": short_t or title[:22],
        "related_date": format_display_date(item),
        "related_source": (sources[0] if sources else "").strip(),
        "related_id": _item_anchor_id(item),
        "related_section": sec,
    }


def _bullet_from_item(title: str, legal_focus: str, action: str) -> str:
    """从单条资讯提炼一条可执行、不过度套话的建议（纯文本，供内部复用）。"""
    title = strip_ai_markers(title or "").strip()
    focus = soften_alarmist_zh(strip_ai_markers(legal_focus or "")).strip()
    act = soften_alarmist_zh(strip_ai_markers(action or "")).strip()
    src = ""
    for cand in (act, focus):
        if not cand or cand in ("—", "-"):
            continue
        if "例会观察清单" in cand or "该动态是否触发" in cand:
            continue
        src = cand
        break
    if not src:
        return ""
    m = re.search(r"建议([^。！？]+)", src)
    body = _strip_fluff_phrases(m.group(1) if m else src)
    if not body or _is_fluffy_tip(body):
        return ""
    if len(body) > 36:
        body = _clip_guide_sentence(body, 36).rstrip("。")
    return body + ("。" if not body.endswith(("。", "！", "？")) else "")


def _bullets_from_long_reference(ref: str) -> list[str]:
    """把旧版一段式参考建议拆成条目列表。"""
    text = soften_alarmist_zh(strip_ai_markers(ref or "")).strip()
    if not text:
        return []
    chunks: list[str] = []
    for sent in _split_zh_sentences(text):
        parts = re.split(r"(?=可考虑|同时[，,]?|结合《)", sent)
        for p in parts:
            p = p.strip()
            if p:
                chunks.append(p)
    out: list[str] = []
    for chunk in chunks:
        tip = _normalize_tip_bullet(chunk, max_chars=46)
        if tip and tip not in out:
            out.append(tip)
        if len(out) >= 5:
            break
    return out


def _collect_week_legal_tip_rows(digest: dict[str, Any]) -> list[dict[str, str]]:
    """参考建议结构化：建议 + 关键词 + 关联本期条目（必须能对上出处）。"""
    weekly = digest.get("weekly") or {}
    ai = digest.get("ai_summary") or {}
    pool = _pool_digest_items(digest)
    rows: list[dict[str, str]] = []
    seen_tips: set[str] = set()
    used_ids: set[str] = set()

    def _push(row: dict[str, str] | None, related: dict[str, Any] | None = None) -> bool:
        if not row:
            return False
        tip = row.get("tip") or ""
        if not tip or tip in seen_tips:
            return False
        if not (row.get("related_title") or "").strip():
            return False
        seen_tips.add(tip)
        rows.append(row)
        if related and related.get("id"):
            used_ids.add(str(related.get("id")))
        return len(rows) >= 5

    raw_items = weekly.get("week_legal_reference_items") or ai.get("week_legal_reference_items")
    if isinstance(raw_items, list):
        for x in raw_items:
            if isinstance(x, dict):
                tip = _normalize_tip_bullet(str(x.get("tip") or x.get("text") or x.get("action") or ""))
                hint = str(x.get("related_title") or x.get("source_title") or x.get("title") or "")
                kw = str(x.get("keyword") or "").strip()
                related = _match_related_item(tip, pool, hint_title=hint, used_ids=used_ids)
                if related:
                    row = _tip_row_from_item(related, tip or str(x.get("tip") or ""))
                    if row and kw:
                        row["keyword"] = kw[:12]
                    if _push(row, related):
                        return rows
                continue
            tip = _normalize_tip_bullet(str(x or ""))
            related = _match_related_item(tip, pool, used_ids=used_ids)
            if related and _push(_tip_row_from_item(related, tip), related):
                return rows

    # 旧长文：拆句后必须能关联到本期条目；《标题》写进 hint 便于对号入座
    ref = build_week_legal_reference(
        reference=weekly.get("week_legal_reference") or ai.get("week_legal_reference") or "",
        question=weekly.get("week_think_question") or ai.get("week_think_question") or "",
        action=weekly.get("week_action_suggestion") or ai.get("week_action_suggestion") or "",
    )
    book_titles = re.findall(r"《([^》]{4,40})》", ref)
    for i, tip in enumerate(_bullets_from_long_reference(ref)):
        hint = book_titles[i] if i < len(book_titles) else "》".join(book_titles)
        if book_titles and i < len(book_titles):
            hint = book_titles[i]
        elif book_titles:
            # 轮询分配书名号标题，减少三条全挂同一条
            hint = book_titles[i % len(book_titles)]
        related = _match_related_item(tip, pool, hint_title=hint or ref[:80], used_ids=used_ids)
        if related and _push(_tip_row_from_item(related, tip), related):
            return rows
    if len(rows) >= 3:
        return rows

    # 从条目直接提炼（出处最清楚）
    for it in pool:
        tip = _bullet_from_item(
            str(it.get("title") or ""),
            str(it.get("legal_focus") or ""),
            str(it.get("action_suggestions") or ""),
        )
        if tip and _push(_tip_row_from_item(it, tip), it):
            return rows

    return rows


def _collect_week_legal_bullets(digest: dict[str, Any]) -> list[str]:
    """兼容旧接口：只返回建议正文列表。"""
    return [r["tip"] for r in _collect_week_legal_tip_rows(digest) if r.get("tip")]


def _collect_weekly_qa(digest: dict[str, Any]) -> tuple[str, str]:
    """兼容旧接口：返回 (参考建议, '')。"""
    ref = _collect_week_legal_reference(digest)
    return ref, ""


def _actions_html(digest: dict[str, Any]) -> str:
    """三大板块之后：法务部参考建议（建议正文可跳转至关联条目）。"""
    tip_rows = _collect_week_legal_tip_rows(digest)
    lis_parts: list[str] = []
    for row in tip_rows:
        tip = _esc(row.get("tip") or "")
        anchor = (row.get("related_id") or "").strip()
        sec = (row.get("related_section") or "").strip()
        if tip and anchor:
            lis_parts.append(
                f'<li><a class="closing-tip-link" href="#{_esc(anchor)}" '
                f'data-sec="{_esc(sec)}" data-item="{_esc(anchor)}">{tip}</a></li>'
            )
        elif tip:
            lis_parts.append(f'<li><div class="closing-tip">{tip}</div></li>')
    if not lis_parts:
        lis_parts.append(
            '<li><div class="closing-tip">本期暂无足够明确的条目支撑可执行建议。</div></li>'
        )
    lis = "".join(lis_parts)
    return f"""
    <section class="closing-sec" id="week-closing">
      <div class="closing-label">{WEEK_LEGAL_REFERENCE_LABEL}</div>
      <ul class="closing-list">{lis}</ul>
    </section>
    """


def _header_fields(digest: dict[str, Any]) -> dict[str, str]:
    weekly = digest.get("weekly") or {}
    ai = digest.get("ai_summary") or {}
    brand = weekly.get("brand") or "法律AI每周资讯"
    vol = weekly.get("vol") or digest.get("vol") or 1
    try:
        vol_n = int(vol)
    except (TypeError, ValueError):
        vol_n = vol
    clue = soften_alarmist_zh(
        strip_ai_markers(weekly.get("judgment_clue") or ai.get("judgment_clue") or "")
    )
    mainline = soften_alarmist_zh(
        strip_ai_markers(
            weekly.get("mainline") or ai.get("mainline") or "（本期主线待提炼）"
        )
    )
    # 本期聚焦：主句 + 补充，短、轻、可扫读
    focus_lead, focus_sub = _focus_pair(clue, mainline)
    focus = focus_lead + focus_sub
    date_line = weekly.get("date_range") or (digest.get("generated_at") or "")[:10]
    # 右上角：日期区间 + 期号/测试期
    short_date = date_line
    if "至" in date_line:
        a, b = date_line.split("至", 1)
        a = a.strip()[:10].replace("-", ".")
        b = b.strip()[:10].replace("-", ".")
        short_date = f"{a}-{b}"
    issue_label = (weekly.get("issue_label") or "").strip()
    if weekly.get("test_issue") or issue_label in ("测试期", "试刊", "测试"):
        issue_part = issue_label or "测试期"
    else:
        issue_part = f"第{vol_n}期"
    vol_line = f"{short_date} · {issue_part}"
    return {
        "title": format_title(brand, vol),
        "subtitle": "",  # 副题「两院法务 · AI 与全球合规观察」已取消对外展示
        "org": weekly.get("org") or "中关村学院 · 中关村人工智能研究院法务",
        "date": date_line,
        "vol_line": vol_line,
        "mainline": mainline,
        "clue": clue or "关注 AI/数据监管对两院管理场景的传导",
        "focus": focus,
        "focus_lead": focus_lead,
        "focus_sub": focus_sub,
    }

def digest_to_html(
    digest: dict[str, Any],
    weeks: list[dict[str, Any]] | None = None,
    current_id: str | None = None,
) -> str:
    """参考 glebis/tufte-report 配色：暖纸底 + 少用强调色。

    weeks: 期次下拉数据 [{"id","label","href","current"}]；为 None 时不渲染期次选择器。
    """
    h = _header_fields(digest)
    sections = digest.get("sections") or {}
    # 三大栏目互斥；默认高亮两院法务（若为空则顺延第一个有内容的栏目）
    active_key = "two_institute"
    if not (sections.get(active_key) or []):
        active_key = next((k for k in SECTION_ORDER if sections.get(k)), SECTION_ORDER[0])
    body = "".join(
        _section_html(k, sections.get(k) or [], active=(k == active_key))
        for k in SECTION_ORDER
    )
    sec_nav = _section_nav_html(sections, active_key)
    actions = _actions_html(digest)
    disclaimer = "仅供两院法务内部使用"

    # 期次选择器：列出全部已归档期次，选中即跳转
    if weeks:
        opts: list[str] = []
        for w in weeks:
            label = _esc(w.get("label") or w.get("id") or "")
            is_cur = (
                (w.get("id") == current_id) if current_id else bool(w.get("current"))
            )
            if is_cur:
                opts.append(f'<option value="" selected>{label}</option>')
            else:
                href = _esc(w.get("href") or "")
                opts.append(f'<option value="{href}">{label}</option>')
        vol_html = (
            '<select class="week-select" id="weekSelect" aria-label="选择期次">'
            + "".join(opts)
            + "</select>"
        )
    else:
        vol_html = f'<div class="vol-line">{_esc(h["vol_line"])}</div>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=3, user-scalable=yes" />
  <meta name="format-detection" content="telephone=no" />
  <title>{_esc(h['title'])}</title>
  <style>
    :root {{
      /* 参考 glebis/tufte-report 配色：暖纸底 + 少用强调色 */
      --ink: #1a1a1a;
      --ink-light: #555555;
      --ink-muted: #888888;
      --bg: #fffff8;
      --bg-aside: #f9f6ee;
      --accent: #a00000;
      --rule: #cccccc;
      --spark: #c45a28;
      --card: #fffff8;
      --soft: #f9f6ee;
      /* 兼容旧变量名 */
      --muted: var(--ink-muted);
      --line: var(--rule);
      --navy: #2a508c;
      --navy-deep: #1a1a1a;
      --orange: var(--spark);
    }}
    html[data-theme="dark"] {{
      --ink: #e8e4d9;
      --ink-light: #b8b4a8;
      --ink-muted: #8a8680;
      --bg: #1a1916;
      --bg-aside: #24221e;
      --accent: #e07070;
      --rule: #3a3832;
      --spark: #d4784a;
      --card: #1a1916;
      --soft: #24221e;
      --navy: #8eb0d8;
      --navy-deep: #e8e4d9;
      --orange: var(--spark);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Serif SC", "Songti SC", serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.65;
      font-size: 16px;
      transition: background-color 0.2s ease, color 0.2s ease;
    }}
    .wrap {{ max-width: 820px; margin: 0 auto; padding: 32px 20px 72px; }}

    .top-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 0 0 20px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--rule);
    }}
    .top-org {{
      text-align: left;
      color: var(--ink-muted);
      font-size: 0.72rem;
      letter-spacing: 0.14em;
      margin: 0;
      flex: 1;
    }}
    .theme-toggle {{
      border: 1px solid var(--rule);
      background: var(--bg-aside);
      color: var(--ink-light);
      font: inherit;
      font-size: 0.78rem;
      padding: 5px 12px;
      cursor: pointer;
      white-space: nowrap;
    }}
    .theme-toggle:hover {{
      color: var(--ink);
      border-color: var(--ink-muted);
    }}
    .mast {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 22px;
    }}
    .brand {{
      margin: 0;
      font-size: clamp(1.55rem, 4vw, 1.95rem);
      font-weight: 600;
      color: var(--ink);
      letter-spacing: 0.02em;
    }}
    .subtitle {{ margin: 6px 0 0; color: var(--ink-light); font-size: 0.95rem; }}
    .vol-line {{
      color: var(--ink-muted);
      font-size: 0.78rem;
      white-space: nowrap;
      padding-bottom: 4px;
      font-variant-numeric: tabular-nums;
    }}
    /* 期次选择器 */
    .mast-right {{
      flex-shrink: 0;
      padding-bottom: 4px;
    }}
    .week-select {{
      font: inherit;
      font-size: 0.78rem;
      color: var(--ink-light);
      background: var(--bg-aside);
      border: 1px solid var(--rule);
      border-radius: 0;
      padding: 4px 8px;
      cursor: pointer;
      font-variant-numeric: tabular-nums;
      max-width: 240px;
    }}
    .week-select:hover {{
      color: var(--ink);
      border-color: var(--ink-muted);
    }}
    .week-select:focus {{
      outline: 1px solid var(--accent);
      outline-offset: 1px;
    }}

    .hero {{
      background: var(--bg-aside);
      border: 1px solid var(--rule);
      border-left: 3px solid var(--accent);
      border-radius: 0;
      padding: 16px 20px 18px;
      margin-bottom: 22px;
    }}
    .hero-badge {{
      display: block;
      color: var(--accent);
      font-size: 0.68rem;
      font-weight: 600;
      letter-spacing: 0.18em;
      margin: 0 0 10px;
      line-height: 1.2;
    }}
    .hero-lead {{
      margin: 0;
      font-size: clamp(1.08rem, 2.4vw, 1.28rem);
      line-height: 1.55;
      font-weight: 600;
      color: var(--ink);
    }}
    .hero-sub {{
      margin: 12px 0 0;
      padding-top: 10px;
      border-top: 1px solid var(--rule);
      font-size: 0.92rem;
      line-height: 1.7;
      font-weight: 400;
      color: var(--ink-light);
      font-style: italic;
    }}

    .sec-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0;
      margin: 0 0 18px;
      border-bottom: 1px solid var(--rule);
    }}
    .sec-tab {{
      border: 0;
      border-bottom: 2px solid transparent;
      background: transparent;
      color: var(--ink-light);
      border-radius: 0;
      padding: 10px 14px 12px;
      margin-bottom: -1px;
      font-size: 0.92rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
    }}
    .sec-tab:hover {{ color: var(--ink); }}
    .sec-tab.is-active {{
      background: transparent;
      border-bottom-color: var(--accent);
      color: var(--ink);
      font-weight: 650;
    }}
    .sec-tab .tab-count {{
      font-size: 0.72rem;
      font-weight: 400;
      color: var(--ink-muted);
      font-variant-numeric: tabular-nums;
    }}
    .sec-tab.is-active .tab-count {{
      color: var(--ink-light);
    }}
    .sec-tip {{ display: none; }}

    .sec-panel {{
      margin: 0 0 28px;
      background: transparent;
      border: 0;
      border-radius: 0;
      overflow: visible;
      scroll-margin-top: 16px;
    }}
    .sec-panel[hidden] {{ display: none; }}
    .sec-list {{ padding: 4px 0 0; }}
    .pointer-row {{
      border-bottom: 1px solid var(--rule);
      background: var(--bg-aside);
    }}
    .pointer-line {{
      padding: 10px 4px;
      color: var(--ink-light);
      font-size: 0.9rem;
      line-height: 1.55;
      font-style: italic;
    }}

    .news-row {{
      border-bottom: 1px solid var(--rule);
      padding: 2px 0;
    }}
    .news-row:last-child {{ border-bottom: none; }}
    .news-toggle {{
      width: 100%;
      display: grid;
      grid-template-columns: 26px 1fr 18px;
      gap: 12px;
      align-items: center;
      border: 0;
      border-left: 2px solid var(--rule);
      background: transparent;
      text-align: left;
      padding: 14px 4px 12px 12px;
      cursor: pointer;
      font: inherit;
      color: inherit;
      border-radius: 0;
    }}
    .news-toggle:hover {{
      background: var(--bg-aside);
      border-left-color: var(--spark);
    }}
    .news-summary {{ min-width: 0; }}
    .sum-num {{
      align-self: start;
      padding-top: 2px;
      font-size: 0.84rem;
      font-weight: 600;
      line-height: 1.45;
      color: var(--ink-muted);
      font-variant-numeric: tabular-nums;
      text-align: right;
    }}
    .sum-title {{
      font-size: 1.06rem;
      font-weight: 650;
      line-height: 1.45;
      color: var(--ink);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .sum-meta {{
      margin-top: 5px;
      color: var(--ink-muted);
      font-size: 0.78rem;
      font-style: italic;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .chev {{
      width: 7px; height: 7px;
      border-right: 1.5px solid var(--ink-muted);
      border-bottom: 1.5px solid var(--ink-muted);
      transform: rotate(45deg);
      transition: transform 160ms ease;
      justify-self: end;
    }}
    .news-row[data-collapsed="0"] .chev {{ transform: rotate(225deg); margin-top: 4px; }}
    .news-body {{
      display: none;
      padding: 4px 8px 16px 14px;
      margin-top: 0;
      border-top: 0;
    }}
    .news-row[data-collapsed="0"] .news-body {{ display: block; }}
    .news-row[data-collapsed="0"] .sum-title {{ -webkit-line-clamp: unset; }}
    .thumb, .cat, .sec-count, .sec-tags, .sec-pos {{ display: none; }}
    .note {{
      margin: 0 0 8px;
      color: var(--ink-muted);
      font-size: 0.78rem;
      font-style: italic;
      line-height: 1.5;
    }}
    .field {{
      margin: 8px 0;
      color: var(--ink-light);
      font-size: 0.92rem;
      line-height: 1.7;
      font-weight: 400;
    }}
    .field strong {{
      color: var(--ink);
      font-weight: 650;
      font-size: 0.84rem;
      letter-spacing: 0.02em;
      margin-right: 0;
    }}
    .field-sep {{
      color: var(--ink-muted);
      margin: 0 0.35em;
      font-weight: 400;
    }}
    .news-title {{
      margin: 0 0 6px;
      font-size: 1.02rem;
      line-height: 1.4;
      font-weight: 700;
    }}
    .news-title a {{ color: var(--ink); text-decoration: none; }}
    .news-title a:hover {{ color: var(--navy); }}
    .news-desc {{
      margin: 0 0 6px;
      color: var(--ink-light);
      font-size: 0.9rem;
    }}
    .news-meta {{
      margin: 0 0 6px;
      color: var(--ink-muted);
      font-size: 0.8rem;
    }}
    .field-list {{
      margin: 4px 0 0;
      padding-left: 1.35em;
    }}
    .field-list li {{ margin: 2px 0; }}
    .title-field {{
      font-size: 1.02rem;
      font-weight: 600;
      margin-top: 2px;
    }}
    .title-field a {{ color: var(--ink); text-decoration: none; }}
    .title-field a:hover {{ color: var(--navy); }}
    .src-label {{ color: var(--ink-light); margin-right: 4px; }}
    .src-url {{
      color: var(--navy);
      font-size: 0.86rem;
      word-break: break-all;
      text-decoration: none;
    }}
    .src-url:hover {{ text-decoration: underline; }}
    .src-line {{ color: var(--ink-light); }}
    .src-link {{
      color: var(--navy);
      text-decoration: none;
      border-bottom: 1px solid transparent;
    }}
    .src-link:hover {{ border-bottom-color: var(--navy); }}
    .detail-link {{ display: none; }}
    .kw-link {{
      color: var(--navy);
      font-size: 0.86rem;
      text-decoration: none;
      font-weight: 600;
    }}
    .kw-link.muted {{ color: var(--ink-muted); font-weight: 500; }}
    .arrow {{ margin-left: 2px; }}

    .closing-sec {{
      margin: 36px 0 20px;
      background: var(--bg-aside);
      border: 1px solid var(--rule);
      border-left: 3px solid var(--accent);
      border-radius: 0;
      padding: 16px 20px 14px;
    }}
    .closing-label {{
      color: var(--accent);
      font-weight: 600;
      font-size: 0.68rem;
      letter-spacing: 0.16em;
      margin: 0 0 10px;
    }}
    .closing-list {{
      margin: 0;
      padding: 0 0 0 1.15em;
      color: var(--ink-light);
      font-size: 0.95rem;
      line-height: 1.65;
      list-style: disc;
    }}
    .closing-list li {{
      margin: 0 0 10px;
      padding-left: 0.1em;
    }}
    .closing-list li:last-child {{ margin-bottom: 0; }}
    .closing-tip {{
      margin: 0;
      color: var(--ink-light);
    }}
    .closing-tip-link {{
      color: var(--ink);
      text-decoration: none;
      border-bottom: 1px solid transparent;
      transition: color 0.15s ease, border-color 0.15s ease;
    }}
    .closing-tip-link:hover {{
      color: var(--accent);
      border-bottom-color: var(--accent);
    }}
    .news-row.is-target {{
      outline: 1px solid var(--accent);
      outline-offset: 2px;
      background: var(--bg-aside);
    }}
    .closing-line {{
      margin: 0;
      color: var(--ink-light);
      font-size: 0.95rem;
      line-height: 1.75;
      font-weight: 400;
    }}
    .closing-line strong {{
      display: block;
      color: var(--accent);
      font-weight: 600;
      font-size: 0.68rem;
      letter-spacing: 0.16em;
      margin-bottom: 8px;
      font-style: normal;
    }}
    .actions-sec {{ display: none; }}
    .act-grid, .gc-box, .q-box, .act-card, .act-n, .actions-banner {{ display: none; }}

    .empty {{ color: var(--ink-muted); padding: 8px 0; font-style: italic; }}
    footer {{
      margin-top: 28px;
      padding-top: 16px;
      border-top: 1px solid var(--rule);
      color: var(--ink-muted);
      font-size: 0.78rem;
      text-align: center;
    }}
    @media (max-width: 720px) {{
      .mast {{ flex-direction: column; align-items: flex-start; }}
      .sec-nav {{ flex-direction: column; border-bottom: 0; gap: 0; }}
      .sec-tab {{
        width: 100%;
        justify-content: space-between;
        border-bottom: 1px solid var(--rule);
        padding: 12px 4px;
      }}
      .sec-tab.is-active {{ border-bottom-color: var(--accent); }}
      .news-toggle {{ grid-template-columns: 22px 1fr 16px; padding-left: 10px; }}
      .news-body {{ padding-left: 12px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top-bar">
      <p class="top-org">{_esc(h['org'])}</p>
      <button type="button" class="theme-toggle" id="themeToggle" aria-label="切换明暗主题">暗色</button>
    </div>
    <header class="mast">
      <div>
        <p class="brand">{_esc(h['title'])}</p>
      </div>
      <div class="mast-right">{vol_html}</div>
    </header>

    <section class="hero">
      <div class="hero-badge">本期聚焦</div>
      <p class="hero-lead">{_esc(h['focus_lead'])}</p>
    </section>

    {sec_nav}
    {body}
    {actions}

    <footer class="foot">
      <p>{disclaimer}</p>
    </footer>
  </div>
  <script>
    (function () {{
      // 钉钉内嵌浏览器强制按宽屏渲染
      (function () {{
        var ua = navigator.userAgent || '';
        if (/DingTalk/.test(ua) || /aliapp/.test(ua)) {{
          var vp = document.querySelector('meta[name="viewport"]');
          if (vp) vp.setAttribute('content', 'width=1200, initial-scale=1, maximum-scale=3, user-scalable=yes');
          document.documentElement.style.minWidth = '1200px';
          document.body.style.minWidth = '1200px';
        }}
      }})();

      var root = document.documentElement;
      var themeBtn = document.getElementById("themeToggle");
      function applyTheme(mode) {{
        if (mode === "dark") root.setAttribute("data-theme", "dark");
        else root.removeAttribute("data-theme");
        if (themeBtn) themeBtn.textContent = mode === "dark" ? "亮色" : "暗色";
        try {{ localStorage.setItem("weekly-theme", mode); }} catch (e) {{}}
      }}
      var saved = "";
      try {{ saved = localStorage.getItem("weekly-theme") || ""; }} catch (e) {{}}
      // 默认强制亮色，不跟随系统 prefers-color-scheme
      applyTheme(saved === "dark" ? "dark" : "light");
      if (themeBtn) {{
        themeBtn.addEventListener("click", function () {{
          var dark = root.getAttribute("data-theme") === "dark";
          applyTheme(dark ? "light" : "dark");
        }});
      }}

      // 期次切换
      var weekSel = document.getElementById("weekSelect");
      if (weekSel) {{
        weekSel.addEventListener("change", function () {{
          var href = weekSel.value;
          if (href) window.location.href = href;
        }});
      }}

      function setItem(row, open) {{
        row.setAttribute("data-collapsed", open ? "0" : "1");
        var btn = row.querySelector(".news-toggle");
        if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
      }}
      document.querySelectorAll(".news-toggle").forEach(function (btn) {{
        btn.addEventListener("click", function () {{
          var row = btn.closest(".news-row");
          if (!row) return;
          setItem(row, row.getAttribute("data-collapsed") !== "0");
        }});
      }});
      function showSec(key) {{
        document.querySelectorAll(".sec-panel").forEach(function (panel) {{
          var on = panel.getAttribute("data-sec") === key;
          if (on) panel.removeAttribute("hidden");
          else panel.setAttribute("hidden", "");
        }});
        document.querySelectorAll(".sec-tab").forEach(function (tab) {{
          var on = tab.getAttribute("data-sec") === key;
          tab.classList.toggle("is-active", on);
          tab.setAttribute("aria-selected", on ? "true" : "false");
        }});
      }}
      document.querySelectorAll(".sec-tab").forEach(function (tab) {{
        tab.addEventListener("click", function () {{
          showSec(tab.getAttribute("data-sec"));
        }});
      }});
      function jumpToItem(anchorId, secKey) {{
        if (!anchorId) return;
        var row = document.getElementById(anchorId);
        if (!row) return;
        var sec = secKey || row.getAttribute("data-sec") || "";
        if (sec) showSec(sec);
        setItem(row, true);
        document.querySelectorAll(".news-row.is-target").forEach(function (el) {{
          el.classList.remove("is-target");
        }});
        row.classList.add("is-target");
        row.scrollIntoView({{ behavior: "smooth", block: "center" }});
        window.setTimeout(function () {{ row.classList.remove("is-target"); }}, 2200);
      }}
      document.querySelectorAll(".closing-tip-link").forEach(function (a) {{
        a.addEventListener("click", function (ev) {{
          ev.preventDefault();
          jumpToItem(a.getAttribute("data-item") || "", a.getAttribute("data-sec") || "");
        }});
      }});
      if (location.hash && location.hash.indexOf("#item-") === 0) {{
        jumpToItem(location.hash.slice(1), "");
      }}
    }})();
  </script>
</body>
</html>
"""



def digest_to_template_markdown(digest: dict[str, Any]) -> str:
    """飞书可贴的简洁文本版（无待人审）。"""
    h = _header_fields(digest)
    lines = [
        h["org"],
        h["title"],
        h["vol_line"],
        "",
        "本期聚焦",
        h["focus_lead"],
        "",
    ]
    sections = digest.get("sections") or {}
    for key in SECTION_ORDER:
        meta = SECTION_META[key]
        lines.append(f"## {meta['label']}")
        lines.append("")
        items = sections.get(key) or []
        if not items:
            lines.append("本期本板块暂无精选")
            lines.append("")
            continue
        for it in items:
            if it.get("is_section_pointer"):
                lines.append(str(it.get("title") or ""))
                lines.append("")
                continue
            f = _item_fields(it)
            lines.append(f"### {f['title']}")
            lines.append(f"{f['date'] or '—'} · {f['region']}")
            links = f.get("source_links") or []
            if links:
                bits = []
                for link in links:
                    url = (link.get("url") or "").strip()
                    label = (link.get("label") or "").strip() or "原文"
                    if url:
                        bits.append(f"[{label}]({url})")
                    else:
                        bits.append(label)
                lines.append("来源：" + "；".join(bits))
            else:
                lines.append(f"来源：{f['source']}")
            lines.append(f"关键信息：{f['key_info']}")
            if f["legal_focus"]:
                lines.append(f"法务关注点：{f['legal_focus']}")
            lines.append(f"影响场景：{f['impact_scenes']}")
            lines.append("")

    # 三大板块之后：法务部参考建议（可跳转关联条目，不再附脚注）
    tip_rows = _collect_week_legal_tip_rows(digest)
    lines.append(f"{WEEK_LEGAL_REFERENCE_LABEL}：")
    for row in tip_rows:
        tip = row.get("tip") or ""
        if tip:
            lines.append(f"- {tip}")
    lines.append("")
    lines.append("仅供两院法务内部使用")
    lines.append("")
    return "\n".join(lines)
