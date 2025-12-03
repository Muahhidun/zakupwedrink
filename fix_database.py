"""
Комплексное исправление базы данных:
1. Добавить недостающие товары
2. Исправить package_weight для штучных товаров
3. Исправить цену рожков
4. Удалить дубликаты поставок
5. Пересчитать weight в supplies
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

# ЦЕНЫ ДЛЯ НОВЫХ ТОВАРОВ (вводить вручную)
NEW_PRODUCTS = [
    {
        "name_chinese": "原味冰淇淋粉",
        "name_russian": "Шоколадное мороженое",
        "name_internal": "Шоколадное мороженое",
        "package_weight": 3.0,
        "units_per_box": 8,
        "price_per_box": 63000,
        "unit": "кг"
    },
    {
        "name_chinese": "WE.封口膜",
        "name_russian": "Плёнка для запайки стаканов",
        "name_internal": "Плёнка для запайки стаканов",
        "package_weight": 1,  # 1 рулон
        "units_per_box": 12,
        "price_per_box": 68600,
        "unit": "шт"
    },
    {
        "name_chinese": "WE.双杯袋",
        "name_russian": "Пакет для двух чашек",
        "name_internal": "Пакет для двух чашек",
        "package_weight": 1,  # 1 пакет
        "units_per_box": 5000,
        "price_per_box": 47600,
        "unit": "шт"
    },
    {
        "name_chinese": "吨吨桶（新）",
        "name_russian": "Стакан большой 900мл",
        "name_internal": "Стакан большой 900мл",
        "package_weight": 1,
        "units_per_box": 200,
        "price_per_box": 21840,
        "unit": "шт"
    },
]

async def main():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL не найден")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    try:
        print("\n" + "=" * 100)
        print("🔧 КОМПЛЕКСНОЕ ИСПРАВЛЕНИЕ БАЗЫ ДАННЫХ")
        print("=" * 100)

        # ============================================================
        # ШАГ 1: Добавить недостающие товары
        # ============================================================
        print("\n📦 ШАГ 1: Добавление недостающих товаров...")

        for product in NEW_PRODUCTS:
            # Проверяем, есть ли уже такой товар
            existing = await db.get_product_by_name(product['name_internal'])
            if existing:
                print(f"   ⏭️  {product['name_russian']} - уже существует")
            else:
                product_id = await db.add_product(
                    name_chinese=product['name_chinese'],
                    name_russian=product['name_russian'],
                    name_internal=product['name_internal'],
                    package_weight=product['package_weight'],
                    units_per_box=product['units_per_box'],
                    price_per_box=product['price_per_box'],
                    unit=product['unit']
                )
                print(f"   ✅ Добавлен: {product['name_russian']} (ID: {product_id})")

        # ============================================================
        # ШАГ 2: Исправить package_weight для штучных товаров
        # ============================================================
        print("\n🔧 ШАГ 2: Исправление package_weight для товаров в штуках...")

        async with db.pool.acquire() as conn:
            # Получаем все товары в штуках с неправильным package_weight
            products_to_fix = await conn.fetch("""
                SELECT id, name_russian, package_weight, units_per_box, box_weight
                FROM products
                WHERE unit = 'шт' AND package_weight != 1
            """)

            if products_to_fix:
                print(f"   Найдено {len(products_to_fix)} товаров для исправления:")

                for p in products_to_fix:
                    old_package_weight = p['package_weight']
                    old_box_weight = p['box_weight']
                    new_package_weight = 1
                    new_box_weight = new_package_weight * p['units_per_box']

                    # Обновляем товар
                    await conn.execute("""
                        UPDATE products
                        SET package_weight = $1, box_weight = $2
                        WHERE id = $3
                    """, new_package_weight, new_box_weight, p['id'])

                    print(f"   ✅ {p['name_russian']}")
                    print(f"      package_weight: {old_package_weight} → {new_package_weight}")
                    print(f"      box_weight: {old_box_weight:,.0f} → {new_box_weight:,.0f}")
            else:
                print("   ✅ Все товары в штуках уже исправлены")

        # ============================================================
        # ШАГ 3: Исправить цену рожков (паллета → коробка)
        # ============================================================
        print("\n💰 ШАГ 3: Исправление цены рожков...")

        async with db.pool.acquire() as conn:
            rozhki = await conn.fetchrow("""
                SELECT id, name_russian, price_per_box, units_per_box
                FROM products
                WHERE name_internal LIKE '%рожк%' OR name_internal LIKE '%Хрустящие%'
            """)

            if rozhki:
                old_price = rozhki['price_per_box']
                # Цена за паллету (16 коробок) = 155,560₸
                # Цена за 1 коробку = 155,560 / 16 = 9,722.5₸
                new_price = 155560 / 16

                await conn.execute("""
                    UPDATE products
                    SET price_per_box = $1
                    WHERE id = $2
                """, new_price, rozhki['id'])

                print(f"   ✅ {rozhki['name_russian']}")
                print(f"      Цена за коробку: {old_price:,.0f}₸ → {new_price:,.2f}₸")
                print(f"      (было: цена за паллету, стало: цена за коробку)")
            else:
                print("   ⚠️  Рожки не найдены в БД")

        # ============================================================
        # ШАГ 4: Удалить дубликаты поставок
        # ============================================================
        print("\n🗑️  ШАГ 4: Удаление дубликатов поставок...")

        async with db.pool.acquire() as conn:
            # Находим дубликаты
            duplicates = await conn.fetch("""
                SELECT
                    date,
                    product_id,
                    COUNT(*) as count,
                    ARRAY_AGG(id ORDER BY id) as ids
                FROM supplies
                GROUP BY date, product_id
                HAVING COUNT(*) > 1
            """)

            if duplicates:
                total_deleted = 0
                for dup in duplicates:
                    # Удаляем все кроме первой записи (с минимальным ID)
                    ids_to_delete = dup['ids'][1:]  # Все кроме первого

                    await conn.execute("""
                        DELETE FROM supplies
                        WHERE id = ANY($1)
                    """, ids_to_delete)

                    total_deleted += len(ids_to_delete)

                print(f"   ✅ Удалено {total_deleted} дублирующихся записей")
            else:
                print("   ✅ Дубликатов не найдено")

        # ============================================================
        # ШАГ 5: Пересчитать weight в supplies для штучных товаров
        # ============================================================
        print("\n⚖️  ШАГ 5: Пересчёт weight в таблице supplies для штучных товаров...")

        async with db.pool.acquire() as conn:
            # Находим поставки штучных товаров с неправильным весом
            wrong_supplies = await conn.fetch("""
                SELECT
                    s.id,
                    s.product_id,
                    s.boxes,
                    s.weight,
                    p.name_russian,
                    p.units_per_box,
                    p.unit
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE p.unit = 'шт'
            """)

            if wrong_supplies:
                print(f"   Найдено {len(wrong_supplies)} поставок штучных товаров:")

                for s in wrong_supplies:
                    # Правильный вес = boxes * units_per_box
                    correct_weight = s['boxes'] * s['units_per_box']

                    if s['weight'] != correct_weight:
                        await conn.execute("""
                            UPDATE supplies
                            SET weight = $1
                            WHERE id = $2
                        """, correct_weight, s['id'])

                        print(f"   ✅ {s['name_russian']}: {s['boxes']} кор.")
                        print(f"      weight: {s['weight']:,.0f} → {correct_weight:,.0f} шт")
                    else:
                        print(f"   ⏭️  {s['name_russian']}: уже правильный вес")
            else:
                print("   ✅ Поставок штучных товаров не найдено")

        print("\n" + "=" * 100)
        print("✅ ВСЕ ИСПРАВЛЕНИЯ ЗАВЕРШЕНЫ!")
        print("=" * 100)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
