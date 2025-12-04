"""
Миграция упаковочных товаров: переход на учёт в штуках

До миграции:
- package_weight = 1000 (одна упаковка = 1000 штук)
- quantity = 6 (введено упаковок)
- weight = 6 * 1000 = 6000 (неправильно!)

После миграции:
- package_weight = 1 (одна упаковка = 1 штука)
- quantity = 6000 (введено штук)
- weight = 6000 * 1 = 6000 (правильно!)
"""
import asyncio
from database_pg import DatabasePG
import os
from dotenv import load_dotenv

load_dotenv()


async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()

    print("=" * 70)
    print("🔄 МИГРАЦИЯ УПАКОВОЧНЫХ ТОВАРОВ НА УЧЁТ В ШТУКАХ")
    print("=" * 70)

    # Получаем все упаковочные товары
    products = await db.get_all_products()
    packaging_products = [p for p in products if p.get('unit') == 'шт']

    if not packaging_products:
        print("\n❌ Упаковочных товаров не найдено")
        await db.close()
        return

    print(f"\n📦 Найдено упаковочных товаров: {len(packaging_products)}\n")

    # Для каждого упаковочного товара
    for product in packaging_products:
        product_id = product['id']
        old_package_weight = product['package_weight']
        old_units_per_box = product['units_per_box']
        old_box_weight = product['box_weight']

        print(f"\n{'='*60}")
        print(f"Товар: {product['name_russian']}")
        print(f"ID: {product_id}")
        print(f"Старые настройки:")
        print(f"  package_weight: {old_package_weight} шт")
        print(f"  units_per_box: {old_units_per_box}")
        print(f"  box_weight: {old_box_weight} шт")

        # Новые настройки
        new_package_weight = 1.0  # Одна упаковка = 1 штука
        new_units_per_box = old_box_weight  # Штук в коробке остается прежним
        new_box_weight = old_box_weight  # Общее количество штук в коробке

        print(f"\nНовые настройки:")
        print(f"  package_weight: {new_package_weight} шт")
        print(f"  units_per_box: {new_units_per_box}")
        print(f"  box_weight: {new_box_weight} шт")

        # 1. Обновляем продукт
        async with db.pool.acquire() as conn:
            await conn.execute("""
                UPDATE products
                SET package_weight = $1,
                    units_per_box = $2,
                    box_weight = $3
                WHERE id = $4
            """, new_package_weight, new_units_per_box, new_box_weight, product_id)

        print("✅ Продукт обновлён")

        # 2. Обновляем остатки (stock)
        # Логика: quantity остается в штуках, weight = quantity * new_package_weight
        async with db.pool.acquire() as conn:
            # Получаем все остатки
            stock_records = await conn.fetch("""
                SELECT id, date, quantity, weight
                FROM stock
                WHERE product_id = $1
                ORDER BY date
            """, product_id)

            if stock_records:
                print(f"\n📊 Обновление остатков ({len(stock_records)} записей):")
                for record in stock_records:
                    old_quantity = record['quantity']
                    old_weight = record['weight']

                    # Реальное количество штук = weight / old_package_weight
                    # (потому что weight = quantity * old_package_weight)
                    # Но если админ вводил напрямую штуки, то quantity УЖЕ в штуках
                    # и weight = quantity * old_package_weight (ошибочно)

                    # Правильно: quantity (введено) - это и есть штуки
                    # weight должен быть = quantity * old_package_weight
                    # Но если weight УЖЕ правильный (равен реальным штукам),
                    # значит quantity нужно оставить как есть

                    # Проверяем: если weight == quantity * old_package_weight,
                    # то админ вводил упаковки (правильно по старой логике)
                    # Если weight != quantity * old_package_weight,
                    # то админ вводил штуки напрямую (неправильно)

                    expected_weight = old_quantity * old_package_weight

                    if abs(old_weight - expected_weight) < 0.1:
                        # Админ вводил упаковки (старая логика работала правильно)
                        new_quantity = old_weight  # Реальное количество штук
                        new_weight = old_weight  # Остается прежним
                    else:
                        # Админ вводил штуки напрямую (ошибка в расчете)
                        # quantity уже в штуках, просто пересчитываем weight
                        new_quantity = old_quantity
                        new_weight = old_quantity * new_package_weight

                    await conn.execute("""
                        UPDATE stock
                        SET quantity = $1, weight = $2
                        WHERE id = $3
                    """, new_quantity, new_weight, record['id'])

                    print(f"  {record['date']}: {old_quantity} → {new_quantity} шт")

                print(f"✅ Остатки обновлены")

        # 3. Обновляем поставки (supplies)
        async with db.pool.acquire() as conn:
            supply_records = await conn.fetch("""
                SELECT id, date, boxes, weight, cost
                FROM supplies
                WHERE product_id = $1
                ORDER BY date
            """, product_id)

            if supply_records:
                print(f"\n🚚 Обновление поставок ({len(supply_records)} записей):")
                for record in supply_records:
                    old_boxes = record['boxes']
                    old_weight = record['weight']

                    # boxes остается в коробках
                    # weight = boxes * new_box_weight
                    new_boxes = old_boxes
                    new_weight = old_boxes * new_box_weight

                    await conn.execute("""
                        UPDATE supplies
                        SET boxes = $1, weight = $2
                        WHERE id = $3
                    """, new_boxes, new_weight, record['id'])

                    print(f"  {record['date']}: {old_boxes} кор. = {new_weight} шт")

                print(f"✅ Поставки обновлены")

    print("\n" + "=" * 70)
    print("✅ МИГРАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 70)
    print("\nТеперь при вводе остатков упаковочных товаров")
    print("администратор должен вводить КОЛИЧЕСТВО ШТУК напрямую.")
    print("\nНапример:")
    print("  Стакан 500: 6000 (штук)")
    print("  Толстые трубочки: 4000 (штук)")
    print("=" * 70)

    await db.close()


if __name__ == '__main__':
    asyncio.run(main())
