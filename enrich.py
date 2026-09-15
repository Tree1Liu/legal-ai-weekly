# -*- coding: utf-8 -*-
"""AI / 规则初筛：摘要、标签、重要级、需人审。

保留原有 mock 规则逻辑；在此基础上叠加《周报说明》字段：
板块分类、影响场景、法务关注点、快讯判定等。
mode=llm/auto 时尝试用大模型改写（失败则回退 mock）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from utils import normalize_published_fields


logger = logging.getLogger(__name__)

# 【可改】关键词 → 法律专业标签（对齐《推送提示》v3.0 §3.2）
KEYWORD_TAG_RULES: list[tuple[str, str]] = [
    (r"全国人大|常委会.?通过|法律修正案|制定.?法律", "立法动态"),
    (r"司法解释|指导性案例|司法政策|公报案例", "司法解释"),
    (r"行政处罚|约谈|专项整治|责令|执法通报", "行政执法"),
    (r"典型案例|标杆.?裁判|首案", "典型案例"),
    (r"部门规章|规范性文件|指导意见|国家标准|行业指引", "政策新规"),
    (r"生成式人工智能|算法备案|深度合成|大模型监管|AI安全|AI标准", "AI监管"),
    (r"个人信息|数据出境|数据安全法|重要数据|数据要素|数据流通", "数据合规"),
    (r"网络安全法|关基|等保|数据泄露|网络攻击", "网络安全"),
    (r"科技伦理|科研诚信|伦理审查|人类遗传", "科技伦理"),
    (r"技术出口|出口管制|经济制裁|两用物项", "出口管制"),
    (r"专利|商标|商业秘密|反不正当竞争", "知识产权"),
    (r"AI生成|AIGC|训练数据.?版权|著作权.?AI", "AI著作权"),
    (r"开源协议|开源许可|开源软件|License", "开源合规"),
    (r"成果转化|技术转移|职务发明|校企.?IP", "成果转化"),
    (r"技术开发合同|技术许可|技术转让|专利许可", "专利与技术合同"),
    (r"合同审查|格式条款|违约责任|合同效力", "合同审查"),
    (r"政府采购|招标投标|比选|供应商管理", "采购与招投标"),
    (r"SaaS|PaaS|云服务|AI服务采购|数据处理协议|系统集成", "IT与云服务"),
    (r"股权投资|孵化|基金合规|投后|股东协议", "投资孵化"),
    (r"反垄断|垄断协议|经营者集中|滥用市场支配", "反垄断与反不正当竞争"),
    (r"劳动合同|用工|社保|竞业限制|裁员", "劳动人事"),
    (r"外聘|兼职导师|退休返聘|顾问协议", "外聘与兼职"),
    (r"博士生|学位|学生奖惩|学术规范|学生伤害", "学生管理"),
    (r"未成年人|校园安全|反欺凌|家长同意|少年.?AI", "未成年人保护"),
    (r"办学|招生|中外合作办学|校外培训", "教育合规"),
    (r"科研经费|科研项目|横向|纵向|科研不端", "科研合规"),
    (r"人类遗传|生物安全|医疗数据|临床研究", "人遗与生物安全"),
    (r"事业单位|民非|国有资产|财政经费|内部审计", "事业单位监管"),
    (r"基金会|捐赠|慈善|公益支出|关联交易", "基金会与公益"),
    (r"商业贿赂|利益冲突|反舞弊|廉洁", "廉洁合规"),
    (r"诉讼|仲裁|执行|证据保全|财产保全", "争议解决"),
    (r"舆情|突发事件|举报|投诉调查", "危机应对"),
    (r"合规管理体系|法务数字化|合规培训|内控", "合规体系"),
    (r"跨境争议|外国法|境外监管|制裁合规", "国际合规"),
    (r"法律科技|LegalTech|法务AI|合同审查工具|Harvey|法智易", "合规体系"),
]

HIGH_PATTERNS = [
    r"通过|表决|公布|施行|修正案|决定",
    r"处罚|刑事责任|立案|约谈",
    r"正式发布|生效|备案|责令|司法解释",
]

# 与两院周报相关的相关性关键词
RELEVANCE_PATTERNS = [
    r"人工智能|AI|算法|大模型|生成式|深度合成",
    r"数据|个人信息|跨境|网络安全|数据安全",
    r"高校|教育|科研|实验室|新型研发|事业单位|博士|未成年人",
    r"民办非|民非|基金会|捐赠|人类遗传|科技伦理",
    r"合规|治理|监管|备案|执法|处罚|司法解释|指导性案例",
    r"知识产权|开源|技术出口|合同|采购",
    r"北京|中关村|科委|海淀",
    r"法律科技|LegalTech|法务AI|合同审查|合规体系|MyLegalAI|法天使|元典|智合",
]

# 三大板块策略与分类（详见 sections_strategy）
from sections_strategy import (
    SECTION_LABELS,
    SECTION_RULES,
    classify_section,
)

# 法律专业标签全集（供 LLM 初筛选用；禁止业务语言标签）
LEGAL_TAG_CATALOG = (
    "立法动态、司法解释、行政执法、典型案例、政策新规、"
    "AI监管、数据合规、网络安全、科技伦理、出口管制、"
    "知识产权、AI著作权、开源合规、成果转化、专利与技术合同、"
    "合同审查、采购与招投标、IT与云服务、投资孵化、交易架构、反垄断与反不正当竞争、"
    "劳动人事、外聘与兼职、学生管理、未成年人保护、教育合规、"
    "科研合规、人遗与生物安全、事业单位监管、基金会与公益、廉洁合规、"
    "争议解决、危机应对、合规体系、国际合规"
)

# 影响场景：改为法律问题取向（兼容旧字段名；展示层主要用 tags）
SCENE_RULES: list[tuple[str, str]] = [
    (r"科研|实验室|横向|纵向|人遗|科技伦理|科研经费", "科研合规"),
    (r"采购|供应商|云服务|SaaS|算法备案|模型|智能体|合同", "IT与云服务"),
    (r"员工|用工|人事|外聘|竞业", "劳动人事"),
    (r"学生|博士|学位|未成年人|校园", "学生管理"),
    (r"成果转化|开源|技术出口|知识产权|专利", "知识产权"),
    (r"制度|审计|内控|合规体系|廉洁", "合规体系"),
    (r"财政|对外投资|国有资产|高校|民非|事业单位|新型研发", "事业单位监管"),
    (r"基金会|捐赠|公示|关联交易|慈善", "基金会与公益"),
    (r"数据|个人信息|跨境|数据出境|数据安全", "数据合规"),
    (r"生成式|算法|深度合成|大模型|AI安全", "AI监管"),
    (r"反垄断|不正当竞争|垄断", "反垄断与反不正当竞争"),
]

# 重大监管动态（快讯）—— 对齐推送提示 v3.0 §5.2
FLASH_PATTERNS = [
    r"(正式发布|公布|施行|生效).{0,24}(人工智能|算法|数据|个人信息|教育|科研|民办非|基金会|人类遗传|未成年人)",
    r"(人工智能|算法|数据|个人信息|人类遗传).{0,24}(正式发布|公布|施行|生效|备案|司法解释)",
    r"(处罚|责令|通报|立案|约谈).{0,36}(高校|科研|民非|基金会|教育机构|大模型|算法)",
    r"(算法备案|生成式人工智能|深度合成|数据出境|重要数据|指导性案例)",
    r"(最高人民.?法院|最高人民.?检察).{0,20}(司法解释|指导性案例|典型案例)",
]


def _text_of(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('raw', '')} {item.get('summary', '')}"


def detect_impact_scenes(text: str, allowed: list[str] | None = None) -> list[str]:
    scenes: list[str] = []
    for pattern, scene in SCENE_RULES:
        if re.search(pattern, text, re.I):
            scenes.append(scene)
    scenes = list(dict.fromkeys(scenes))
    if allowed:
        scenes = [s for s in scenes if s in allowed] or scenes
    return scenes[:4]


def relevance_score(text: str) -> int:
    return sum(1 for p in RELEVANCE_PATTERNS if re.search(p, text, re.I))


def is_flash_candidate(text: str, importance: str, cfg: dict[str, Any] | None = None) -> bool:
    """快讯判定：关键词规则 + 配置中的两院在推项目关键词。"""
    cfg = cfg or {}
    if any(re.search(p, text, re.I) for p in FLASH_PATTERNS):
        return True
    for kw in cfg.get("active_project_keywords") or []:
        if kw and kw in text and re.search(r"发布|施行|生效|备案|新规|办法|规定", text):
            return True
    if re.search(r"(自发布之日起|立即执行|过渡期|个月内完成|限期整改)", text) and relevance_score(text) >= 2:
        return True
    return importance == "high" and relevance_score(text) >= 2


def _guess_region(text: str) -> str:
    if re.search(r"北京|中关村", text):
        return "北京"
    if re.search(r"欧盟|EU|欧洲", text, re.I):
        return "欧盟/欧洲"
    if re.search(r"美国|OpenAI|NIST", text, re.I):
        return "美国"
    if re.search(r"联合国|全球", text):
        return "全球"
    return "中国"


def _mock_enrich_one(item: dict[str, Any], priority_tags: list[str], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """原有规则初筛 + 周报扩展字段。"""
    cfg = cfg or {}
    text = _text_of(item)
    tags: list[str] = []
    for pattern, tag in KEYWORD_TAG_RULES:
        if re.search(pattern, text, re.I):
            tags.append(tag)
    if priority_tags:
        ordered = [t for t in priority_tags if t in tags] + [t for t in tags if t not in priority_tags]
        tags = list(dict.fromkeys(ordered))
    else:
        tags = list(dict.fromkeys(tags))

    importance = "low"
    if any(re.search(p, text) for p in HIGH_PATTERNS):
        importance = "high"
    elif tags:
        importance = "medium"

    title = item.get("title") or ""
    summary = title if len(title) <= 120 else title[:117] + "..."

    need_review = importance == "high" or item.get("source_type") == "wechat"
    allowed_scenes = cfg.get("impact_scenes") or []
    preferred = item.get("default_section") or item.get("section")
    if preferred in SECTION_LABELS:
        section = preferred
    else:
        section = classify_section(text)
    scenes = detect_impact_scenes(text, allowed_scenes)
    score = relevance_score(text)
    flash = is_flash_candidate(text, importance, cfg)

    # 法务关注点 / 行动建议：规则不再写空套话；有 LLM 时再补具体内容
    scene_hint = "、".join(f"#{s}" for s in scenes) if scenes else "#内部合规"
    legal_focus = ""
    think_q = ""
    action = ""

    item = dict(item)
    item["summary"] = summary
    item["tags"] = tags or ["未分类"]
    item["importance"] = importance
    item["need_human_review"] = bool(need_review)
    item["enrich_mode"] = "mock"
    # —— 周报扩展字段 ——
    item["section"] = section
    item["section_label"] = SECTION_LABELS.get(section, section)
    item["region"] = item.get("region") or _guess_region(text)
    item["extended_source"] = item.get("extended_source") or ""
    item["key_info"] = item.get("key_info") or summary
    item["legal_focus"] = legal_focus
    item["impact_scenes"] = scenes
    item["impact_scene_tags"] = [f"#{s}" for s in scenes] or [scene_hint.split("、")[0]]
    item["think_questions"] = think_q
    item["action_suggestions"] = action
    item["relevance_score"] = score
    item["is_flash"] = bool(flash)
    # 规范原文发布时间，禁止对 RFC2822 做 [:10] 截断
    item.update({k: v for k, v in normalize_published_fields(item).items()
                 if k in ("published_at", "published_date", "date_source")})
    return item


def _llm_enrich_batch(items: list[dict[str, Any]], cfg: dict[str, Any], priority_tags: list[str]) -> list[dict[str, Any]] | None:
    """批量让模型补摘要/标签/周报字段；失败返回 None。"""
    if not items:
        return []
    from summarize import _call_openai_compatible, _llm_endpoints

    endpoints = _llm_endpoints(cfg)
    if not endpoints:
        return None

    llm = (cfg.get("enrich") or {}).get("llm") or {}
    base = [_mock_enrich_one(i, priority_tags, cfg) for i in items]
    # 优先送 high/medium，控制 token；其余保留规则结果
    ranked = sorted(
        base,
        key=lambda x: (0 if x.get("importance") == "high" else 1 if x.get("importance") == "medium" else 2),
    )
    slim = [
        {
            "id": b["id"],
            "title": b.get("title"),
            "source": b.get("source"),
            "section": b.get("section"),
            "impact_scenes": b.get("impact_scenes"),
            "snippet": (b.get("key_info") or b.get("summary") or "")[:160],
        }
        for b in ranked[:24]
    ]
    prompt = (
        "你在为一份「法律AI每周资讯」做条目初筛。\n"
        "受众：中关村学院与中关村人工智能研究院（两院）法务部。"
        "两院是国家级AI领域新型高校/新型研发机构（博士培养、少年AI学院未成年人、"
        "院企联合实验室、AI孵化投资、AI+科研伦理等），周报须以法律专业判断为核心。\n"
        "法务部关切：AI全链条监管、数据合规判断协同、科研项目合规、合同全周期、"
        "全品类用工、学生与未成年人保护、产业孵化投资、院企合作、国际交流合规、"
        "基金会与事业单位监管、争议解决与合规体系建设。"
        "（注：数据安全主责、知识产权管理主责不在法务，但法务须能做法律判断与合同把关。）\n"
        "请为下列条目生成 JSON 数组。每个元素字段：\n"
        "id, "
        "title(判断性标题：体现法律判断，不照搬新闻原标题；例不写「XX被处罚」，"
        "写「XX因未履行算法备案被处罚——AI服务提供者备案合规红线再次明确」), "
        "summary(不超过80字，说清什么机构出了什么、影响什么), "
        "key_info(2-3句说清发生了什么，禁止复制网站导航/页脚/SEO/通稿套话), "
        "legal_focus(1-2句：必须落到审什么合同条款、补什么制度规则、会签看什么材料、"
        "给业务部门发什么提示；禁止「建议持续关注」「提高意识」「需承办人判断」"
        "「视情况处理」「建议相关部门重视」等空话), "
        "tags(2-3个，必须从下列法律专业标签中选，第1个为主标签，禁止业务语言如"
        "「AI系统采购」「人事培训」「对外合作」：" + LEGAL_TAG_CATALOG + "), "
        "importance(high|medium|low), need_human_review(bool), "
        "section(global_ai|legal_ai|two_institute), "
        "impact_scenes(仍填1-3个，优先复用 tags 中的法律标签), "
        "think_questions(法务视角一问，必须具体到合同/制度/边界/纠纷，"
        "禁止「AI对我们有什么影响」这类空问), "
        "action_suggestions(法务部本周可执行一句：出XX清单/在XX合同模板加XX条款/"
        "给XX部门发风险提示/核查XX存量合同；禁止「完善合规体系」空话), "
        "is_flash(bool,是否重大监管快讯：新法新规司法解释正式发布且直接影响两院核心业务、"
        "或处罚约谈立案、或7天内产生即时合规义务), "
        "region(法域/主体简写，如全国人大/最高法/网信办/北京/欧盟/美国FTC)。\n"
        "板块口诀：two_institute=中国立法司法执法监管及两院场景；"
        "legal_ai=法律AI工具与合规实务方法论；"
        "global_ai=全球AI治理规则变化（禁止纯融资跑分公关稿）。"
        "拿不准且与两院法律合规弱相关则不要硬塞（可降低 importance 并 need_human_review=true）。\n"
        "禁止编造法条编号与案号；引用新规须准确。只输出 JSON 数组。\n"
        + json.dumps(slim, ensure_ascii=False)
    )
    timeout = int(llm.get("timeout_seconds") or 90)
    last_err: Exception | None = None
    for ep in endpoints:
        try:
            logger.info("尝试 LLM 初筛：%s / %s（%s 条）", ep["name"], ep["model"], len(slim))
            content = _call_openai_compatible(
                ep["api_base"],
                ep["api_key"],
                ep["model"],
                [
                    {"role": "system", "content": (
                        "你是两院法务情报初筛助理，只输出合法 JSON。"
                        "板块：two_institute=两院法务（中国立法司法执法与两院场景，建议占比最高）；"
                        "legal_ai=法律AI/合规实务；"
                        "global_ai=全球AI治理（规则变化，非产业热闹）。"
                        "标签必须用法律专业分类，禁止业务语言。"
                        "legal_focus 与 action_suggestions 必须可执行、可落地。"
                        "按读者视角定主位；宁缺毋滥。"
                    )},
                    {"role": "user", "content": prompt},
                ],
                timeout=timeout,
            )
            m = re.search(r"\[.*\]", content, re.S)
            if not m:
                last_err = ValueError("未解析到 JSON 数组")
                continue
            arr = json.loads(m.group(0))
            by_id = {str(x.get("id")): x for x in arr if isinstance(x, dict)}
            out = []
            for b in base:
                patch = by_id.get(str(b.get("id"))) or {}
                row = dict(b)
                if patch.get("title"):
                    # 判断性标题：仅在模型给出非空且不太短时覆盖
                    nt = str(patch["title"]).strip()
                    if len(nt) >= 8:
                        row["title"] = nt[:120]
                if patch.get("summary"):
                    row["summary"] = str(patch["summary"])[:120]
                if patch.get("key_info"):
                    row["key_info"] = str(patch["key_info"])[:300]
                if patch.get("legal_focus"):
                    row["legal_focus"] = str(patch["legal_focus"])[:200]
                if patch.get("think_questions"):
                    row["think_questions"] = str(patch["think_questions"])[:200]
                if patch.get("action_suggestions"):
                    row["action_suggestions"] = str(patch["action_suggestions"])[:200]
                if isinstance(patch.get("tags"), list) and patch["tags"]:
                    row["tags"] = [str(t) for t in patch["tags"][:6]]
                if patch.get("importance") in ("high", "medium", "low"):
                    row["importance"] = patch["importance"]
                if "need_human_review" in patch:
                    row["need_human_review"] = bool(patch["need_human_review"])
                if patch.get("section") in SECTION_LABELS:
                    row["section"] = patch["section"]
                    row["section_label"] = SECTION_LABELS[patch["section"]]
                if isinstance(patch.get("impact_scenes"), list) and patch["impact_scenes"]:
                    row["impact_scenes"] = [str(s).lstrip("#") for s in patch["impact_scenes"][:4]]
                    row["impact_scene_tags"] = [f"#{s}" for s in row["impact_scenes"]]
                if "is_flash" in patch:
                    row["is_flash"] = bool(patch["is_flash"])
                if patch.get("region"):
                    row["region"] = str(patch["region"])[:40]
                if patch:
                    row["enrich_mode"] = "llm"
                out.append(row)
            return out
        except Exception as e:
            last_err = e
            logger.warning("LLM 初筛端点失败 %s：%s", ep["name"], e)

    if last_err:
        logger.exception("全部 LLM 初筛端点失败：%s", last_err)
    return None


def filter_by_relevance(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """按周报相关性软/硬筛选。默认 soft：保留全部，相关的排前。"""
    weekly = cfg.get("weekly") or {}
    mode = (weekly.get("relevance_filter") or "soft").lower()
    if mode == "off" or bool(weekly.get("include_window_all", True)):
        # 全量窗口模式：不在 enrich 阶段丢弃
        return sorted(items, key=lambda x: (-int(x.get("relevance_score") or 0), x.get("importance") != "high"))
    scored = sorted(items, key=lambda x: (-int(x.get("relevance_score") or 0), x.get("importance") != "high"))
    if mode == "hard":
        kept = [i for i in scored if int(i.get("relevance_score") or 0) > 0]
        return kept or scored[:8]
    return scored


def enrich_items(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    mode = ((cfg.get("enrich") or {}).get("mode") or "auto").lower()
    priority_tags = cfg.get("priority_tags") or []

    if mode == "mock":
        logger.info("初筛模式=mock（规则），共 %s 条", len(items))
        out = [_mock_enrich_one(i, priority_tags, cfg) for i in items]
        return filter_by_relevance(out, cfg)

    if mode in ("llm", "auto"):
        llm_out = _llm_enrich_batch(items, cfg, priority_tags)
        if llm_out is not None:
            logger.info("初筛模式=llm，共 %s 条", len(llm_out))
            return filter_by_relevance(llm_out, cfg)
        if mode == "llm":
            logger.warning("enrich.mode=llm 失败，回退 mock")
        else:
            logger.info("无可用 LLM，初筛回退 mock，共 %s 条", len(items))
        out = [_mock_enrich_one(i, priority_tags, cfg) for i in items]
        return filter_by_relevance(out, cfg)

    logger.warning("未知 enrich.mode=%s，回退 mock", mode)
    out = [_mock_enrich_one(i, priority_tags, cfg) for i in items]
    return filter_by_relevance(out, cfg)
