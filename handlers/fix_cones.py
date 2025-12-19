"""
Обработчик для исправления данных по рожкам (admin команда)
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from database_pg import DatabasePG

router = Router()


@router.message(Command("fix_cones"))
async def cmd_fix_cones(message: Message, db: DatabasePG):
    """
    Исправить данные по хрустящим рожкам в базе данных
    Паллет = 16 коробок по 400 рожков = 6400 рожков за 175,000 ₸
    """
    await message.answer("🔧 Исправляю данные по рожкам...")

    async with db.pool.acquire() as conn:
        # Обновляем данные
        await conn.execute("""
            UPDATE products
            SET
                package_weight = 1.0,
                units_per_box = 400,
                unit = 'шт',
                price_per_box = 10937.5,
                box_weight = 400.0
            WHERE name_internal = 'Хрустящие рожки по 400 штук'
        """)

        # Проверяем результат
        row = await conn.fetchrow("""
            SELECT * FROM products
            WHERE name_internal = 'Хрустящие рожки по 400 штук'
        """)

        response = (
            "✅ <b>Данные по рожкам обновлены:</b>\n\n"
            f"📦 Название: {row['name_internal']}\n"
            f"⚖️ Фасовка: {row['package_weight']} {row['unit']} × {row['units_per_box']} шт\n"
            f"📊 Вес коробки: {row['box_weight']} {row['unit']}\n"
            f"💰 Цена за коробку: {row['price_per_box']:,.1f} ₸\n\n"
            f"📦 Минимальный закуп: 16 коробок (паллет) = 6,400 рожков за 175,000 ₸"
        )

        await message.answer(response, parse_mode="HTML")
