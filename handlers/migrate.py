"""
Handler для миграции упаковочных товаров
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("migrate_packaging"))
async def cmd_migrate_packaging(message: Message, db):
    """Миграция упаковочных товаров на учёт в штуках"""

    # Проверяем права (только для администратора)
    if message.from_user.id != 432642298:  # ID администратора
        await message.answer("❌ Эта команда доступна только администратору")
        return

    await message.answer("🔄 Начинаю миграцию упаковочных товаров...")

    try:
        # Получаем все упаковочные товары
        products = await db.get_all_products()
        packaging_products = [p for p in products if p.get('unit') == 'шт']

        if not packaging_products:
            await message.answer("❌ Упаковочных товаров не найдено")
            return

        await message.answer(f"📦 Найдено упаковочных товаров: {len(packaging_products)}")

        total_updated = 0

        # Для каждого упаковочного товара
        for product in packaging_products:
            product_id = product['id']
            old_package_weight = product['package_weight']
            old_box_weight = product['box_weight']

            # Новые настройки
            new_package_weight = 1.0  # Одна упаковка = 1 штука
            new_units_per_box = old_box_weight  # Штук в коробке
            new_box_weight = old_box_weight  # Остается прежним

            # 1. Обновляем продукт
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE products
                    SET package_weight = $1,
                        units_per_box = $2,
                        box_weight = $3
                    WHERE id = $4
                """, new_package_weight, new_units_per_box, new_box_weight, product_id)

            # 2. Обновляем остатки
            async with db.pool.acquire() as conn:
                stock_records = await conn.fetch("""
                    SELECT id, date, quantity, weight
                    FROM stock
                    WHERE product_id = $1
                    ORDER BY date
                """, product_id)

                for record in stock_records:
                    old_quantity = record['quantity']
                    old_weight = record['weight']

                    # Проверяем правильность старых данных
                    expected_weight = old_quantity * old_package_weight

                    if abs(old_weight - expected_weight) < 0.1:
                        # Данные правильные - админ вводил упаковки
                        new_quantity = old_weight  # Реальное количество штук
                        new_weight = old_weight
                    else:
                        # Админ вводил штуки напрямую
                        new_quantity = old_quantity
                        new_weight = old_quantity

                    await conn.execute("""
                        UPDATE stock
                        SET quantity = $1, weight = $2
                        WHERE id = $3
                    """, new_quantity, new_weight, record['id'])

            # 3. Обновляем поставки
            async with db.pool.acquire() as conn:
                supply_records = await conn.fetch("""
                    SELECT id, boxes, weight
                    FROM supplies
                    WHERE product_id = $1
                """, product_id)

                for record in supply_records:
                    old_boxes = record['boxes']
                    new_boxes = old_boxes
                    new_weight = old_boxes * new_box_weight

                    await conn.execute("""
                        UPDATE supplies
                        SET boxes = $1, weight = $2
                        WHERE id = $3
                    """, new_boxes, new_weight, record['id'])

            total_updated += 1
            await message.answer(f"✅ {product['name_russian']} обновлён")

        await message.answer(
            f"✅ <b>МИГРАЦИЯ ЗАВЕРШЕНА!</b>\n\n"
            f"Обновлено товаров: {total_updated}\n\n"
            f"Теперь при вводе остатков упаковочных товаров\n"
            f"вводите <b>количество штук</b> напрямую.\n\n"
            f"Например:\n"
            f"• Стакан 500: <b>6000</b> (штук)\n"
            f"• Толстые трубочки: <b>4000</b> (штук)",
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка миграции: {e}", parse_mode="HTML")
