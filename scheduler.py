"""
Планировщик задач для WeDrink бота
"""
import logging
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

logger = logging.getLogger(__name__)


async def send_auto_purchase_order(bot: Bot):
    """
    Автоматически рассчитать и отправить заказ на закуп (если сумма >= 500,000₸)
    Отправляется в 12:00 по Астане
    """
        from database import Database
        from database_pg import DatabasePG
        from utils.calculations import get_auto_order_with_threshold, format_auto_order_list
        from handlers.orders import prepare_order_data

        database_url = os.getenv('DATABASE_URL')
        if database_url:
            db = DatabasePG(database_url)
        else:
            db = Database("wedrink.db")
            
        await db.init_db()

        logger.info("🔍 Рассчитываю автоматический заказ на 14 дней...")

        # Подготавливаем данные (аналогично ручному расчету)
        stock_data = await prepare_order_data(db, company_id=1)

        # Получаем заказ с порогом 500,000₸
        products_to_order, total_cost, should_notify = get_auto_order_with_threshold(
            stock_data,
            order_days=14,
            threshold_amount=500000
        )

        if not should_notify:
            logger.info(
                f"💰 Сумма заказа ({total_cost:,.0f}₸) меньше порога (500,000₸). "
                f"Уведомление не отправляется."
            )
            await db.close()
            return

        # Формируем сообщение
        order_text = format_auto_order_list(products_to_order, total_cost)

        # Отправляем всем активным пользователям
        user_ids = await db.get_all_active_users()
        logger.info(f"📢 Отправка заказа {len(user_ids)} пользователям...")

        success_count = 0
        for user_id in user_ids:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=order_text,
                    parse_mode="HTML"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

        logger.info(
            f"✅ Автоматический заказ (сумма: {total_cost:,.0f}₸) "
            f"отправлен {success_count}/{len(user_ids)} пользователям"
        )

        await db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка в send_auto_purchase_order: {e}")
        import traceback
        traceback.print_exc()


async def check_and_send_reminder(bot: Bot, group_chat_id: str, reminder_type: str):
    """
    Проверить введены ли остатки сегодня, если нет - отправить напоминание

    Args:
        bot: Telegram bot instance
        group_chat_id: ID группового чата
        reminder_type: Тип напоминания (morning, afternoon, evening, final)
    """
    try:
        from database import Database
        from database_pg import DatabasePG

        database_url = os.getenv('DATABASE_URL')
        if database_url:
            db = DatabasePG(database_url)
        else:
            db = Database("wedrink.db")
            
        await db.init_db()

        # Проверяем были ли введены остатки сегодня
        today = datetime.now().date()
        company_id = 1 # Assuming default company
        has_data = await db.has_stock_for_date(company_id, today) if hasattr(db, 'pool') else await db.has_stock_for_date(today)

        if has_data:
            logger.info(f"✅ Остатки за {today} уже введены, напоминание не требуется")
            await db.close()
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

        # Кнопка для перехода в Web App
        web_app_url = os.getenv('WEB_APP_URL', 'http://localhost:5005')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Ввести остатки (Web)", web_app=WebAppInfo(url=f"{web_app_url}/stock_input"))]
        ])

        # Отправляем в группу
        try:
            await bot.send_message(
                chat_id=group_chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            logger.info(f"✅ Напоминание ({reminder_type}) отправлено в группу {group_chat_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в группу: {e}")

        # Отправляем всем пользователям в личку
        if hasattr(db, 'get_active_users_for_reminder'):
            user_ids = await db.get_active_users_for_reminder(company_id, today.isoformat())
            logger.info(f"📢 Рассылка напоминаний {len(user_ids)} пользователям (с учетом графика смен)...")
        else:
            user_ids = await db.get_all_active_users()
            logger.info(f"📢 Рассылка напоминаний {len(user_ids)} пользователям...")

        success_count = 0
        for user_id in user_ids:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")

        logger.info(f"✅ Напоминание ({reminder_type}) отправлено {success_count}/{len(user_ids)} пользователям")

        # Закрываем БД после всех операций
        await db.close()

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

    # Добавляем автоматический расчет заказа на 12:00
    scheduler.add_job(
        send_auto_purchase_order,
        trigger=CronTrigger(hour=12, minute=0, timezone="Asia/Almaty"),
        args=[bot],
        id='auto_purchase_order',
        name='Автоматический заказ на закуп (12:00)',
        replace_existing=True
    )
    logger.info("📦 Автоматический расчет заказа настроен на 12:00 (Астана)")
    logger.info("   Порог отправки: 500,000₸ | Расчет на 14 дней | Округление по правилу 0.2")

    return scheduler
