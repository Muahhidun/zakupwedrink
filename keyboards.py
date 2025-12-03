"""
Клавиатуры для бота
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import os


def get_main_menu(is_private_chat: bool = True) -> ReplyKeyboardMarkup:
    """Главное меню бота

    Args:
        is_private_chat: True для личного чата, False для группы
    """
    web_app_url = os.getenv('WEB_APP_URL', 'http://localhost:5000')

    # В группах нельзя использовать WebApp кнопки
    if is_private_chat:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="📝 Ввод остатков (форма)",
                        web_app=WebAppInfo(url=web_app_url)
                    ),
                ],
                [
                    KeyboardButton(text="📝 Ввод остатков (чат)"),
                    KeyboardButton(text="📦 Текущие остатки"),
                ],
                [
                    KeyboardButton(text="📦 Добавить поставку"),
                    KeyboardButton(text="🛒 Список закупа"),
                ],
                [
                    KeyboardButton(text="💰 Отчеты"),
                    KeyboardButton(text="📊 Аналитика"),
                ],
                [
                    KeyboardButton(text="ℹ️ Помощь"),
                ],
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие"
        )
    else:
        # Для групп - без WebApp кнопки
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="📝 Ввод остатков (чат)"),
                    KeyboardButton(text="📦 Текущие остатки"),
                ],
                [
                    KeyboardButton(text="📦 Добавить поставку"),
                    KeyboardButton(text="🛒 Список закупа"),
                ],
                [
                    KeyboardButton(text="💰 Отчеты"),
                    KeyboardButton(text="📊 Аналитика"),
                ],
                [
                    KeyboardButton(text="ℹ️ Помощь"),
                ],
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие"
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
                KeyboardButton(text="7 дней"),
                KeyboardButton(text="10 дней"),
                KeyboardButton(text="14 дней"),
            ],
            [
                KeyboardButton(text="⬅️ Назад"),
            ],
        ],
        resize_keyboard=True
    )
    return keyboard
