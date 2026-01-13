"""
Обработчики для управления пользователями
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from middleware.auth import admin_only
from keyboards import get_main_menu

router = Router()


class UserManagementStates(StatesGroup):
    """Состояния для управления пользователями"""
    entering_user_id = State()


@router.message(Command("add_employee"))
@router.message(Command("add_admin"))
@admin_only
async def cmd_add_user(message: Message, state: FSMContext, **kwargs):
    """Начать процесс добавления пользователя"""
    role = 'admin' if 'admin' in message.text.lower() else 'employee'

    await state.set_state(UserManagementStates.entering_user_id)
    await state.update_data(role=role)

    await message.answer(
        f"👤 <b>Добавление пользователя ({role})</b>\n\n"
        f"Введите Telegram ID пользователя:\n"
        f"💡 Узнать ID: @userinfobot",
        parse_mode="HTML"
    )


@router.message(UserManagementStates.entering_user_id)
@admin_only
async def process_user_id(message: Message, state: FSMContext, db, **kwargs):
    """Обработка ID пользователя"""
    try:
        user_id = int(message.text.strip())
        data = await state.get_data()
        role = data['role']
        admin_id = message.from_user.id

        await db.update_user_role(user_id, role, admin_id)

        await message.answer(
            f"✅ <b>Пользователь добавлен!</b>\n\n"
            f"ID: {user_id}\n"
            f"Роль: {role}\n\n"
            f"Пользователь может начать работу через /start",
            parse_mode="HTML",
            reply_markup=get_main_menu(True, 'admin')
        )

        await state.clear()

    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (Telegram ID):")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


@router.message(Command("list_users"))
@router.message(F.text == "👥 Управление")
@admin_only
async def cmd_list_users(message: Message, db, **kwargs):
    """Список всех пользователей"""
    try:
        users = await db.list_users_with_roles()

        if not users:
            await message.answer("📋 Список пользователей пуст", reply_markup=get_main_menu(True, 'admin'))
            return

        lines = ["👥 <b>ПОЛЬЗОВАТЕЛИ СИСТЕМЫ</b>\n"]

        admins = [u for u in users if u['role'] == 'admin']
        employees = [u for u in users if u['role'] == 'employee']

        if admins:
            lines.append("<b>👑 Администраторы:</b>")
            for user in admins:
                name = user.get('username') or user.get('first_name') or f"ID:{user['id']}"
                status = "✅" if user['is_active'] else "⏸️"
                lines.append(f"{status} {name} (ID: {user['id']})")
            lines.append("")

        if employees:
            lines.append("<b>👷 Сотрудники:</b>")
            for user in employees:
                name = user.get('username') or user.get('first_name') or f"ID:{user['id']}"
                status = "✅" if user['is_active'] else "⏸️"
                added_by = user.get('added_by_username') or 'Система'
                lines.append(f"{status} {name} (ID: {user['id']})\n   Добавил: {added_by}")
            lines.append("")

        lines.append(f"<b>Всего:</b> {len(users)} пользователей")
        lines.append("\n💡 /add_employee или /add_admin для добавления")

        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=get_main_menu(True, 'admin'))

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
