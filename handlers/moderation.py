"""
Обработчики для модерации заявок на остатки
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from middleware.auth import admin_only
from keyboards import get_main_menu
import os

router = Router()


class ModerationStates(StatesGroup):
    """Состояния для модерации"""
    entering_rejection = State()


@router.callback_query(F.data.startswith("review_"))
@admin_only
async def callback_review_submission(callback: CallbackQuery, db, **kwargs):
    """Просмотр заявки"""
    submission_id = int(callback.data.split("_")[1])

    try:
        submission = await db.get_submission_by_id(submission_id)
        if not submission or submission['status'] != 'pending':
            await callback.answer("⚠️ Заявка не найдена или уже обработана", show_alert=True)
            return

        items = await db.get_submission_items(submission_id)

        username = submission.get('username') or submission.get('first_name') or 'Неизвестно'
        date = submission['submission_date'].strftime('%d.%m.%Y')

        lines = [
            f"📦 <b>ЗАЯВКА #{submission_id}</b>\n",
            f"👤 Сотрудник: {username}",
            f"📅 Дата: {date}",
            f"⏰ Создано: {submission['created_at'].strftime('%d.%m %H:%M')}\n",
            f"<b>Товары:</b>"
        ]

        for item in items:
            unit = item.get('unit', 'кг')
            qty = item.get('edited_quantity') or item['quantity']
            weight = item.get('edited_weight') or item['weight']

            if unit == 'шт':
                lines.append(f"• {item['name_russian']}: {qty:.0f} шт.")
            else:
                lines.append(f"• {item['name_russian']}: {qty:.0f} уп. ({weight:.1f} кг)")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Утвердить", callback_data=f"approve_{submission_id}"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{submission_id}")
            ],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{submission_id}")]
        ])

        await callback.message.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("approve_"))
@admin_only
async def callback_approve_submission(callback: CallbackQuery, db, **kwargs):
    """Утвердить заявку"""
    submission_id = int(callback.data.split("_")[1])
    admin_id = callback.from_user.id

    try:
        submitted_by = await db.approve_submission(submission_id, admin_id)

        await callback.message.edit_text(
            f"✅ <b>Заявка #{submission_id} УТВЕРЖДЕНА</b>\n\nДанные перенесены в основную базу.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Утверждено!")

        # Уведомляем сотрудника
        await callback.bot.send_message(
            chat_id=submitted_by,
            text=f"✅ <b>ЗАЯВКА УТВЕРЖДЕНА</b>\n\nВаша заявка #{submission_id} была проверена и утверждена.\n\nДанные успешно сохранены.",
            parse_mode="HTML"
        )

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("reject_"))
@admin_only
async def callback_reject_submission(callback: CallbackQuery, state: FSMContext, **kwargs):
    """Начать отклонение заявки"""
    submission_id = int(callback.data.split("_")[1])

    await state.set_state(ModerationStates.entering_rejection)
    await state.update_data(submission_id=submission_id)

    await callback.message.answer("📝 Введите причину отклонения заявки:")
    await callback.answer()


@router.message(ModerationStates.entering_rejection)
@admin_only
async def process_rejection_reason(message: Message, state: FSMContext, db, **kwargs):
    """Обработка причины отклонения"""
    data = await state.get_data()
    submission_id = data['submission_id']
    reason = message.text
    admin_id = message.from_user.id

    try:
        submitted_by = await db.reject_submission(submission_id, admin_id, reason)

        await message.answer(
            f"❌ <b>Заявка #{submission_id} ОТКЛОНЕНА</b>\n\nПричина: {reason}",
            parse_mode="HTML",
            reply_markup=get_main_menu(True, 'admin')
        )

        # Уведомляем сотрудника
        await message.bot.send_message(
            chat_id=submitted_by,
            text=f"❌ <b>ЗАЯВКА ОТКЛОНЕНА</b>\n\nВаша заявка #{submission_id} была отклонена.\n\n<b>Причина:</b> {reason}\n\nПроверьте данные и отправьте заново.",
            parse_mode="HTML"
        )

        await state.clear()

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


@router.callback_query(F.data.startswith("edit_"))
@admin_only
async def callback_edit_submission(callback: CallbackQuery, **kwargs):
    """Редактировать заявку через WebApp"""
    submission_id = int(callback.data.split("_")[1])

    web_app_url = os.getenv('WEB_APP_URL', 'http://localhost:5000')
    edit_url = f"{web_app_url}/submission_edit?id={submission_id}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Открыть редактор", web_app=WebAppInfo(url=edit_url))],
        [InlineKeyboardButton(text="« Назад", callback_data=f"review_{submission_id}")]
    ])

    await callback.message.edit_text(
        f"📝 <b>Редактирование заявки #{submission_id}</b>\n\n"
        f"Нажмите кнопку ниже для открытия редактора.\n"
        f"После изменений нажмите \"Сохранить и утвердить\".",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(Command("pending"))
@router.message(F.text == "📋 Модерация")
@admin_only
async def cmd_pending_submissions(message: Message, db, **kwargs):
    """Список ожидающих модерации заявок"""
    try:
        submissions = await db.get_pending_submissions()

        if not submissions:
            await message.answer("📋 Нет заявок на модерации", reply_markup=get_main_menu(True, 'admin'))
            return

        lines = ["📋 <b>ЗАЯВКИ НА МОДЕРАЦИИ</b>\n"]

        for sub in submissions:
            username = sub.get('username') or sub.get('first_name') or 'Неизвестно'
            date = sub['submission_date'].strftime('%d.%m.%Y')
            created = sub['created_at'].strftime('%d.%m %H:%M')

            lines.append(
                f"🔸 Заявка #{sub['id']}\n"
                f"   👤 {username}\n"
                f"   📅 {date}\n"
                f"   📦 {sub['items_count']} товаров\n"
                f"   ⏰ {created}\n"
            )

        buttons = [[InlineKeyboardButton(text=f"Заявка #{sub['id']}", callback_data=f"review_{sub['id']}")]
                   for sub in submissions[:5]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await message.answer("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.message(Command("my_submissions"))
@router.message(F.text == "📦 Мои заявки")
async def cmd_my_submissions(message: Message, db, user_role: str, **kwargs):
    """Просмотр своих заявок (для сотрудников)"""
    try:
        user_id = message.from_user.id
        submissions = await db.get_user_submissions(user_id, limit=20)

        if not submissions:
            await message.answer(
                "📋 У вас пока нет заявок",
                reply_markup=get_main_menu(True, user_role)
            )
            return

        lines = ["📋 <b>МОИ ЗАЯВКИ</b>\n"]

        status_emoji = {
            'pending': '⏳',
            'approved': '✅',
            'rejected': '❌'
        }

        for sub in submissions:
            emoji = status_emoji.get(sub['status'], '❓')
            date = sub['submission_date'].strftime('%d.%m.%Y')
            created = sub['created_at'].strftime('%d.%m %H:%M')

            status_text = {
                'pending': 'Ожидает проверки',
                'approved': 'Утверждена',
                'rejected': 'Отклонена'
            }.get(sub['status'], 'Неизвестно')

            lines.append(
                f"{emoji} Заявка #{sub['id']} - {status_text}\n"
                f"   📅 {date}\n"
                f"   📦 {sub['items_count']} товаров\n"
                f"   ⏰ {created}"
            )

            if sub['status'] == 'rejected' and sub['rejection_reason']:
                lines.append(f"   💬 Причина: {sub['rejection_reason']}")

            lines.append("")

        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=get_main_menu(True, user_role)
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
