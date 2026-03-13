"""
Клавиатуры для бота
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import os


def get_main_menu(is_private_chat: bool = True, user_role: str = 'employee') -> ReplyKeyboardMarkup:
    """Главное меню бота

    Args:
        is_private_chat: True для личного чата, False для группы
        user_role: 'employee' или 'admin'
    """
    web_app_url = os.getenv('WEB_APP_URL', 'http://localhost:5000')

    # В группах - базовое меню без ввода остатков
    if not is_private_chat:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📦 Текущие остатки"), KeyboardButton(text="🛒 Список закупа")],
                [KeyboardButton(text="💰 Отчеты"), KeyboardButton(text="📊 Аналитика")],
            ],
            resize_keyboard=True
        )
        return keyboard

    # Личный чат
    if user_role == 'employee':
        # СОТРУДНИК - только ввод и свои заявки
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Ввести остатки", web_app=WebAppInfo(url=web_app_url))],
                [KeyboardButton(text="📦 Мои заявки")],
            ],
            resize_keyboard=True,
            input_field_placeholder="Введите остатки"
        )
        # АДМИН - оставляем только кнопку перехода в веб-апп, все остальное он сделает там
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="💎 Открыть Управление", web_app=WebAppInfo(url=web_app_url))
                ]
            ],
            resize_keyboard=True,
            input_field_placeholder="Откройте панель управления"
        )

    return keyboard


def get_reports_menu() -> ReplyKeyboardMarkup:
    """Меню отчетов"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Вчера"),
                KeyboardButton(text="📆 Неделя"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True
    )
    return keyboard


def get_order_menu() -> ReplyKeyboardMarkup:
    """Меню заказов"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="14 дней"),
                KeyboardButton(text="20 дней"),
                KeyboardButton(text="30 дней"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True
    )
    return keyboard
