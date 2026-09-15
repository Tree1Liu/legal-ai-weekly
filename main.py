# -*- coding: utf-8 -*-
"""一键入口：跑通「采集 → 整理 →（人审策略）→ 推送」。

用法：
  C:\\python\\python.exe main.py --once
  C:\\python\\python.exe main.py --once --flash
  C:\\python\\python.exe main.py --once --quarterly
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import run_pipeline
from push_dingtalk import push_dingtalk
from push_miniprogram import push_digest
from quarterly import build_quarterly
from utils import (
    ensure_dirs,
    load_config,
    project_root,
    setup_logging,
    write_json,
)


def run_once(config_path: str | None = None, *, flash_only: bool = False) -> dict:
    cfg = load_config(config_path)
    paths = ensure_dirs(cfg)
    setup_logging(paths["log_file"])
    logger = logging.getLogger("main")

    digest = run_pipeline(cfg, flash_only=flash_only)

    # 归档本期 + 重建发布目录（最新期进首页，历史期进 archive/）
    archive_dir = paths.get("archive_dir") or (paths["data_dir"] / "archive")
    deploy_dir = paths.get("deploy_dir") or (project_root() / "deploy")
    try:
        from archive import archive_issue, build_deploy

        meta = archive_issue(digest, archive_dir)
        build = build_deploy(archive_dir, deploy_dir)
        logger.info(
            "归档完成 %s；发布目录 %s 期（最新 %s）",
            meta.get("week_id"),
            build.get("issues"),
            build.get("latest"),
        )
    except Exception as e:
        logger.warning("归档/发布目录构建失败：%s", e)

    result = push_digest(digest, cfg)
    ding = push_dingtalk(digest, cfg)
    summary = {
        "digest_title": digest.get("title"),
        "product_mode": digest.get("product_mode") or cfg.get("product_mode"),
        "counts": digest.get("counts"),
        "paths": digest.get("_paths"),
        "push": result,
        "dingtalk": ding,
    }
    write_json(paths["digest_dir"] / "last_run_summary.json", summary)
    logger.info("本轮结束：%s", summary)
    return summary


def run_quarterly(config_path: str | None = None) -> dict:
    cfg = load_config(config_path)
    paths = ensure_dirs(cfg)
    setup_logging(paths["log_file"])
    logger = logging.getLogger("main")
    digest = build_quarterly(cfg)
    ding = push_dingtalk(digest, cfg)
    summary = {
        "digest_title": digest.get("title"),
        "product_mode": "quarterly",
        "counts": digest.get("counts"),
        "paths": digest.get("_paths"),
        "dingtalk": ding,
    }
    write_json(paths["digest_dir"] / "last_run_summary.json", summary)
    logger.info("季度合集结束：%s", summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="法律AI周报 / 快讯 / 季度合集")
    parser.add_argument("--once", action="store_true", help="立即跑一轮周报")
    parser.add_argument("--flash", action="store_true", help="重大监管快讯")
    parser.add_argument("--quarterly", action="store_true", help="生成季度合集")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args(argv)

    if args.quarterly:
        run_quarterly(args.config)
        return

    if not args.once:
        print("提示：--once 周报；--once --flash 快讯；--quarterly 季度合集")
        print("示例：C:\\python\\python.exe main.py --once")
        sys.exit(0)

    run_once(args.config, flash_only=bool(args.flash))


if __name__ == "__main__":
    main()
