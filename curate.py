# -*- coding: utf-8 -*-
"""周报精选：硬筛选、板块限额、两院占比、选题方向计分。"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 明确噪音：与两院法务周报无关的娱乐/社会/纯业务杂讯（按全文匹配）
NOISE_PATTERNS = [
    r"团播|娱乐乱象|明星|综艺|演唱会",
    r"足球|篮球|奥运|亚运|体育赛事|体育争议|涉外体育",
    r"彩票|中奖|开奖",
    r"保健食品|特殊食品|特殊医学用途配方食品",
    r"化妆品注册|医疗器械注册|药品说明书",
    r"进口保健|备案管理信息系统",
    r"食品安全抽检|不合格食品|农兽药残留",
    r"特种设备|电梯检验|压力容器",
    r"天气预报|交通限行",
    r"招聘启事|公务员考试",
]

# 标题级噪音：仅当标题本身是通稿/外事/党建学习/泛教育活动/律所营销时剔除
TITLE_NOISE_PATTERNS = [
    r"正确政绩观|学习教育成果|政绩观学习",
    r"会见.{0,20}(部长|大使|代表|校长)",
    r"教育交流周|交流周开幕|友好访问|出访",
    r"座谈会召开|成果交流会|专题研讨班开班",
    # 教育部通稿/活动开幕——非法律AI、也非两院合同制度场景
    r"研习营|研习营开营|语言文化教育",
    r"对口支援|援藏干部|财务工作会",
    r"巡视情况汇报|巡视工作领导小组听取",
    r"义务教育|做中学|领航行动",
    r"原创性教材|教材出版",
    r"红色山河|创意长漫|以奋斗赓续",
    r"港澳青少年|青少年.?营",
    # 律所/平台营销：招聘、直播预告、邀请函、交易通稿、民事八卦案
    r"招聘|校招|社招|诚聘|招贤|心与梦的工作",
    r"直播预告|直播邀请|威科直播",
    r"邀请函|线下邀请|线下活动|[Ii]nvite\b|报名通道",
    r"助力.{0,30}(融资|并购|吸收合并|完成.?轮)",
    r"联署倡议|儿童友好律师",
    r"婚姻家庭纠纷|未成年子女名下",
    r"从三罪到一罪|民刑交叉追诉",
    r"赋能法律人经验值",
]

# 全刊保留信号（粗筛）：过宽的「教育」已去掉，避免教育部通稿入刊
KEEP_SIGNAL = (
    r"人工智能|AI|算法|大模型|生成式|深度合成|智能体|"
    r"数据安全|个人信息|数据跨境|数据出境|网络安全|重要数据|"
    r"高校|科研经费|科研项目|实验室|成果转化|横向|纵向|新型研发|"
    r"民办非|民非|基金会|捐赠|事业单位|人类遗传|科技伦理|未成年人|"
    r"法律科技|LegalTech|法务|合同审查|合同管理|合规体系|"
    r"中关村|科委|科技行政处罚|算法备案|司法解释|指导性案例|"
    r"开源|知识产权|技术出口|模型安全|商业秘密|出口管制|"
    r"国防动员|反垄断|垄断协议|"
    r"数字基础设施|信息科技|法定代表人|智慧法治|"
    r"检察.?办案|典型案例|最高人民.?检察|互联网法院"
)

# 法律AI/合规实务板块硬核信号（必须命中；反垄断监管通稿归两院，不进本栏）
LEGAL_AI_CORE = (
    r"法律科技|LegalTech|法律AI|法务AI|合同审查|法律检索|文书生成|"
    r"知识管理|法务团队|法律职业|垂类工具|合规工具|合规体系|"
    r"律所.{0,12}(AI|人工智能|数字化|科技|智能化|白皮书|合规)|"
    r"(AI|人工智能|数字化).{0,12}(律所|法务)|"
    r"智慧法治|法治合规平台|法律咨询.?Pro|AlphaGPT|Harvey|Ironclad|法智易|"
    r"MyLegalAI|法天使|元典|智合|豆包|扣子|Coze|WorkBuddy|Alpha|AIpha|"
    r"合同助手|合同库|AI辅助办案|法律大模型|法务数字化|法务落地|"
    r"企业AI治理|Agent工作流|智能审核|供应商合规|"
    r"开源.?协议|开源.?许可|提示词|幻觉检测|"
    r"法律人.?AI|AI.?培训与应用"
)

# 两院法务板块硬核信号：须有直接服务两院场景的法律/合规信号
TWO_INSTITUTE_CORE = (
    r"人工智能|AI|算法|大模型|生成式|深度合成|智能体|算法备案|"
    r"数据安全|个人信息|数据跨境|数据出境|重要数据|数据分级|"
    r"科研经费|科研项目|成果转化|横向项目|纵向项目|重点实验室|"
    r"新型研发|事业单位|民办非|民非|基金会|捐赠|"
    r"高校.{0,12}(合规|合同|采购|知识产权|数据|处罚|执法)|"
    r"(合规|合同|采购|知识产权|数据|处罚|执法).{0,12}高校|"
    r"中关村|北京市科委|科技行政处罚|"
    r"国防动员|技术出口|开源许可|商业秘密|出口管制|"
    r"反垄断|垄断协议|市场监管总局|"
    r"教育.?培训合同|人事.?用工|劳务派遣|劳动合同|服务期|"
    r"知识产权.{0,8}(转化|归属|许可|检察)|"
    r"科研资金|学术诚信|科技行政处罚|科技伦理|人类遗传|人遗|"
    r"(采购|招投标).{0,12}(AI|人工智能|科研|数据)|"
    r"(AI|人工智能|科研|数据).{0,12}(采购|招投标)|"
    r"数字基础设施|信息科技.?月报|教育行业.?资讯|"
    r"最高人民.?检察|知识产权检察|典型案例|司法解释|指导性案例|"
    r"法定代表人|代办.?审慎|训推.?数据|未成年人|博士生|少年.?AI|"
    r"互联网法院|知识产权法院|行政处罚|约谈|专项整治"
)

# 两院栏软噪音：看标题是否像新闻通稿/外事礼仪（正文顺带提及不算）
TWO_INSTITUTE_SOFT_NOISE = [
    r"正确政绩观|学习教育工作成果|政绩观学习教育",
    r"^[^。]{0,8}会见|出访|友好访问|交流周开幕|教育交流周",
    r"专题研讨班|成果交流会|座谈会$",
    r"开幕(?!.*?(办法|规定|条例|合规|数据|人工智能))",
]


def direction_score(text: str, directions: list[str]) -> list[str]:
    """命中的选题方向标签。"""
    mapping = [
        (r"人工智能|算法|大模型|生成式|AI治理|深度合成", "AI监管与企业AI治理"),
        (r"责任|风控|合规义务|处罚|执法", "合规风控与责任边界"),
        (r"合同|审查|智能审核|条款", "合同管理与AI审查实践"),
        (r"数据|跨境|个人信息|数据出境", "数据合规及数据跨境"),
        (r"知识管理|数字化|法务系统", "法务知识管理与数字化建设"),
        (r"法律科技|法务.?AI|律所|落地|案例", "法务AI落地案例与行业观察"),
        (r"算法备案|算法合规|热点", "人工智能与算法合规法规政策及热点案例"),
        (r"事业单位|新型研发|民非|高校|科研机构", "事业单位/新型研发机构政策动态"),
    ]
    hits: list[str] = []
    for pattern, label in mapping:
        if re.search(pattern, text, re.I):
            hits.append(label)
    if directions:
        # 配置中的方向优先展示；未列出的仍保留命中标签
        ordered = [d for d in directions if d in hits] + [h for h in hits if h not in directions]
        hits = ordered
    return list(dict.fromkeys(hits))[:4]


def is_noise(text: str, title: str = "") -> bool:
    if any(re.search(p, text or "", re.I) for p in NOISE_PATTERNS):
        return True
    # 通稿/外事类只看标题，避免聚合卡正文顺带提及被误杀
    t = (title or text or "").strip()
    return any(re.search(p, t, re.I) for p in TITLE_NOISE_PATTERNS)


def is_legal_ai_core(text: str, title: str = "") -> bool:
    """法律AI/法律科技板块硬门槛。"""
    blob = f"{title or ''} {text or ''}"
    if is_noise(blob, title=title or text):
        return False
    return bool(re.search(LEGAL_AI_CORE, blob, re.I))


def is_two_institute_relevant(text: str) -> bool:
    """是否与两院法务观察范围相关（全刊粗筛）。"""
    return bool(re.search(KEEP_SIGNAL, text, re.I))


def is_two_institute_core(text: str, title: str = "") -> bool:
    """两院法务板块硬门槛：须有直接服务两院场景的法律/合规信号。"""
    if not text or not str(text).strip():
        return False
    title_s = (title or "").strip() or str(text).split("。")[0][:80]
    # 软噪音只看标题：正文提到政绩观/会见不算整条剔除
    if any(re.search(p, title_s, re.I) for p in TWO_INSTITUTE_SOFT_NOISE):
        if not re.search(
            r"办法|规定|条例|决定|处罚|执法|合同|数据出境|算法备案|生成式|科研经费|科研资金",
            title_s,
            re.I,
        ):
            return False
    return bool(re.search(TWO_INSTITUTE_CORE, text, re.I))


def _item_text(row: dict[str, Any]) -> str:
    return (
        f"{row.get('title', '')} {row.get('raw', '')} {row.get('summary', '')} "
        f"{row.get('key_info', '')} {' '.join(row.get('original_titles') or [])} "
        f"{' '.join(row.get('tags') or [])}"
    )


def two_institute_card_ok(row: dict[str, Any]) -> bool:
    """聚合卡质量门：标题过硬核；成员标题过脏时才剔除。"""
    title = str(row.get("title") or "")
    text = _item_text(row)
    if is_noise(text, title=title):
        return False
    if not is_two_institute_core(text, title=title):
        return False
    originals = [str(t).strip() for t in (row.get("original_titles") or []) if str(t).strip()]
    if len(originals) < 3:
        return True
    # 标题本身已是强主题（科研/数据/AI/知识产权等）→ 信任提炼标题
    # 但「赛事/交流/开幕」类活动通稿即使带知识产权字样，仍要看成员质量
    strong_title = bool(
        re.search(
            r"科研经费|科研资金|数据合规|数据出境|人工智能|算法备案|国防动员|"
            r"知识产权转化|成果转化|民非|基金会|科技行政处罚|跨境.*技术合作|涉外合作",
            title,
            re.I,
        )
    )
    eventish = bool(re.search(r"赛事|交流周|研习营|开幕|研讨会|招聘活动", title))
    if strong_title and not eventish:
        return True
    hit = sum(1 for t in originals if is_two_institute_core(t, title=t))
    # 普通聚合卡：至少约 1/3 成员贴两院，且不少于 2 条
    return hit >= 2 and hit * 3 >= len(originals)


def curate_items(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """精选入刊：去掉噪音与无关业务，再按板块限额封顶。"""
    weekly = cfg.get("weekly") or {}
    mode = (weekly.get("relevance_filter") or "soft").lower()
    min_score = int(weekly.get("min_relevance_score") or 1)
    limits = weekly.get("section_limits") or {
        "global_ai": 25,
        "legal_ai": 25,
        "two_institute": 50,
    }
    max_items = int(weekly.get("max_items") or 80)
    enforce_ratio = bool(weekly.get("enforce_two_institute_ratio", False))
    target_ratio = float(weekly.get("two_institute_min_ratio") or 0.5)
    directions = weekly.get("directions") or []
    # include_all：时间窗内汇总，但仍剔除噪音与无关业务
    include_all = bool(weekly.get("include_window_all", True))
    drop_unrelated = bool(weekly.get("drop_unrelated_business", True))
    # 两院栏硬筛：默认开启
    strict_two = bool(weekly.get("strict_two_institute", True))
    min_two_score = int(weekly.get("two_institute_min_score") or 2)

    prepared: list[dict[str, Any]] = []
    for it in items:
        row = dict(it)
        text = _item_text(row)
        title = str(row.get("title") or "")
        if is_noise(text, title=title):
            row["curate_drop"] = "noise"
            continue
        # 与两院法务无关的业务信息直接丢弃（快讯保留）
        if drop_unrelated and not row.get("is_flash") and not is_two_institute_relevant(text):
            row["curate_drop"] = "unrelated_business"
            continue
        score = int(row.get("relevance_score") or 0)
        dirs = direction_score(text, directions)
        row["directions"] = dirs
        if dirs and score < 1:
            score = max(score, 1)
            row["relevance_score"] = score

        sec = row.get("section") or ""
        # 主位已是/将是两院：必须过硬核门槛，否则改挂或不入刊
        if strict_two and (sec == "two_institute" or not sec):
            if not is_two_institute_core(text, title=title) and not row.get("is_flash"):
                # 仅真正的法律科技信号才改挂法律AI；其余直接丢弃（禁止教育部通稿回流）
                if is_legal_ai_core(text, title=title):
                    row["section"] = "legal_ai"
                    row["curate_note"] = "resection_from_two_institute"
                else:
                    row["curate_drop"] = "two_institute_weak"
                    continue
            elif score < min_two_score and not row.get("is_flash") and not dirs:
                row["curate_drop"] = "two_institute_low_score"
                continue

        # 法律AI栏硬门槛：须是工具/法务落地/法律职业相关，禁止泛教育通稿
        if (row.get("section") or sec) == "legal_ai" and not row.get("is_flash"):
            if not is_legal_ai_core(text, title=title):
                row["curate_drop"] = "legal_ai_weak"
                continue

        # hard 模式丢低相关；soft/全量也至少要求 min_score（默认 1）
        if score < min_score and not row.get("is_flash") and not dirs:
            if mode == "hard" or drop_unrelated:
                row["curate_drop"] = "low_relevance"
                continue
        if (not include_all) and mode == "hard" and score < min_score and not row.get("is_flash"):
            row["curate_drop"] = "low_relevance"
            continue
        prepared.append(row)

    rank_imp = {"high": 0, "medium": 1, "low": 2}
    prepared.sort(
        key=lambda x: (
            0 if x.get("is_flash") else 1,
            rank_imp.get(x.get("importance"), 9),
            -int(x.get("relevance_score") or 0),
            0 if x.get("directions") else 1,
        )
    )

    # 来源均衡：先保证每个来源至少占若干席位，避免单源占满
    per_source_min = int(weekly.get("per_source_min") or 3)
    per_source_max = int(weekly.get("per_source_max") or 20)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in prepared:
        by_source.setdefault(row.get("source") or "未知", []).append(row)

    diversified: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    # 第一轮：每源先取 min 条
    for src, rows in by_source.items():
        for row in rows[:per_source_min]:
            iid = row.get("id")
            if iid and iid not in seen_ids:
                diversified.append(row)
                seen_ids.add(iid)
    # 第二轮：按原排序继续补，受 per_source_max 约束
    source_count = {src: 0 for src in by_source}
    for row in diversified:
        source_count[row.get("source") or "未知"] = source_count.get(row.get("source") or "未知", 0) + 1
    for row in prepared:
        if len(diversified) >= max_items:
            break
        iid = row.get("id")
        if not iid or iid in seen_ids:
            continue
        src = row.get("source") or "未知"
        if source_count.get(src, 0) >= per_source_max:
            continue
        diversified.append(row)
        seen_ids.add(iid)
        source_count[src] = source_count.get(src, 0) + 1

    prepared = diversified or prepared

    buckets: dict[str, list[dict[str, Any]]] = {
        "global_ai": [],
        "legal_ai": [],
        "two_institute": [],
    }
    leftover: list[dict[str, Any]] = []
    for row in prepared:
        sec = row.get("section") or "two_institute"
        if sec not in buckets:
            sec = "two_institute"
        # 兜底进两院前再过一次硬核门槛 + 聚合卡质量门
        if sec == "two_institute" and strict_two and not row.get("is_flash"):
            if not two_institute_card_ok(row):
                leftover.append(row)
                continue
        lim = int(limits.get(sec) or 30)
        if len(buckets[sec]) < lim:
            buckets[sec].append(row)
        else:
            leftover.append(row)

    selected = buckets["global_ai"] + buckets["legal_ai"] + buckets["two_institute"]

    # 未满总上限时，把 leftover 继续补入（不得把弱相关硬塞进两院）
    if len(selected) < max_items:
        for row in leftover:
            if len(selected) >= max_items:
                break
            sec = row.get("section") or ""
            if strict_two and sec == "two_institute" and not row.get("is_flash"):
                if not is_two_institute_core(_item_text(row), title=str(row.get("title") or "")):
                    continue
            selected.append(row)

    if enforce_ratio and selected:
        def ratio(rows: list[dict[str, Any]]) -> float:
            if not rows:
                return 0.0
            return sum(1 for r in rows if r.get("section") == "two_institute") / len(rows)

        ti_pool = [
            r
            for r in leftover
            if r.get("section") == "two_institute"
            and (
                not strict_two
                or r.get("is_flash")
                or is_two_institute_core(_item_text(r), title=str(r.get("title") or ""))
            )
        ]
        seen = {r.get("id") for r in selected}
        ti_pool = [r for r in ti_pool if r.get("id") not in seen]
        while ratio(selected) < target_ratio and ti_pool and len(selected) < max_items:
            selected.append(ti_pool.pop(0))

    selected = selected[:max_items]
    selected.sort(
        key=lambda x: (
            {"global_ai": 0, "legal_ai": 1, "two_institute": 2}.get(x.get("section"), 9),
            0 if x.get("is_flash") else 1,
            -int(x.get("relevance_score") or 0),
        )
    )
    logger.info(
        "精选：候选 %s → 入刊 %s（global=%s legal=%s two=%s，来源 %s）",
        len(items),
        len(selected),
        sum(1 for r in selected if r.get("section") == "global_ai"),
        sum(1 for r in selected if r.get("section") == "legal_ai"),
        sum(1 for r in selected if r.get("section") == "two_institute"),
        len({r.get("source") for r in selected}),
    )
    return selected
