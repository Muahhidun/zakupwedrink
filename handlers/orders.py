"""
Обработчики для формирования заказов
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from database import Database
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


@router.message(Command("order"))
async def cmd_order(message: Message, db: Database):
    """Список товаров для закупа (стандартный - на 10 дней)"""
    await message.answer("⏳ Рассчитываю заказ...")

    stock_data = await prepare_order_data(db)
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=7,  # Заказываем если осталось меньше недели
        order_days=10       # Заказываем на 10 дней
    )

    order_text = format_order_list(products_to_order)
    await message.answer(order_text, parse_mode="HTML")


@router.message(Command("order14"))
async def cmd_order14(message: Message, db: Database):
    """Заказ на 14 дней"""
    await message.answer("⏳ Рассчитываю заказ на 14 дней...")

    stock_data = await prepare_order_data(db)
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=7,
        order_days=14
    )

    order_text = format_order_list(products_to_order)
    await message.answer(order_text, parse_mode="HTML")


@router.message(Command("order7"))
async def cmd_order7(message: Message, db: Database):
    """Заказ на 7 дней"""
    await message.answer("⏳ Рассчитываю заказ на 7 дней...")

    stock_data = await prepare_order_data(db)
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=5,
        order_days=7
    )

    order_text = format_order_list(products_to_order)
    await message.answer(order_text, parse_mode="HTML")
