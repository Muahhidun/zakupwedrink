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
    try:
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

        logger.info("🔍 Рассчитываю автоматический заказ на 14 дней для всех активных компаний...")

        companies = await db.get_all_companies()
        
        for company in companies:
            if company.get('subscription_status') != 'active':
                continue
                
            company_id = company['id']
            # Подготавливаем данные (аналогично ручному расчету)
            stock_data = await prepare_order_data(db, company_id=company_id)

            # Получаем заказ с порогом 500,000₸
            products_to_order, total_cost, should_notify = get_auto_order_with_threshold(
                stock_data,
                order_days=14,
                threshold_amount=500000
            )

            if not should_notify:
                logger.info(
                    f"🏢 Компания {company_id}: Сумма заказа ({total_cost:,.0f}₸) меньше порога (500,000₸). "
                    f"Уведомление не отправляется."
                )
                continue

            # Формируем сообщение
            order_text = format_auto_order_list(products_to_order, total_cost)

            # Отправляем только администраторам данной компании
            admin_ids = await db.get_admins_for_company(company_id)
            logger.info(f"📢 Компания {company_id}: Отправка заказа {len(admin_ids)} администраторам...")

            success_count = 0
            for admin_id in admin_ids:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=order_text,
                        parse_mode="HTML"
                    )
                    success_count += 1
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки админу {admin_id}: {e}")

            logger.info(
                f"✅ Компания {company_id}: Автоматический заказ (сумма: {total_cost:,.0f}₸) "
                f"отправлен {success_count}/{len(admin_ids)} администраторам"
            )

        await db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка в send_auto_purchase_order: {e}")
        import traceback
        traceback.print_exc()


