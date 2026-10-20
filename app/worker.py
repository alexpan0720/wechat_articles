from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from app.cli import run_sync


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> None:
    scheduler = BlockingScheduler(timezone=ZoneInfo("Asia/Shanghai"))
    scheduler.add_job(run_sync, "cron", hour="9,18", minute=15, args=["scheduled"],
                      id="daily-sync", max_instances=1, coalesce=True)
    scheduler.add_job(run_sync, "cron", day_of_week="sun", hour=3, minute=30,
                      args=["compensation"], id="weekly-compensation", max_instances=1)
    logging.info("Sync worker started; daily jobs run at 09:15 and 18:15 Asia/Shanghai")
    scheduler.start()


if __name__ == "__main__":
    main()

