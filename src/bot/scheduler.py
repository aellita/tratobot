import logging

from aiogram import Bot
from aiogram.fsm.storage.base import BaseStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..services.daily_limits import refresh_all_daily_limits
from ..services.evening_report import send_auto_close_reports, send_evening_teaser
from ..services.morning_report import send_morning_reports

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler(bot: Bot, storage: BaseStorage):
    moscow_tz = "Europe/Moscow"
    scheduler.add_job(
        send_morning_reports,
        CronTrigger(hour=8, minute=0, timezone=moscow_tz),
        kwargs={"bot": bot},
        id="morning_report",
        name="Утренняя рассылка",
        replace_existing=True,
        misfire_grace_time=14400,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_evening_teaser,
        CronTrigger(hour=22, minute=0, timezone=moscow_tz),
        kwargs={"bot": bot, "storage": storage},
        id="evening_teaser",
        name="Вечерний тизер",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        send_auto_close_reports,
        CronTrigger(hour=23, minute=30, timezone=moscow_tz),
        kwargs={"bot": bot, "storage": storage},
        id="evening_auto_close",
        name="Авто-закрытие дня",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_all_daily_limits,
        CronTrigger(hour=0, minute=5, timezone=moscow_tz),
        id="daily_limits_snapshot",
        name="Снапшот дневных лимитов",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info(
        "Планировщик запущен: снапшот лимитов 00:05, утро 08:00, "
        "тизер 22:00, авто-закрытие 23:30 МСК"
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
