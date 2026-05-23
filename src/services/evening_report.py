import random
import logging
import asyncio

from aiogram import Bot
from sqlalchemy import select

from ..db.database import async_session_maker
from ..db.models.models import User, UserSettings
from .expense_service import get_today_expenses_sum, get_today_daily_limit

logger = logging.getLogger(__name__)


def get_evening_message(limit: float, spent: float) -> str:
    if spent <= limit:
        saved = limit - spent
        green_phrases = [
            f"🔋 <b>Вечерний итог:</b>\nБро, ты сегодня просто машина! Твой лимит был {int(limit)}₽, а потратил ты всего {int(spent)}₽. Сэкономленные <b>{int(saved)}₽</b> я мысленно откладываю в счет твоей Мечты. Спи спокойно, день закрыт в плюс! 🥳",
            f"🌟 <b>Управленческий триумф!</b>\nПотрачено всего {int(spent)}₽ из {int(limit)}₽. Ты удержал баланс, а это значит, что мы на один шаг ближе к твоим целям. Горжусь тобой, иди отдыхай! 🤜🤛",
            f"💎 <b>Финансовый флекс:</b>\nСегодня мы не спустили деньги на ветер. Лимит: {int(limit)}₽, факт: {int(spent)}₽. Кубышка довольно урчит, а Мечта становится ближе. Ложись спать с чистой совестью! 💤",
            f"🧘 <b>Дзен в кошельке:</b>\n{int(spent)}₽ потрачено, {int(saved)}₽ спасено. Ты контролируешь свои деньги, а не они тебя. Отличный день, бро. Завтра продолжим в том же духе!",
        ]
        return random.choice(green_phrases)

    overdraft = spent - limit
    overdraft_percent = (overdraft / limit) * 100 if limit > 0 else 100

    if overdraft_percent <= 20:
        yellow_phrases = [
            f"⚠️ <b>Вечерний итог:</b>\nНа сегодня лимит исчерпан и даже слегка превышен (на {int(overdraft)}₽). Не критично, обычная погрешность. Но завтра утром приборы покажут цифру чуть меньше. Пока отдыхай, утро вечера мудренее! 🌙",
            f"☕️ <b>Упс, микро-перерасход:</b>\nВышли за рамки на {int(overdraft)}₽. Похоже, кто-то взял лишний кофе или проехался на комфорт-плюсе. Ничего страшного, нагрузку я распределю. Расслабься, день всё равно неплохой! 👌",
            f"📊 <b>В пределах нормы, но...</b>\nТраты за день: {int(spent)}₽ при лимите {int(limit)}₽. Превышение копеечное, завтра затянем пояса на пару миллиметров и даже не заметим. Хорошего вечера, бро!",
        ]
        return random.choice(yellow_phrases)
    else:
        red_phrases = [
            f"🚨 <b>Фиксирую жесткий овердрафт!</b>\nОу, сегодня мы знатно погуляли и вылетели за рамки лимита аж на {int(overdraft)}₽! Без паники, я уже готовлю план спасения на утро. Главное — больше сегодня ничего не покупай. Ложись отдыхать, завтра всё разрулим! 🤝",
            f"🔥 <b>Кошелек горит!</b>\nБро, сегодня был явно весёлый или очень стрессовый день. Мы потратили {int(spent)}₽ вместо {int(limit)}₽. Счётчик зашкаливает. Закрывай банковские приложения, выдыхай, утро принесёт новые цифры и новые решения. Я с тобой! 🫡",
            f"💥 <b>Баланс пробит:</b>\nМинус {int(overdraft)}₽ от сегодняшней нормы. Деньги ушли, но нервы дороже — не кори себя. Завтра утром мы либо распечатаем Кубышку, либо пересчитаем дни. А пока — режим энергосбережения. Спокойной ночи! 🌃",
        ]
        return random.choice(red_phrases)


async def send_evening_reports(bot: Bot):
    logger.info("Запуск вечерней рассылки в 22:00...")

    async with async_session_maker() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    for tg_id in user_ids:
        try:
            async with async_session_maker() as session:
                settings_result = await session.execute(
                    select(UserSettings).where(UserSettings.telegram_id == tg_id)
                )
                settings = settings_result.scalar_one_or_none()
                if settings and not settings.notifications_enabled:
                    continue

            limit = await get_today_daily_limit(tg_id)
            if limit <= 0:
                continue

            spent = await get_today_expenses_sum(tg_id)
            text = get_evening_message(limit=limit, spent=spent)

            await bot.send_message(chat_id=tg_id, text=text)
            logger.info(f"Вечерний отчёт отправлен {tg_id}")

            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить вечерний отчёт для {tg_id}: {e}")

    logger.info("Вечерняя рассылка завершена.")
