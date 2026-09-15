# -*- coding: utf-8 -*-
"""人审卡点。

生产：review_status 保持 pending，由承办人在小程序/表格中批准。
演示：dry_run + auto_approve_in_dry_run 时可自动批准非高风险项，便于联调跑通。
"""

from __future__ import annotations

import logging
from typing import Any

from utils import now_cst

logger = logging.getLogger(__name__)


def apply_review(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    dry_run = bool(cfg.get("dry_run", True))
    auto = bool(cfg.get("auto_approve_in_dry_run", False))
    out = []
    for item in items:
        row = dict(item)
        # 无链接直接拒绝
        if not (row.get("url") or "").strip():
            row["review_status"] = "rejected"
            row["reviewed_by"] = "system"
            out.append(row)
            continue

        if dry_run and auto:
            # 【可改】演示策略：high 仍 pending，其余自动过
            if row.get("importance") == "high" and row.get("need_human_review"):
                row["review_status"] = "pending"
                row["reviewed_by"] = ""
            else:
                row["review_status"] = "approved"
                row["reviewed_by"] = "dry_run_auto"
                row["reviewed_at"] = now_cst().isoformat()
        else:
            # 生产默认全部 pending，等待人审工具/表单回写
            if row.get("need_human_review", True):
                row["review_status"] = "pending"
            else:
                row["review_status"] = "approved"
                row["reviewed_by"] = "policy_auto_low"
                row["reviewed_at"] = now_cst().isoformat()
        out.append(row)

    pending_n = sum(1 for x in out if x.get("review_status") == "pending")
    approved_n = sum(1 for x in out if x.get("review_status") == "approved")
    logger.info("人审结果：approved=%s pending=%s（dry_run=%s auto=%s）", approved_n, pending_n, dry_run, auto)
    return out


def approve_ids(store_rows: list[dict[str, Any]], ids: list[str], reviewer: str) -> list[dict[str, Any]]:
    """供课后扩展：根据 id 列表批量批准。"""
    id_set = set(ids)
    now = now_cst().isoformat()
    for row in store_rows:
        if row.get("id") in id_set:
            row["review_status"] = "approved"
            row["reviewed_by"] = reviewer
            row["reviewed_at"] = now
    return store_rows
