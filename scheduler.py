"""
Планировщик задач для WeDrink бота
"""
import logging
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

logger = logging.getLogger(__name__)


async def send_daily_reminder(bot: Bot, chat_id: str):
    """
    Отправить ежедневное напоминание о добавлении остатков
    """
    try:
        message = (
            "⏰ <b>Напоминание!</b>\n\n"
            "Время добавить остатки на складе.\n"
            "Нажмите 📝 Ввод остатков для обновления данных.\n\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y')}"
        )
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML"
        )
        logger.info(f"✅ Напоминание отправлено в чат {chat_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки напоминания: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Настроить и запустить планировщик задач
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")  # Казахстан UTC+6

    # Получаем ID чата из переменных окружения
    reminder_chat_id = os.getenv('REMINDER_CHAT_ID')

    if not reminder_chat_id:
        logger.warning("⚠️ REMINDER_CHAT_ID не установлен, напоминания отключены")
        logger.warning("💡 Добавьте REMINDER_CHAT_ID в .env файл для включения напоминаний")
        return scheduler

    # Добавляем задачу: каждый день в 11:00 по времени Алматы
    scheduler.add_job(
        send_daily_reminder,
        trigger=CronTrigger(hour=11, minute=0),
        args=[bot, reminder_chat_id],
        id='daily_stock_reminder',
        name='Ежедневное напоминание об остатках',
        replace_existing=True
    )

    logger.info(f"📅 Планировщик настроен: напоминания в 11:00 в чат {reminder_chat_id}")

    return scheduler
