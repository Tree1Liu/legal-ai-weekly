# -*- coding: utf-8 -*-
"""定时任务。

周报模式（默认）：每周五 17:00 跑流水线。
日报模式：按 schedule.hour/minute，可 weekdays_only。

用法：
1) 本脚本常驻：python scheduler_job.py
2) Windows 任务计划：周五 17:00 执行 `python main.py --once`
"""

from __future__ import annotations

import logging
import sys

from utils import load_config, setup_logging, ensure_dirs


def _is_weekday() -> bool:
    from utils import now_cst

    return now_cst().weekday() < 5


def _is_friday() -> bool:
    from utils import now_cst

    return now_cst().weekday() == 4


def run_once() -> None:
    from main import run_once as main_once

    main_once()


def main() -> None:
    cfg = load_config()
    paths = ensure_dirs(cfg)
    setup_logging(paths["log_file"])
    logger = logging.getLogger(__name__)

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error(
            "未安装 APScheduler。可：C:\\python\\python.exe -m pip install apscheduler\n"
            "或改用 Windows 计划任务调用：python main.py --once"
        )
        sys.exit(1)

    hour = int((cfg.get("schedule") or {}).get("hour", 17))
    minute = int((cfg.get("schedule") or {}).get("minute", 0))
    weekdays_only = bool((cfg.get("schedule") or {}).get("weekdays_only", False))
    friday_only = bool((cfg.get("schedule") or {}).get("friday_only", True))
    product = (cfg.get("product_mode") or "weekly").lower()
    tz = cfg.get("timezone") or "Asia/Shanghai"

    # 周报默认仅周五；日报可用 weekdays_only
    if product == "weekly":
        friday_only = bool((cfg.get("schedule") or {}).get("friday_only", True))

    scheduler = BlockingScheduler(timezone=tz)

    def job():
        if friday_only and not _is_friday():
            logger.info("非周五，跳过（周报固定周五推送）")
            return
        if weekdays_only and not friday_only and not _is_weekday():
            logger.info("非工作日，跳过")
            return
        logger.info("定时触发 %02d:%02d product=%s", hour, minute, product)
        run_once()

    if friday_only:
        trigger = CronTrigger(day_of_week="fri", hour=hour, minute=minute, timezone=tz)
        logger.info("调度已启动：每周五 %02d:%02d（法律AI周报）", hour, minute)
    else:
        trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
        logger.info(
            "调度已启动：每天 %02d:%02d（weekdays_only=%s）",
            hour,
            minute,
            weekdays_only,
        )

    scheduler.add_job(job, trigger, id="legal_weekly_digest")
    scheduler.start()


if __name__ == "__main__":
    main()
