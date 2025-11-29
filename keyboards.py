"""
Клавиатуры для бота
"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню бота"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📝 Ввод остатков"),
                KeyboardButton(text="📦 Текущие остатки"),
            ],
            [
                KeyboardButton(text="🛒 Список закупа"),
                KeyboardButton(text="💰 Отчеты"),
            ],
            [
                KeyboardButton(text="📊 Аналитика"),
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
