"""
Обработчики для формирования заказов
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from database import Database
from keyboards import get_main_menu
from utils.calculations import (
    calculate_average_consumption,
    days_until_stockout,
    get_products_to_order,
    format_order_list
)

router = Router()


async def prepare_order_data(db: Database):
    """Подготовить данные для формирования заказа"""
    stock = await db.get_latest_stock()
    enriched_stock = []

    for item in stock:
        # Получаем историю остатков за последние 7 дней
        history = await db.get_stock_history(item['product_id'], days=7)

        # Рассчитываем средний расход
        avg_consumption = calculate_average_consumption(history)

        enriched_stock.append({
            **item,
            'avg_daily_consumption': avg_consumption
        })

    return enriched_stock


async def generate_order(message: Message, db: Database, days: int, threshold: int = 7):
    """Универсальная функция генерации заказа"""
    await message.answer("⏳ Рассчитываю заказ...")

    stock_data = await prepare_order_data(db)
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=threshold,
        order_days=days
    )

    order_text = format_order_list(products_to_order)
    await message.answer(order_text, reply_markup=get_main_menu(), parse_mode="HTML")


@router.message(Command("order"))
@router.message(F.text == "10 дней")
async def cmd_order(message: Message, db: Database):
    """Список товаров для закупа (стандартный - на 10 дней)"""
    await generate_order(message, db, days=10, threshold=7)


@router.message(Command("order14"))
@router.message(F.text == "14 дней")
async def cmd_order14(message: Message, db: Database):
    """Заказ на 14 дней"""
    await generate_order(message, db, days=14, threshold=7)


@router.message(Command("order7"))
@router.message(F.text == "7 дней")
async def cmd_order7(message: Message, db: Database):
    """Заказ на 7 дней"""
    await generate_order(message, db, days=7, threshold=5)
