# -*- coding: utf-8 -*-
"""推送到法务小程序后端（占位实现）。"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def push_digest(digest: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """把已批准日报推给小程序后端。

    约定请求体（【可改】与后端对齐）：
    {
      "title": "...",
      "generated_at": "...",
      "items": [ {title, url, summary, tags, importance, source} ]
    }
    """
    mp = cfg.get("miniprogram") or {}
    api_url = mp.get("api_url") or ""
    token_env = mp.get("token_env") or "MINIPROGRAM_PUSH_TOKEN"
    timeout = int(mp.get("timeout_seconds") or 15)
    dry_run = bool(cfg.get("dry_run", True))

    payload = {
        "title": digest.get("title"),
        "generated_at": digest.get("generated_at"),
        "counts": digest.get("counts"),
        "items": [
            {
                "id": i.get("id"),
                "title": i.get("title"),
                "url": i.get("url"),
                "summary": i.get("summary"),
                "tags": i.get("tags"),
                "importance": i.get("importance"),
                "source": i.get("source"),
                "source_type": i.get("source_type"),
                "published_at": i.get("published_at"),
            }
            for i in digest.get("items") or []
        ],
    }

    if dry_run:
        logger.info("dry_run=true，跳过真实推送。将推送 %s 条。api=%s", len(payload["items"]), api_url)
        return {"ok": True, "dry_run": True, "pushed": len(payload["items"])}

    if not api_url or "example.com" in api_url:
        logger.error("请先在 config.yaml 填写真实 miniprogram.api_url")
        return {"ok": False, "error": "api_url_not_configured"}

    token = os.environ.get(token_env, "")
    if not token:
        logger.error("环境变量 %s 未设置", token_env)
        return {"ok": False, "error": "token_missing"}

    try:
        import requests
    except ImportError as e:
        raise RuntimeError("推送需要 requests：C:\\python\\python.exe -m pip install requests") from e

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    ok = 200 <= resp.status_code < 300
    logger.info("小程序推送 status=%s ok=%s", resp.status_code, ok)
    return {
        "ok": ok,
        "status_code": resp.status_code,
        "text": (resp.text or "")[:500],
        "pushed": len(payload["items"]),
    }
