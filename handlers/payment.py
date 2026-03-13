"""
Обработчики для функции оплаты подписки (Kaspi Pay Concierge MVP)
"""
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from database_pg import DatabasePG

logger = logging.getLogger(__name__)
router = Router()

class PaymentFlow(StatesGroup):
    waiting_for_phone = State()

@router.callback_query(F.data.startswith("pay_subscription_"))
async def process_pay_subscription(callback: CallbackQuery, state: FSMContext, db: DatabasePG):
    """Нажатие на кнопку оплаты подписки"""
    company_id = int(callback.data.split("_")[2])
    
    # Сохраняем company_id в состояние
    await state.update_data(company_id=company_id)
    
    await callback.message.answer(
        "📱 <b>Оплата подписки (Kaspi Pay)</b>\n\n"
        "Пожалуйста, введите номер телефона, на который зарегистрировано ваше приложение Kaspi, "
        "чтобы мы могли выставить вам счет на оплату.\n\n"
        "<i>Формат: +77012345678 или 87012345678</i>",
        parse_mode="HTML"
    )
    await state.set_state(PaymentFlow.waiting_for_phone)
    await callback.answer()

@router.message(PaymentFlow.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext, bot: Bot, db: DatabasePG):
    """Получение номера телефона и отправка заявки суперадминам"""
    phone = message.text.strip()
    data = await state.get_data()
    company_id = data.get("company_id")
    
    # Базовая валидация номера (только цифры и +)
    if not phone.replace('+', '').isdigit() or len(phone) < 10:
        await message.answer("❌ Неверный формат номера. Пожалуйста, введите корректный номер (например, +77012345678):")
        return

    company_info = await db.get_company(company_id)
    company_name = company_info.get('name_russian') or company_info.get('name_internal') if company_info else f"ID {company_id}"

    # Отправляем уведомление пользователю
    await message.answer(
        "✅ <b>Запрос отправлен!</b>\n\n"
        "Мы выставим вам счет в приложении Kaspi Pay в ближайшее время. "
        "После оплаты подписка будет активирована автоматически, и вы получите уведомление.",
        parse_mode="HTML"
    )
    await state.clear()
    
    # Отправляем заявку суперадминам (company_id = 1, role = admin)
    super_admins = await db.get_admins_for_company(1)
    
    admin_msg = (
        f"🔴 <b>Запрос на оплату подписки!</b>\n\n"
        f"<b>Точка:</b> {company_name} (ID: {company_id})\n"
        f"<b>От:</b> @{message.from_user.username or message.from_user.first_name}\n"
        f"<b>Телефон Kaspi:</b> <code>{phone}</code>\n\n"
        f"<i>Выставьте счет клиенту через Kaspi Pay, а после получения оплаты "
        f"нажмите на одну из кнопок ниже для активации подписки.</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Активировать (1 мес)", callback_data=f"sub_extend_{company_id}_1")],
        [InlineKeyboardButton(text="🟢 Активировать (6 мес)", callback_data=f"sub_extend_{company_id}_6")],
        [InlineKeyboardButton(text="🟢 Активировать (1 год)", callback_data=f"sub_extend_{company_id}_12")]
    ])
    
    for admin_id in super_admins:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=admin_msg,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"❌ Не удалось отправить заявку суперадмину {admin_id}: {e}")

@router.callback_query(F.data.startswith("sub_extend_"))
async def process_sub_extend(callback: CallbackQuery, bot: Bot, db: DatabasePG, scheduler: AsyncIOScheduler):
    """Суперадмин активирует подписку"""
    parts = callback.data.split("_")
    company_id = int(parts[2])
    months = int(parts[3])
    
    company_info = await db.get_company(company_id)
    if not company_info:
        await callback.answer("Ошибка: компания не найдена", show_alert=True)
        return
        
    current_end = company_info.get("subscription_end")
    if not current_end:
        current_end = datetime.now(ZoneInfo("Asia/Almaty"))
    
    # Если подписка уже истекла, отсчитываем от сегодняшнего дня
    now = datetime.now(ZoneInfo("Asia/Almaty")).replace(tzinfo=None)
    if isinstance(current_end, datetime) and current_end < now:
        current_end = now
    
    # Продлеваем на месяц(ы)
    # Приблизительно 1 месяц = 30 дней
    days_to_add = months * 30
    
    success = await db.extend_company_subscription(company_id, days_to_add)
    
    if success:
        new_company_info = await db.get_company(company_id)
        new_end = new_company_info.get("subscription_end").strftime('%d.%m.%Y')
        
        await callback.message.edit_text(
            f"{callback.message.html_text}\n\n"
            f"✅ <b>Подписка успешно продлена!</b>\n"
            f"Новая дата окончания: {new_end}",
            parse_mode="HTML"
        )
        await callback.answer(f"Продлено на {months} мес.")
        
        # Уведомляем админов точки
        client_admins = await db.get_admins_for_company(company_id)
        for admin_id in client_admins:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"🎉 <b>Подписка активирована!</b>\n\n"
                         f"Оплата получена. Доступ к системе продлен до <b>{new_end}</b>.\n"
                         f"Спасибо, что вы с нами!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
                
        # Если есть приостановленные cron (хотя они не приостанавливаются для конкретной компании),
        # мы просто пропускали их в scheduler.py
    else:
        await callback.answer("❌ Ошибка при обновлении базы данных", show_alert=True)
