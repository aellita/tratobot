import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aiogram import Bot

from ..services.evening_report import send_evening_reports

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler(bot: Bot):
    scheduler.add_job(
        send_evening_reports,
        CronTrigger(hour=22, minute=0),
        kwargs={"bot": bot},
        id="evening_report",
        name="Вечерняя рассылка итогов",
        replace_existing=True,
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("Планировщик запущен: вечерний отчёт в 22:00")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
