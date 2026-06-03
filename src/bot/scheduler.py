import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram.fsm.storage.base import BaseStorage

from aiogram import Bot

from ..services.evening_report import send_evening_teaser, send_auto_close_reports
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
        misfire_grace_time=300,
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

    scheduler.start()
    logger.info("Планировщик запущен: утро 08:00, тизер 22:00, авто-закрытие 23:30 МСК")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
