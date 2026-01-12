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
        # Получаем историю остатков за последние 30 дней для стабильного среднего
        history = await db.get_stock_history(item['product_id'], days=30)
        supplies = await db.get_supply_history(item['product_id'], days=30)

        # Рассчитываем средний расход с учетом поставок
        avg_consumption, days_with_data, warning = calculate_average_consumption(history, supplies)

        enriched_stock.append({
            **item,
            'avg_daily_consumption': avg_consumption,
            'consumption_warning': warning
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
@router.message(F.text == "14 дней")
async def cmd_order(message: Message, db: Database):
    """Список товаров для закупа (стандартный - на 14 дней)"""
    await generate_order(message, db, days=14, threshold=14)


@router.message(Command("order20"))
@router.message(F.text == "20 дней")
async def cmd_order20(message: Message, db: Database):
    """Заказ на 20 дней"""
    await generate_order(message, db, days=20, threshold=20)


@router.message(Command("order30"))
@router.message(F.text == "30 дней")
async def cmd_order30(message: Message, db: Database):
    """Заказ на 30 дней"""
    await generate_order(message, db, days=30, threshold=30)


@router.message(Command("test_auto_order"))
async def cmd_test_auto_order(message: Message, db: Database):
    """
    Тестовая команда: проверить автоматический заказ с порогом 500,000₸
    """
    await message.answer("🧪 Тестирую автоматический заказ...")

    try:
        from utils.calculations import get_auto_order_with_threshold, format_auto_order_list

        # Подготавливаем данные
        stock_data = await prepare_order_data(db)

        # Получаем заказ с порогом
        products_to_order, total_cost, should_notify = get_auto_order_with_threshold(
            stock_data,
            order_days=14,
            threshold_amount=500000
        )

        # Формируем ответ
        if not should_notify:
            response = (
                f"💰 Сумма заказа: <b>{total_cost:,.0f}₸</b>\n\n"
                f"⚠️ Порог не достигнут (минимум: 500,000₸)\n"
                f"Уведомление не будет отправлено автоматически.\n\n"
                f"Товаров для закупа: {len(products_to_order)}"
            )
            await message.answer(response, parse_mode="HTML")
            return

        # Отправляем список заказа
        order_text = format_auto_order_list(products_to_order, total_cost)
        await message.answer(
            f"✅ Порог достигнут! Уведомление будет отправлено.\n\n{order_text}",
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}", parse_mode="HTML")
