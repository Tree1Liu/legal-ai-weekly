# -*- coding: utf-8 -*-
"""三大板块组织策略：定位、分类主位、重叠时次位一行指引。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from utils import make_id

logger = logging.getLogger(__name__)

# 展示顺序：两院法务 → 法律AI/合规实务 → 全球AI治理
SECTION_ORDER = ("two_institute", "legal_ai", "global_ai")

SECTION_STRATEGY: dict[str, dict[str, Any]] = {
    "two_institute": {
        "label": "两院法务",
        "label_full": "一、两院法务",
        "positioning": "本周哪些立法、司法、执法、监管动态直接关系两院业务",
        "topics": [
            "中国法律法规/部门规章/规范性文件/司法解释/指导性案例/行政执法/监管处罚/行业标准",
            "北京地方监管；教育/科研/事业单位/民非/基金会合规；高校法务典型案例",
            "数据/算法/AI直接监管",
            "最高院/最高检/互联网法院/知产法院发布的与AI、数据、科研、教育相关的裁判规则与典型案例",
            "科研经费、科技伦理、人类遗传资源、博士培养、未成年人保护、院企联合实验室、孵化投资等两院场景",
        ],
        "tags": ["立法司法", "监管执法", "教育科研", "数据算法"],
    },
    "legal_ai": {
        "label": "法律 AI / 合规实务",
        "label_full": "二、法律AI/合规实务",
        "positioning": "法律行业、法务职能如何应对AI、合规体系如何搭建、对方法务在做什么",
        "topics": [
            "法律AI工具迭代（合同审查/法律检索/合规审查/知识管理/法务数据中台）",
            "红圈所/头部企业法务团队AI落地与合规体系实务案例",
            "AI合规体系搭建方法论、合规风险评估、供应商合规调查、合同智能化审查",
            "法律科技行业重要动态（融资、并购、重大产品、监管许可）",
            "AI时代法律职业研究、法务数字化转型研究（有数据、有案例、有可借鉴做法）",
        ],
        "tags": ["垂类工具", "合规实务", "法务数字化"],
    },
    "global_ai": {
        "label": "全球 AI 治理",
        "label_full": "三、全球AI治理与产业动态",
        "positioning": "AI大方向上全球在发生什么规则变化",
        "topics": [
            "主要经济体AI立法/修法/执法重要节点（EU AI Act、美国州级立法、英日新加澳加等）",
            "国际AI标准（ISO/IEC、IEEE、NIST）重大发布或征求意见",
            "跨境AI治理合作（G7/OECD/UN/APEC）与跨境执法协作",
            "具有全球性合规影响的AI安全事件、重大处罚与标杆司法案例",
        ],
        "tags": ["全球治理", "跨境执法", "国际标准"],
    },
}

# 规则计分：读者视角主位（同分：两院 > 法律AI > 全球）
SECTION_RULES: list[tuple[str, str]] = [
    (
        "global_ai",
        r"EU AI Act|联合国.?AI|G7|OECD|APEC|NIST|ISO.?IEC|IEEE.?AI|"
        r"FTC|白宫|ICO|PDPC|GDPR.?AI|跨境执法|"
        r"美国.?AI.?行政令|欧盟委员会.?AI",
    ),
    (
        "legal_ai",
        r"法律科技|LegalTech|法律AI|法务AI|合同审查|法律检索|文书生成|知识管理|"
        r"法务团队|法律职业|合规工具|AI辅助办案|法律大模型|合同管理.?AI|"
        r"企业AI治理|法务数字化|法务落地|垂类工具|合规体系.?搭建|"
        r"律所.{0,12}(AI|人工智能|数字化|科技|白皮书|合规)|"
        r"(AI|人工智能|数字化).{0,12}(律所|法务)|"
        r"智慧法治|法治合规平台|AlphaGPT|法律人.?AI|"
        r"MyLegalAI|法天使|元典|智合|豆包|扣子|Coze|WorkBuddy|AIpha|Alpha|"
        r"Harvey|Ironclad|法智易|通义法睿",
    ),
    (
        "two_institute",
        r"高校|科研经费|科研项目|成果转化|民非|基金会|捐赠|新型研发|事业单位|"
        r"中关村|北京市科委|科技行政处罚|算法备案|生成式人工智能|深度合成|"
        r"个人信息|数据安全|数据出境|数据跨境|重要数据|数据分级|"
        r"国防动员|重点实验室|人类遗传|科技伦理|科研诚信|"
        r"反垄断|垄断协议|市场监管总局|"
        r"教育.?培训合同|人事.?用工|劳务派遣|劳动合同|服务期|"
        r"知识产权.{0,8}(转化|归属|许可|检察)|未成年人|"
        r"司法解释|指导性案例|公报案例|行政处罚|约谈|"
        r"互联网法院|知识产权法院|最高人民.?法院|最高人民.?检察",
    ),
]

SECTION_LABELS = {k: v["label_full"] for k, v in SECTION_STRATEGY.items()}
SECTION_LABELS_SHORT = {k: v["label"] for k, v in SECTION_STRATEGY.items()}


def classify_section(text: str) -> str:
    """按组织策略计分定主位。

    无命中时默认 legal_ai（不再默认两院），避免泛政务/外事资讯刷屏两院栏。
    """
    scores = {name: 0 for name, _ in SECTION_RULES}
    for name, pattern in SECTION_RULES:
        hits = re.findall(pattern, text or "", re.I)
        scores[name] = len(hits)
    best = max(scores.values()) if scores else 0
    if best <= 0:
        return "legal_ai"
    # 同分优先：两院 > 法律AI > 全球（仅当两院确实有分）
    for name in ("two_institute", "legal_ai", "global_ai"):
        if scores.get(name, 0) == best:
            return name
    return "legal_ai"


def _pointer_item(primary_sec: str, primary_title: str, secondary_sec: str) -> dict[str, Any]:
    """次要板块一行指引，不重复全文。"""
    pri_label = SECTION_LABELS_SHORT.get(primary_sec, primary_sec)
    tip = f"🔗{primary_title} 详见「{pri_label}」"
    return {
        "id": make_id(f"ptr:{secondary_sec}:{primary_sec}:{primary_title}", tip),
        "title": tip,
        "is_section_pointer": True,
        "pointer_to": primary_sec,
        "pointer_title": primary_title,
        "section": secondary_sec,
        "section_label": SECTION_LABELS.get(secondary_sec, secondary_sec),
        "source": "",
        "sources_list": [],
        "source_urls": [],
        "key_info": "",
        "legal_focus": "",
        "impact_scenes": [],
        "impact_scene_tags": [],
        "extended_source": "—",
        "url": "",
        "importance": "low",
        "tags": ["交叉指引"],
        "review_status": "approved",
    }


def reorganize_sections_by_strategy(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """按组织策略重排三大板块；重叠时主位全文、次位一行指引。优先 LLM。"""
    digest = dict(digest)
    sections = dict(digest.get("sections") or {})
    # 展平（去掉旧指引）
    pool: list[dict[str, Any]] = []
    for key in SECTION_ORDER:
        for it in sections.get(key) or []:
            if it.get("is_section_pointer"):
                continue
            pool.append(dict(it))
    if not pool:
        return digest

    assigned = _llm_reorganize(pool, cfg)
    if not assigned:
        assigned = _rule_reorganize(pool)

    new_sections: dict[str, list[dict[str, Any]]] = {k: [] for k in SECTION_ORDER}
    # 先放全文；空主位 = 过不了门槛，宁缺毋滥（不再默认塞进两院）
    for row in assigned:
        sec = row.get("section")
        if sec not in new_sections:
            logger.info("改挂后丢弃：%s", (row.get("title") or "")[:60])
            continue
        row["section"] = sec
        row["section_label"] = SECTION_LABELS.get(sec, sec)
        row.pop("is_section_pointer", None)
        new_sections[sec].append(row)

    # 再放次位指引（每板块最多 2 条，避免刷屏）
    ptr_budget: dict[str, int] = {k: 0 for k in SECTION_ORDER}
    seen_ptr: set[str] = set()
    for row in assigned:
        primary = row.get("section") or "two_institute"
        title = (row.get("title") or "").strip()
        for sec in row.get("also_in") or []:
            if sec not in new_sections or sec == primary or not title:
                continue
            if ptr_budget[sec] >= 2:
                continue
            key = f"{sec}|{primary}|{title}"
            if key in seen_ptr:
                continue
            seen_ptr.add(key)
            new_sections[sec].append(_pointer_item(primary, title, sec))
            ptr_budget[sec] += 1

    digest["sections"] = new_sections
    digest["items"] = [it for k in SECTION_ORDER for it in new_sections[k]]
    digest["section_strategy"] = {
        k: {
            "positioning": SECTION_STRATEGY[k]["positioning"],
            "topics": SECTION_STRATEGY[k]["topics"],
        }
        for k in SECTION_ORDER
    }
    counts = dict(digest.get("counts") or {})
    counts["by_section"] = {k: len(new_sections[k]) for k in SECTION_ORDER}
    digest["counts"] = counts
    return digest


def _rule_reorganize(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in pool:
        text = " ".join(
            [
                str(it.get("title") or ""),
                str(it.get("key_info") or ""),
                " ".join(it.get("original_titles") or []),
                " ".join(it.get("tags") or []),
            ]
        )
        primary = _fix_primary_section(it, classify_section(text))
        scores = {name: len(re.findall(pat, text, re.I)) for name, pat in SECTION_RULES}
        also = []
        for name, sc in scores.items():
            if name == primary:
                continue
            if sc >= 2 and sc >= scores.get(primary, 0):
                also.append(name)
        if primary == "two_institute":
            also = [a for a in also if a != "legal_ai"]
        row = dict(it)
        row["section"] = primary
        row["also_in"] = also[:1]
        out.append(row)
    return out


def _llm_reorganize(pool: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]] | None:
    from summarize import _call_openai_compatible, _llm_endpoints

    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        return None

    strategy_brief = {
        k: {
            "定位": SECTION_STRATEGY[k]["positioning"],
            "收录": SECTION_STRATEGY[k]["topics"],
        }
        for k in SECTION_ORDER
    }
    slim = []
    for i, it in enumerate(pool):
        slim.append({
            "idx": i,
            "title": it.get("title"),
            "key_info": (it.get("key_info") or "")[:180],
            "tags": (it.get("tags") or [])[:5],
            "sources": (it.get("sources_list") or [])[:4],
            "old_section": it.get("section"),
        })

    system = (
        "你是两院（中关村学院+中关村人工智能研究院）法务周报编辑。"
        "周报面向两院法务部，强调筛选、判断、转化：每条须能落到法条/合同条款/制度规则/"
        "争议处理/合规风险/会签要点/责任边界/纠纷预防，不发看热闹的产业新闻。\n"
        "请按「组织策略」为每条资讯定主位板块，仅在确有交叉时给次位指引。\n"
        "原则1：按读者视角定主位——读者打开该板块最想看到的是什么。\n"
        "原则2：全文只放主位；also_in 通常为 []，仅当另一板块读者也必须知晓时填1个，最多1个。\n"
        "定主位口诀：\n"
        "- two_institute（两院法务，建议占比≥50%）：中国立法/司法/执法/监管直接或间接影响"
        "教育/科研/AI/数据/事业单位/民非/基金会/未成年人保护；最高法最高检司法解释与指导案例；"
        "互联网法院/知产法院涉AI数据网络知产案例；部委及北京地方执法约谈处罚；"
        "科研管理/人遗/科技伦理/博士培养/校园与未成年人保护/成果转化与出口管制/"
        "新研发机构与孵化投资/事业单位民非基金会/数据与AI直接监管/北京地方立法执法。\n"
        "- 禁止放入 two_institute：纯党政活动通稿（外事会见、交流周开幕、调研视察、座谈会、"
        "开班典礼等无实质规则）；两院或兄弟院校日常动态（开学典礼、运动会、招生宣传、校庆）；"
        "与两院无关的道交/体育等泛立法；纯宣传稿、无制度规则的领导讲话。\n"
        "- legal_ai（法律AI/合规实务）：法律AI/合规科技工具发布与重大迭代；红圈所/头部企业"
        "法务合规团队公开的AI/数据/合同审查体系实务；有方法论意义的合规体系建设文章；"
        "法律科技行业重要动态；有数据案例可借鉴的法务数字化/法律职业研究。\n"
        "- 禁止放入 legal_ai：教育部/科技部等活动通稿（有实质规则改归 two_institute）；"
        "纯律师业务推广、招聘广告、会议软文。\n"
        "- global_ai（全球AI治理）：主要经济体AI立法修法执法节点；国际AI标准组织重大标准；"
        "跨境AI治理合作；具全球合规影响的AI安全事件/重大处罚；主要法域AI重大司法案例。\n"
        "- 禁止放入 global_ai：纯产品发布/模型跑分/融资新闻（除非重大违规下架/安全事件）；"
        "纯技术论文（除非直接触发伦理法律讨论）；公司公关稿、行业会议通稿；纯股价估值商业动作。\n"
        "- 拿不准且与两院法律合规均弱相关时，一律不收录（宁缺毋滥；section 可返回空字符串）。\n"
        "also_in 判定示例：最高法涉AI著作权司法解释→two_institute+[]；"
        "EU AI Act细则含科研教育豁免→global_ai+['two_institute']；"
        "红圈所企业AI合规指引→legal_ai+[]；"
        "网信办生成式AI执法首案→two_institute，可 also_in ['legal_ai']。\n"
        "板块键名只能是：global_ai / legal_ai / two_institute（或空字符串表示不收录）。\n"
        "输出 JSON 数组，元素字段：idx, section(主位), also_in(数组，通常[]，最多1个), reason(不超过20字)。\n"
        "不要 Markdown。"
    )
    user = json.dumps({"strategy": strategy_brief, "items": slim}, ensure_ascii=False)
    timeout = int(((cfg.get("enrich") or {}).get("llm") or {}).get("timeout_seconds") or 90)
    timeout = max(timeout, 120)

    for ep in endpoints:
        try:
            logger.info("按组织策略重排板块：%s 条 via %s", len(slim), ep["name"])
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
                continue
            try:
                arr = json.loads(m.group(0))
            except json.JSONDecodeError:
                raw = m.group(0)
                cut = raw.rfind("}")
                if cut < 0:
                    continue
                arr = json.loads(raw[: cut + 1] + "]")
            mapping: dict[int, dict[str, Any]] = {}
            for obj in arr:
                if not isinstance(obj, dict):
                    continue
                try:
                    idx = int(obj.get("idx"))
                except (TypeError, ValueError):
                    continue
                sec = str(obj.get("section") or "").strip()
                if sec not in SECTION_STRATEGY:
                    continue
                also = obj.get("also_in") or []
                if isinstance(also, str):
                    also = [also]
                also = [a for a in also if a in SECTION_STRATEGY and a != sec][:1]
                mapping[idx] = {"section": sec, "also_in": also}
            if len(mapping) < max(1, len(pool) // 2):
                logger.warning("板块重排结果过少 %s/%s", len(mapping), len(pool))
                continue
            out = []
            for i, it in enumerate(pool):
                row = dict(it)
                info = mapping.get(i) or {
                    "section": classify_section(str(it.get("title") or "")),
                    "also_in": [],
                }
                row["section"] = _fix_primary_section(row, info["section"])
                also = [a for a in (info.get("also_in") or []) if a != row["section"]][:1]
                # 若主位已是两院，一般不再往法律AI挂指引（避免监管资讯刷屏）
                if row["section"] == "two_institute":
                    also = [a for a in also if a != "legal_ai"]
                row["also_in"] = also
                out.append(row)
            return out
        except Exception as e:
            logger.warning("板块重排 LLM 失败 %s：%s", ep["name"], e)
    return None


def _fix_primary_section(item: dict[str, Any], proposed: str) -> str:
    """用硬规则校正明显错位，保证读者视角主位清晰。"""
    from curate import is_legal_ai_core, is_noise, is_two_institute_core

    title = str(item.get("title") or "")
    text = " ".join(
        [
            title,
            str(item.get("key_info") or ""),
            " ".join(item.get("original_titles") or []),
            " ".join(item.get("tags") or []),
        ]
    )
    # 招聘/直播预告/交易通稿等：直接不入栏
    if is_noise(text, title=title):
        return ""
    # 1) 明确全球治理 / 跨境监管（强信号；禁止纯融资跑分进本栏）
    if re.search(
        r"EU AI Act|联合国.?AI|G7|OECD|APEC|NIST|ISO.?IEC|IEEE.?AI|"
        r"FTC|白宫|ICO|PDPC|GDPR|"
        r"美国.?AI.?行政令|欧盟委员会.?AI|跨境执法",
        text,
        re.I,
    ):
        return "global_ai"
    # 2) 法律行业纵深 / 合规实务 / 垂类工具
    if re.search(
        r"法律科技|LegalTech|法律AI|法务AI|合同审查工具|法律检索|文书生成|法律职业|"
        r"法务AI落地|法务数字化|企业AI治理.?法务|垂类工具|合规体系.?搭建|"
        r"MyLegalAI|法天使|元典|智合|豆包|扣子|Coze|WorkBuddy|AIpha|AlphaGPT|"
        r"合同助手|合同库|智慧法治|法治合规平台|法律人.?AI|"
        r"律师实验室|法律服务新模式|法律咨询.?Pro|Harvey|Ironclad|法智易|"
        r"律所.{0,12}(AI|人工智能|数字化|科技|白皮书|合规)|"
        r"(AI|人工智能|数字化).{0,12}(律所|法务)",
        text,
        re.I,
    ):
        return "legal_ai"
    if is_legal_ai_core(text, title=title):
        return "legal_ai"
    # 3) 直接服务两院的立法司法执法/数据科研合规硬核
    if is_two_institute_core(text, title=title):
        return "two_institute"
    # 4) 全球产业弱信号：仅当伴随合规/监管/下架/处罚语境才进 global_ai
    if re.search(
        r"(违规|下架|处罚|执法|禁令|安全事件|数据泄露).{0,20}"
        r"(模型|大模型|AI|OpenAI|Anthropic)|"
        r"(模型|大模型|AI).{0,20}(违规|下架|处罚|执法|禁令|安全事件|数据泄露)",
        text,
        re.I,
    ):
        return "global_ai"
    # 提议未过硬核 → 丢弃（勿硬塞）
    if proposed in ("two_institute", "legal_ai"):
        return ""
    if proposed == "global_ai":
        return ""
    if proposed in SECTION_STRATEGY:
        return proposed
    guessed = classify_section(text)
    if guessed == "legal_ai" and not is_legal_ai_core(text, title=title):
        return ""
    if guessed == "two_institute" and not is_two_institute_core(text, title=title):
        return ""
    if guessed == "global_ai":
        # 无强治理信号时不因弱规则命中而入全球栏
        return ""
    return guessed