async def check_and_send_reminder(bot: Bot, reminder_type: str):
    """
    Проверить введены ли остатки сегодня, если нет - отправить напоминание

    Args:
        bot: Telegram bot instance
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

        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Almaty")).date()
        
        companies = await db.get_all_companies()
        
        for company in companies:
            if company.get('subscription_status') not in ['active', 'trial']:
                continue
                
            company_id = company['id']
            # Проверяем были ли введены остатки сегодня для этой компании
            has_data = await db.has_stock_for_date(company_id, today) if hasattr(db, 'pool') else await db.has_stock_for_date(today)

            if has_data:
                logger.info(f"✅ Компания {company_id}: Остатки за {today} уже введены, напоминание не требуется")
                continue

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

            # Отправляем всем пользователям в личку
            if hasattr(db, 'get_active_users_for_reminder'):
                user_ids = await db.get_active_users_for_reminder(company_id, today.isoformat())
                logger.info(f"📢 Компания {company_id}: Рассылка {len(user_ids)} пользователям (с учетом графика смен)...")
            else:
                user_ids = await db.get_all_active_users()
                logger.info(f"📢 Компания {company_id}: Рассылка {len(user_ids)} пользователям...")

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
                    
            # Дублируем уведомление администраторам франшизы (для контроля)
            admin_ids = await db.get_admins_for_company(company_id)
            for admin_id in admin_ids:
                if admin_id not in user_ids: # не отправляем дважды, если админ на смене
                    try:
                        admin_msg = f"⚠️ <b>Внимание (Контроль)!</b>\n\nСотрудники получили напоминание о вводе остатков!\n\n" + message
                        await bot.send_message(
                            chat_id=admin_id,
                            text=admin_msg,
                            parse_mode="HTML",
                            reply_markup=keyboard
                        )
                    except Exception as e:
                        logger.error(f"❌ Ошибка CC админу {admin_id}: {e}")

            logger.info(f"✅ Компания {company_id}: Напоминание ({reminder_type}) отправлено {success_count}/{len(user_ids)} пользователям")

        # Закрываем БД после всех операций
        await db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка в check_and_send_reminder: {e}")

async def check_and_send_shift_reminder(bot: Bot):
    """
    Проверить, есть ли у кого-то смена через 1 час, и отправить напоминание.
    """
    try:
        from database_pg import DatabasePG
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            return # Only supported in PG mode currently
            
        db = DatabasePG(database_url)
        await db.init_db()

        from zoneinfo import ZoneInfo
        now_astana = datetime.now(ZoneInfo("Asia/Almaty")) # Changed to correctly use Almaty time
        users_in_one_hour = await db.get_users_with_shift_in_one_hour(now_astana)

        success_count = 0
        for data in users_in_one_hour:
            user_id = data['id']
            start_time_str = data.get('start_time', '')
            if isinstance(start_time_str, str):
                start_time_str = start_time_str[:5]
            else:
                start_time_str = str(start_time_str)[:5]

            message = (
                "🔔 <b>Напоминание о смене!</b>\n\n"
                f"Ваша смена начинается примерно через час (в <b>{start_time_str}</b>).\n"
                "Пожалуйста, не опаздывайте!"
            )
            
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="HTML"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминания о смене пользователю {user_id}: {e}")
                
            # Копия администраторам для контроля
            try:
                company_id = data.get('company_id')
                if company_id:
                    first_name = data.get('first_name') or ''
                    last_name = data.get('last_name') or ''
                    employee_name = f"{first_name} {last_name}".strip() or "Сотрудник"
                    
                    admin_ids = await db.get_admins_for_company(company_id)
                    admin_msg = f"👁‍🗨 <b>Контроль смен</b>\n\nСотруднику <b>{employee_name}</b> отправлено напоминание о начале смены в <b>{start_time_str}</b>."
                    for admin_id in admin_ids:
                        if admin_id != user_id:
                            try:
                                await bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
                            except Exception as e:
                                logger.error(f"❌ Ошибка отправки CC админу {admin_id} о смене: {e}")
            except Exception as e:
                logger.error(f"❌ Ошибка при отправке CC о смене админам: {e}")

        if users_in_one_hour:
            logger.info(f"✅ Напоминание о предстоящей смене отправлено {success_count}/{len(users_in_one_hour)} пользователям")

        await db.close()
    except Exception as e:
        logger.error(f"❌ Ошибка в check_and_send_shift_reminder: {e}")
        import traceback
        traceback.print_exc()

async def check_expired_trials_and_subscriptions():
    """Ежедневная задача для проверки и отключения истекших подписок/триалов"""
    try:
        from database_pg import DatabasePG
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            return
            
        db = DatabasePG(database_url)
        await db.init_db()
        
        updated_count = await db.check_expired_subscriptions()
        if updated_count > 0:
            logger.warning(f"⚠️ Отключено {updated_count} компаний по истечению срока подписки/триала")
        else:
            logger.info("✅ Истекших подписок не найдено")
            
        await db.close()
    except Exception as e:
        logger.error(f"❌ Ошибка в check_expired_trials_and_subscriptions: {e}")

async def check_expiring_subscriptions_and_notify(bot: Bot):
    """
    Проверяет подписки, которые истекают через 3 дня и 0 дней,
    и отправляет напоминание администраторам точки с кнопкой оплаты.
    """
    try:
        from database_pg import DatabasePG
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            return
            
        db = DatabasePG(database_url)
        await db.init_db()

        # 1. Проверяем те, у кого осталось ровно 3 дня
        expiring_in_3_days = await db.get_expiring_subscriptions(days_left=3)
        # 2. Проверяем те, у кого осталось 0 дней (истекает сегодня или уже истекла)
        expiring_today = await db.get_expiring_subscriptions(days_left=0)

        # Функция для рассылки
        async def notify_admins(companies, days_left):
            for company in companies:
                company_id = company['id']
                company_name = company['name_russian'] or company['name_internal']
                
                # Формируем текст
                if days_left == 0:
                    text = (
                        f"⚠️ <b>Внимание!</b>\n\n"
                        f"Подписка для точки <b>«{company_name}»</b> отключена или истекает сегодня.\n\n"
                        f"Чтобы не потерять доступ к дашборду и Telegram-боту, пожалуйста, оплатите продление подписки."
                    )
                else:
                    text = (
                        f"🔔 <b>Напоминание о подписке</b>\n\n"
                        f"Подписка для точки <b>«{company_name}»</b> истекает через <b>{days_left} дня</b>.\n\n"
                        f"Чтобы работа не прерывалась, пожалуйста, заранее оплатите продление."
                    )

                # Добавляем кнопку оплаты (с callback data для FSM)
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить подписку (Kaspi)", callback_data=f"pay_subscription_{company_id}")]
                ])

                admin_ids = await db.get_admins_for_company(company_id)
                for admin_id in admin_ids:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=text,
                            parse_mode="HTML",
                            reply_markup=keyboard
                        )
                    except Exception as e:
                        logger.error(f"❌ Ошибка при отправке уведомления об оплате админу {admin_id}: {e}")

        # Отправляем уведомления
        await notify_admins(expiring_in_3_days, 3)
        await notify_admins(expiring_today, 0)

        await db.close()

    except Exception as e:
        logger.error(f"❌ Ошибка в check_expiring_subscriptions_and_notify: {e}")
        import traceback
        traceback.print_exc()

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """
    Настроить и запустить планировщик задач
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")  # Казахстан UTC+5

    # Проверка подписок каждую полночь в 00:05
    scheduler.add_job(
        check_expired_trials_and_subscriptions,
        trigger=CronTrigger(hour=0, minute=5, timezone="Asia/Almaty"),
        id='check_expired_subs',
        name='Проверка истекших подписок (00:05)',
        replace_existing=True
    )
    logger.info("📅 Проверка подписок настроена на 00:05")

    # Уведомления об оплате каждый день в 10:00 утра
    scheduler.add_job(
        check_expiring_subscriptions_and_notify,
        trigger=CronTrigger(hour=10, minute=0, timezone="Asia/Almaty"),
        args=[bot],
        id='notify_expiring_subs',
        name='Напоминание об оплате подписки (10:00)',
        replace_existing=True
    )
    logger.info("💸 Напоминания об оплате подписок настроены на 10:00")

    # Добавляем напоминания на разное время
    reminders = [
        (11, 0, 'morning', 'Утреннее напоминание (11:00)'),
        (14, 0, 'afternoon', 'Дневное напоминание (14:00)'),
        (17, 0, 'evening', 'Вечернее напоминание (17:00)'),
        (19, 0, 'late_evening', 'Позднее вечернее напоминание (19:00)'),
        (21, 0, 'final', 'Крайнее напоминание (21:00)')
    ]

    for hour, minute, reminder_type, name in reminders:
        scheduler.add_job(
            check_and_send_reminder,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Asia/Almaty"),
            args=[bot, reminder_type],
            id=f'reminder_{reminder_type}',
            name=name,
            replace_existing=True
        )
        logger.info(f"📅 {name} настроено")

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

    # Добавляем проверку смен каждые 5 минут
    scheduler.add_job(
        check_and_send_shift_reminder,
        trigger=CronTrigger(minute='*/5', timezone="Asia/Almaty"),
        args=[bot],
        id='shift_reminder',
        name='Напоминание о смене (за 1 час)',
        replace_existing=True
    )
    logger.info("⏰ Проверка предстоящих смен настроена (каждые 5 минут)")

    return scheduler
