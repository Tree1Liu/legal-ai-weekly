# -*- coding: utf-8 -*-
"""周报归档库：每期周报落库（digest JSON）+ 期次索引 + 发布目录构建。

目录约定
--------
data/archive/
    index.json          # 期次索引（"数据库"）：所有期次元数据，按结束日期倒序
    w-YYYYMMDD.json     # 每期完整 digest（渲染的唯一数据源）

deploy/
    index.html          # 最新一期
    archive/w-*.html    # 历史各期
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from utils import now_cst, write_json

logger = logging.getLogger(__name__)

ARCHIVE_DIRNAME = "archive"
INDEX_FILENAME = "index.json"


# ---------------------------------------------------------------- 日期归一化

def _norm_full(token: str, inherit_year: str = "") -> str | None:
    """把 2026-09-14 / 2026.9.4 / 09.14 归一为 2026-09-14。"""
    token = (token or "").strip()
    m = re.match(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$", token)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})[-./](\d{1,2})$", token)
    if m and inherit_year:
        return f"{inherit_year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def parse_date_range(date_range: str, fallback: str = "") -> tuple[str, str]:
    """解析 date_range，返回 (start_iso, end_iso)。

    兼容两种历史格式：
        "2026-08-21 17:00 至 2026-08-24 11:14"
        "2026.09.04 至 09.09"
    """
    text = (date_range or "").strip()
    fallback = (fallback or "").strip()

    year = ""
    m = re.search(r"(\d{4})", text) or re.search(r"(\d{4})", fallback)
    if m:
        year = m.group(1)

    tokens = re.findall(
        r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}", text
    )
    dates = [d for d in (_norm_full(t, year) for t in tokens) if d]

    if not dates and fallback:
        fb = fallback[:10]
        d = _norm_full(fb, year)
        if d:
            dates = [d]

    if not dates:
        return "", ""

    start = dates[0]
    end = dates[-1]
    if end < start:  # 跨年等异常时兜底
        end = start
    return start, end


def date_label(start: str, end: str) -> str:
    """2026-09-11 / 2026-09-14 -> 2026.09.11-09.14"""
    if not start:
        return ""
    a = start.replace("-", ".")
    if not end:
        return a
    b = end.replace("-", ".")
    if end[:4] == start[:4]:
        b = b[5:]
    return f"{a}-{b}"


# ---------------------------------------------------------------- 期次元数据

def issue_from_digest(digest: dict[str, Any]) -> dict[str, Any]:
    """从 digest 提炼期次元数据。"""
    weekly = digest.get("weekly") or {}
    generated_at = str(digest.get("generated_at") or "")
    start, end = parse_date_range(weekly.get("date_range") or "", generated_at)
    if not end:
        end = generated_at[:10]
    if not start:
        start = end

    issue_label = (weekly.get("issue_label") or "").strip()
    vol = weekly.get("vol") or digest.get("vol")
    if not issue_label:
        issue_label = f"第{vol}期" if vol else ""

    dl = date_label(start, end)
    label = f"{dl} · {issue_label}" if issue_label else dl

    week_id = f"w-{end.replace('-', '')}" if end else f"w-{generated_at[:10].replace('-', '')}"

    counts = digest.get("counts") or {}
    return {
        "week_id": week_id,
        "start_date": start,
        "end_date": end,
        "date_label": dl,
        "issue_label": issue_label,
        "label": label,
        "vol": vol,
        "title": digest.get("title") or "法律AI每周资讯",
        "sources": counts.get("sources"),
        "total": counts.get("total_in_batch"),
        "generated_at": generated_at,
    }


# ---------------------------------------------------------------- 归档读写

def _archive_dir(cfg_or_dir: Any) -> Path:
    from utils import project_root

    archive_dir = Path(cfg_or_dir or (project_root() / "data" / ARCHIVE_DIRNAME))
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


def load_index(archive_dir: Path) -> dict[str, Any]:
    import json

    p = Path(archive_dir) / INDEX_FILENAME
    if not p.exists():
        return {"issues": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("archive index 读取失败：%s", e)
        return {"issues": []}
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        return {"issues": []}
    return data


def save_index(archive_dir: Path, index: dict[str, Any]) -> None:
    issues = index.get("issues") or []
    issues.sort(key=lambda x: (x.get("end_date") or "", x.get("week_id") or ""), reverse=True)
    index["issues"] = issues
    index["updated_at"] = now_cst().isoformat()
    write_json(Path(archive_dir) / INDEX_FILENAME, index)


def archive_issue(digest: dict[str, Any], archive_dir: Path) -> dict[str, Any]:
    """把一期 digest 写入归档库，并更新索引。同 week_id 覆盖（重跑覆盖旧版）。"""
    archive_dir = _archive_dir(archive_dir)
    meta = issue_from_digest(digest)
    wid = meta["week_id"]

    write_json(archive_dir / f"{wid}.json", digest)

    index = load_index(archive_dir)
    issues = index.get("issues") or []
    issues = [it for it in issues if it.get("week_id") != wid]
    issues.append(meta)
    index["issues"] = issues
    save_index(archive_dir, index)

    logger.info("归档期次 %s（%s）共 %s 期", wid, meta.get("label"), len(issues))
    return meta


def load_issue_digest(archive_dir: Path, week_id: str) -> dict[str, Any] | None:
    import json

    p = Path(archive_dir) / f"{week_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("归档期次读取失败 %s：%s", week_id, e)
        return None


def list_issues(archive_dir: Path) -> list[dict[str, Any]]:
    """按期次倒序返回。"""
    issues = load_index(_archive_dir(archive_dir)).get("issues") or []
    return sorted(
        issues,
        key=lambda x: (x.get("end_date") or "", x.get("week_id") or ""),
        reverse=True,
    )


def _weeks_for_page(
    issues: list[dict[str, Any]],
    latest_id: str,
    page_id: str,
    *,
    page_is_root: bool,
) -> list[dict[str, Any]]:
    """构建某页面上的期次下拉数据（href 相对当前页面位置，current 为当前页自身）。"""
    out: list[dict[str, Any]] = []
    for it in issues:
        wid = it.get("week_id") or ""
        if page_is_root:
            href = "index.html" if wid == latest_id else f"archive/{wid}.html"
        else:
            href = "../index.html" if wid == latest_id else f"{wid}.html"
        out.append(
            {
                "id": wid,
                "label": it.get("label") or wid,
                "href": href,
                "current": wid == page_id,
            }
        )
    return out


def build_deploy(archive_dir: Path, deploy_dir: Path) -> dict[str, Any]:
    """重建发布目录：最新期 -> index.html；各期 -> archive/w-*.html。"""
    from report_html import digest_to_html

    archive_dir = _archive_dir(archive_dir)
    deploy_dir = Path(deploy_dir)
    archive_out = deploy_dir / "archive"
    archive_out.mkdir(parents=True, exist_ok=True)

    issues = list_issues(archive_dir)
    if not issues:
        logger.warning("归档库为空，跳过发布目录构建")
        return {"ok": False, "reason": "empty_archive"}

    latest_id = issues[0]["week_id"]
    written: list[str] = []

    for it in issues:
        wid = it["week_id"]
        digest = load_issue_digest(archive_dir, wid)
        if not digest:
            logger.warning("缺 digest，跳过 %s", wid)
            continue

        # archive/ 下的版本
        weeks = _weeks_for_page(issues, latest_id, wid, page_is_root=False)
        html = digest_to_html(digest, weeks=weeks, current_id=wid)
        target = archive_out / f"{wid}.html"
        target.write_text(html, encoding="utf-8")
        written.append(str(target))

        # 最新期同时输出为首页
        if wid == latest_id:
            weeks_root = _weeks_for_page(issues, latest_id, wid, page_is_root=True)
            html_root = digest_to_html(digest, weeks=weeks_root, current_id=wid)
            (deploy_dir / "index.html").write_text(html_root, encoding="utf-8")
            written.append(str(deploy_dir / "index.html"))

    # 清理已不在索引里的历史文件
    valid = {f"{it['week_id']}.html" for it in issues}
    for f in archive_out.glob("w-*.html"):
        if f.name not in valid:
            f.unlink()
            logger.info("清理过期归档页：%s", f.name)

    logger.info("发布目录已重建：%s 期 → %s", len(issues), deploy_dir)
    return {
        "ok": True,
        "issues": len(issues),
        "latest": latest_id,
        "files": written,
    }


__all__ = [
    "parse_date_range",
    "date_label",
    "issue_from_digest",
    "archive_issue",
    "load_issue_digest",
    "list_issues",
    "load_index",
    "save_index",
    "build_deploy",
    "backfill_from_digests",
]


# ---------------------------------------------------------------- 历史回填

def backfill_from_digests(
    digest_dir: Path,
    archive_dir: Path,
    *,
    pattern: str = "weekly-*.json",
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """把历史 digest 文件按期次回填进归档库。同一期只保留时间戳最新的一份。"""
    import json

    digest_dir = Path(digest_dir)
    archive_dir = _archive_dir(archive_dir)

    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for p in sorted(digest_dir.glob(pattern)):
        if p.name in ("weekly-latest.json",):
            continue
        try:
            digest = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("跳过无法解析的 %s：%s", p.name, e)
            continue
        meta = issue_from_digest(digest)
        wid = meta["week_id"]
        # 文件名时间戳越大越新；相同则比 generated_at
        stamp = p.stem
        prev = best.get(wid)
        if prev is None or stamp > prev[0]:
            best[wid] = (stamp, digest)

    saved: list[dict[str, Any]] = []
    for wid in sorted(best, reverse=True):
        digest = best[wid][1]
        if dry_run:
            saved.append(issue_from_digest(digest))
            continue
        saved.append(archive_issue(digest, archive_dir))

    logger.info("历史回填完成：%s 期（dry_run=%s）", len(saved), dry_run)
    return saved


# ---------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> None:
    import argparse
    import logging as _logging

    from utils import project_root

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="周报归档 / 发布目录构建")
    parser.add_argument("--backfill", action="store_true", help="把历史 digest 回填进归档库")
    parser.add_argument("--build", action="store_true", help="重建 deploy 发布目录")
    parser.add_argument("--list", action="store_true", help="列出已归档期次")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写盘")
    parser.add_argument("--archive-dir", default=None, help="归档目录（默认 data/archive）")
    parser.add_argument("--deploy-dir", default=None, help="发布目录（默认 deploy）")
    args = parser.parse_args(argv)

    root = project_root()
    archive_dir = Path(args.archive_dir) if args.archive_dir else root / "data" / ARCHIVE_DIRNAME
    deploy_dir = Path(args.deploy_dir) if args.deploy_dir else root / "deploy"

    if args.backfill:
        rows = backfill_from_digests(
            root / "data" / "digests", archive_dir, dry_run=args.dry_run
        )
        for m in rows:
            print(f"  {m['week_id']:14s} {m.get('label','')}")

    if args.build:
        res = build_deploy(archive_dir, deploy_dir)
        print("build:", res.get("ok"), "issues:", res.get("issues"), "latest:", res.get("latest"))

    if args.list:
        for it in list_issues(archive_dir):
            print(f"  {it['week_id']:14s} {it.get('label','')}")


if __name__ == "__main__":
    _main()
