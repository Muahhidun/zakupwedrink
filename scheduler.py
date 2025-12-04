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


async def check_and_send_reminder(bot: Bot, group_chat_id: str, reminder_type: str):
    """
    Проверить введены ли остатки сегодня, если нет - отправить напоминание

    Args:
        bot: Telegram bot instance
        group_chat_id: ID группового чата
        reminder_type: Тип напоминания (morning, afternoon, evening, final)
    """
    try:
        # Импортируем здесь чтобы избежать циклических зависимостей
        from database_pg import DatabasePG

        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            logger.warning("⚠️ DATABASE_URL не установлен")
            return

        db = DatabasePG(database_url)
        await db.init_db()

        # Проверяем были ли введены остатки сегодня
        today = datetime.now().date()
        has_data = await db.has_stock_for_date(today)

        await db.close()

        if has_data:
            logger.info(f"✅ Остатки за {today} уже введены, напоминание не требуется")
            return

        # Формируем сообщение в зависимости от времени
        messages = {
            'morning': (
                "⏰ <b>Доброе утро!</b>\n\n"
                "Напоминание: необходимо ввести остатки на складе.\n"
                "Нажмите 📝 Ввод остатков для обновления данных.\n\n"
                f"Дата: {today.strftime('%d.%m.%Y')}"
            ),
            'afternoon': (
                "⏰ <b>Напоминание!</b>\n\n"
                "Остатки ещё не введены.\n"
                "Пожалуйста, внесите данные по складу.\n\n"
                f"Дата: {today.strftime('%d.%m.%Y')}"
            ),
            'evening': (
                "⚠️ <b>Важное напоминание!</b>\n\n"
                "Остатки до сих пор не введены.\n"
                "Это влияет на точность расчёта закупов.\n"
                "Пожалуйста, внесите данные как можно скорее.\n\n"
                f"Дата: {today.strftime('%d.%m.%Y')}"
            ),
            'final': (
                "🚨 <b>КРАЙНЕЕ НАПОМИНАНИЕ!</b>\n\n"
                "Остатки за сегодня всё ещё не введены!\n"
                "Это последнее напоминание за день.\n\n"
                "⚠️ Без актуальных данных расчёт закупов будет неточным.\n"
                "Пожалуйста, не забудьте ввести остатки.\n\n"
                f"Дата: {today.strftime('%d.%m.%Y')}"
            )
        }

        message = messages.get(reminder_type, messages['morning'])

        # Отправляем в группу
        try:
            await bot.send_message(
                chat_id=group_chat_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"✅ Напоминание ({reminder_type}) отправлено в группу {group_chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в группу: {e}")

        # Отправляем всем пользователям в личку
        user_ids = await db.get_all_active_users()
        logger.info(f"📢 Рассылка напоминаний {len(user_ids)} пользователям...")

        success_count = 0
        for user_id in user_ids:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="HTML"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

        logger.info(f"✅ Напоминание ({reminder_type}) отправлено {success_count}/{len(user_ids)} пользователям")

    except Exception as e:
        logger.error(f"❌ Ошибка в check_and_send_reminder: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Настроить и запустить планировщик задач
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")  # Казахстан UTC+5

    # Получаем ID группового чата из переменных окружения
    group_chat_id = os.getenv('REMINDER_CHAT_ID')  # ID группы

    if not group_chat_id:
        logger.warning("⚠️ REMINDER_CHAT_ID не установлен, напоминания отключены")
        logger.warning("💡 Добавьте REMINDER_CHAT_ID в .env файл для включения напоминаний")
        return scheduler

    # Добавляем напоминания на разное время
    reminders = [
        (11, 0, 'morning', 'Утреннее напоминание (11:00)'),
        (13, 0, 'afternoon', 'Дневное напоминание (13:00)'),
        (15, 0, 'evening', 'Вечернее напоминание (15:00)'),
        (17, 0, 'final', 'Крайнее напоминание (17:00)')
    ]

    for hour, minute, reminder_type, name in reminders:
        scheduler.add_job(
            check_and_send_reminder,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Almaty"),
            args=[bot, group_chat_id, reminder_type],
            id=f'reminder_{reminder_type}',
            name=name,
            replace_existing=True
        )
        logger.info(f"📅 {name} настроено для чата {group_chat_id}")

    logger.info("📱 Личные напоминания будут отправлены всем зарегистрированным пользователям бота")

    return scheduler
