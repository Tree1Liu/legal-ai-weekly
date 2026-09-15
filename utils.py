# -*- coding: utf-8 -*-
"""公共工具：读写配置、时间窗口、日志、简易指纹。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # 若未安装 PyYAML
    yaml = None


CST = timezone(timedelta(hours=8))


def parse_source_datetime(raw: Any) -> datetime | None:
    """解析原文发布时间：支持 ISO、RFC2822（RSS）、中文日期。采集时刻不算原文时间。"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CST)
        return dt.astimezone(CST)

    s = str(raw).strip()
    if not s or s in ("—", "-", "None", "null"):
        return None

    # ISO：2026-08-25T12:00:00+08:00 / 2026-08-25
    try:
        iso = s.replace("Z", "+00:00")
        if re.match(r"^20\d{2}-\d{2}-\d{2}$", iso):
            return datetime(int(iso[:4]), int(iso[5:7]), int(iso[8:10]), tzinfo=CST)
        if "T" in iso or ("+" in iso[10:] or iso.endswith("Z")):
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            return dt.astimezone(CST)
    except Exception:
        pass

    # RFC2822：Tue, 25 Aug 2026 10:00:00 GMT
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(CST)
    except Exception:
        pass

    # 中文：2026年8月25日 / 2026-08-25 / 2026.08.25
    m = re.search(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime(y, mo, d, tzinfo=CST)
        except ValueError:
            return None

    # 英文缩写/残片：Tue, 25 Aug 2026 / Tue, 25 Au（[:10] 截断）
    m2 = re.search(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+(\d{1,2})\s+([A-Za-z]{2,9})\s*(20\d{2})?",
        s,
        re.I,
    )
    if m2:
        day = int(m2.group(1))
        mon = _month_from_abbr(m2.group(2))
        year = int(m2.group(3)) if m2.group(3) else datetime.now(CST).year
        if mon:
            try:
                return datetime(year, mon, day, tzinfo=CST)
            except ValueError:
                return None
    return None


def _month_from_abbr(token: str) -> int | None:
    t = (token or "").strip().lower()
    mapping = [
        ("january", 1), ("jan", 1),
        ("february", 2), ("feb", 2),
        ("march", 3), ("mar", 3),
        ("april", 4), ("apr", 4),
        ("may", 5),
        ("june", 6), ("jun", 6),
        ("july", 7), ("jul", 7),
        ("august", 8), ("aug", 8), ("au", 8),
        ("september", 9), ("sept", 9), ("sep", 9),
        ("october", 10), ("oct", 10),
        ("november", 11), ("nov", 11),
        ("december", 12), ("dec", 12),
    ]
    for key, mon in mapping:
        if t == key or t.startswith(key) or key.startswith(t):
            if len(t) >= 2:
                return mon
    return None


def extract_date_from_url(url: str) -> datetime | None:
    """从常见政务/资讯 URL 路径提取发布日（次选，仍属原文侧线索）。"""
    u = (url or "").strip()
    if not u:
        return None
    patterns = [
        r"/20(\d{2})(\d{2})/t20\d{2}(\d{2})(\d{2})_",  # /202608/t20260824_
        r"/(20\d{2})-(\d{1,2})/(\d{1,2})/",  # /2026-08/04/
        r"/(20\d{2})/(\d{1,2})/(\d{1,2})/",
        r"[?&](?:date|time|pdate)=?(20\d{2})[-/]?(\d{1,2})[-/]?(\d{1,2})",
    ]
    m = re.search(patterns[0], u)
    if m:
        y = 2000 + int(m.group(1))
        mo, d = int(m.group(2)), int(m.group(4))
        try:
            return datetime(y, mo, d, tzinfo=CST)
        except ValueError:
            return None
    for pat in patterns[1:]:
        m = re.search(pat, u)
        if not m:
            continue
        y, mo, d = map(int, m.groups()[:3])
        try:
            return datetime(y, mo, d, tzinfo=CST)
        except ValueError:
            continue
    return None


def _is_collect_time_disguise(published: Any, collected: Any) -> bool:
    """published_at 与 collected_at 同秒，通常是采集时刻冒充原文时间。"""
    if not published or not collected:
        return False
    a = str(published).strip()[:19]
    b = str(collected).strip()[:19]
    return bool(a) and a == b


def normalize_published_fields(item: dict[str, Any]) -> dict[str, Any]:
    """把条目的 published_at / published_date 规范为真实原文时间（ISO + YYYY-MM-DD）。"""
    row = dict(item)
    collected = row.get("collected_at")
    collect_dt = parse_source_datetime(collected)
    disguised = _is_collect_time_disguise(row.get("published_at"), collected)

    candidates: list[Any] = [row.get("source_published_at")]
    # 采集时刻冒充的 published_at / 由其截出的 published_date 不可信
    if not disguised:
        candidates.append(row.get("published_at"))
        candidates.append(row.get("published_date"))
    for u in row.get("source_urls") or []:
        if isinstance(u, dict):
            candidates.append(u.get("published_at") or u.get("published_date"))

    field_dt = None
    for c in candidates:
        if not c:
            continue
        if _is_collect_time_disguise(c, collected):
            continue
        field_dt = parse_source_datetime(c)
        if field_dt:
            break

    url_dates: list = []
    udt0 = extract_date_from_url(str(row.get("url") or ""))
    if udt0:
        url_dates.append(udt0)
    for u in row.get("source_urls") or []:
        if not isinstance(u, dict):
            continue
        udt = extract_date_from_url(str(u.get("url") or ""))
        if udt:
            url_dates.append(udt)
    url_dt = max(url_dates) if url_dates else None

    dt = field_dt
    # 纠正历史伪日期：字段日=采集日，但 URL 日不同 → 以 URL（原文路径）为准
    if url_dt and collect_dt and field_dt:
        if field_dt.date() == collect_dt.date() and url_dt.date() != field_dt.date():
            dt = url_dt
    elif not dt:
        dt = url_dt

    if dt:
        row["published_at"] = dt.isoformat()
        row["published_date"] = dt.strftime("%Y-%m-%d")
        row["date_source"] = "original"
    else:
        # 无原文时间：清空伪日期，避免把采集日当成资讯日
        row["published_at"] = ""
        row["published_date"] = ""
        row["date_source"] = "missing"
    return row


def format_display_date(item: dict[str, Any]) -> str:
    """条目小注：优先原文日 MM.DD；无原文日时用采集日，避免小注缺时间。"""
    row = normalize_published_fields(item)
    d = (row.get("published_date") or "").strip()
    if re.match(r"^20\d{2}-\d{2}-\d{2}$", d):
        return d[5:].replace("-", ".")
    col = parse_source_datetime(item.get("collected_at"))
    if col:
        return col.strftime("%m.%d")
    return "—"


def pick_best_published(items: list[dict[str, Any]]) -> tuple[str, str]:
    """从一组成员中取最新的真实原文时间，返回 (iso, YYYY-MM-DD)。"""
    best: datetime | None = None
    for it in items or []:
        row = normalize_published_fields(it)
        dt = parse_source_datetime(row.get("published_at") or row.get("published_date"))
        if dt and (best is None or dt > best):
            best = dt
    if not best:
        return "", ""
    return best.isoformat(), best.strftime("%Y-%m-%d")


def get_env_key(name: str) -> str:
    """读取环境变量；进程里没有时，再读 Windows 用户变量（注册表）。"""
    val = (os.environ.get(name) or "").strip()
    if val:
        return val
    if sys.platform == "win32" and name:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                raw, _ = winreg.QueryValueEx(key, name)
                return (str(raw) if raw is not None else "").strip()
        except OSError:
            pass
    return ""


def project_root() -> Path:
    return Path(__file__).resolve().parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载 config.yaml；若不存在则回退到 config.example.yaml。"""
    root = project_root()
    cfg_path = Path(path) if path else root / "config.yaml"
    if not cfg_path.exists():
        cfg_path = root / "config.example.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    if yaml is None:
        raise RuntimeError("请先安装 PyYAML：C:\\python\\python.exe -m pip install pyyaml")
    return yaml.safe_load(text)


def setup_logging(log_file: str | Path) -> None:
    path = Path(log_file)
    if not path.is_absolute():
        path = project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def now_cst() -> datetime:
    return datetime.now(tz=CST)


def lookback_since(hours: int) -> datetime:
    return now_cst() - timedelta(hours=hours)


def weekly_window_since(
    now: datetime | None = None,
    *,
    cutoff_hour: int = 17,
    cutoff_minute: int = 0,
) -> datetime:
    """周报时间窗起点：上一个「周五 cutoff」时刻。

    《周报说明》：每周五下午 17:00 推送，覆盖上周五 17:00 至推送当下。
    若当前恰好是周五且已过 cutoff，则起点为「上周五」；
    若尚未到本周五 cutoff，起点仍为上周五。
    """
    now = now or now_cst()
    # weekday: 周一=0 … 周五=4
    days_since_friday = (now.weekday() - 4) % 7
    this_friday = (now - timedelta(days=days_since_friday)).replace(
        hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0
    )
    if now >= this_friday and days_since_friday == 0:
        # 本周五 cutoff 之后：窗口从上周五开始
        return this_friday - timedelta(days=7)
    if now >= this_friday:
        # 周六/日等：this_friday 已是刚过去的周五
        return this_friday
    # 本周五尚未到：上周五
    return this_friday - timedelta(days=7)


def resolve_lookback_since(cfg: dict[str, Any]) -> datetime:
    """按 product_mode 选择时间窗。"""
    mode = (cfg.get("product_mode") or "weekly").lower()
    if mode == "weekly":
        sch = cfg.get("schedule") or {}
        return weekly_window_since(
            cutoff_hour=int(sch.get("hour", 17)),
            cutoff_minute=int(sch.get("minute", 0)),
        )
    return lookback_since(int(cfg.get("lookback_hours") or 168))


def next_weekly_vol(meta_path: Path) -> int:
    """读取并递增周报期号，写入 meta 文件。"""
    vol = 1
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            vol = int(meta.get("last_vol") or 0) + 1
        except (json.JSONDecodeError, ValueError, TypeError):
            vol = 1
    meta["last_vol"] = vol
    meta["updated_at"] = now_cst().isoformat()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return vol


def make_id(url: str, title: str = "") -> str:
    raw = (url or "").strip() or (title or "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def ensure_dirs(cfg: dict[str, Any]) -> dict[str, Path]:
    root = project_root()
    paths = cfg.get("paths", {})
    mapping = {}
    for key, rel in paths.items():
        p = Path(rel)
        if not p.is_absolute():
            p = root / p
        if key.endswith("_dir") or key in ("inbox_dir", "data_dir", "digest_dir"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
        mapping[key] = p
    return mapping


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
