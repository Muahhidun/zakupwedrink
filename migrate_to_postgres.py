"""
Скрипт миграции данных из SQLite в PostgreSQL
"""
import asyncio
import os
from database import Database as SQLiteDB
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def migrate_data():
    """Мигрировать данные из SQLite в PostgreSQL"""
    sqlite_path = os.getenv('DATABASE_PATH', 'wedrink.db')
    postgres_url = os.getenv('DATABASE_URL')

    if not postgres_url:
        print("❌ DATABASE_URL не найден в .env файле")
        return

    print(f"📦 Начинаем миграцию из {sqlite_path} в PostgreSQL...")

    # Инициализация баз данных
    sqlite_db = SQLiteDB(sqlite_path)
    postgres_db = DatabasePG(postgres_url)

    await sqlite_db.init_db()
    await postgres_db.init_db()

    try:
        # 1. Миграция товаров
        print("\n1️⃣  Миграция товаров...")
        products = await sqlite_db.get_all_products()
        product_id_map = {}  # Маппинг старых ID на новые

        for product in products:
            try:
                new_id = await postgres_db.add_product(
                    name_chinese=product['name_chinese'],
                    name_russian=product['name_russian'],
                    name_internal=product['name_internal'],
                    package_weight=product['package_weight'],
                    units_per_box=product['units_per_box'],
                    price_per_box=product['price_per_box'],
                    unit=product.get('unit', 'кг')
                )
                product_id_map[product['id']] = new_id
                print(f"   ✅ {product['name_internal']}: {product['id']} → {new_id}")
            except Exception as e:
                print(f"   ⚠️  {product['name_internal']}: уже существует или ошибка: {e}")
                # Если товар уже есть, получаем его ID
                existing = await postgres_db.get_product_by_name(product['name_internal'])
                if existing:
                    product_id_map[product['id']] = existing['id']

        print(f"   📊 Всего товаров: {len(products)}")

        # 2. Миграция остатков
        print("\n2️⃣  Миграция остатков...")
        # Получаем все уникальные даты
        async with sqlite_db.pool if hasattr(sqlite_db, 'pool') else sqlite_db.db_path as conn:
            import aiosqlite
            async with aiosqlite.connect(sqlite_path) as conn:
                async with conn.execute("SELECT DISTINCT date FROM stock ORDER BY date") as cursor:
                    dates = await cursor.fetchall()

        stock_count = 0
        for (date,) in dates:
            stock_items = await sqlite_db.get_stock_by_date(date)
            for item in stock_items:
                old_product_id = item['product_id']
                new_product_id = product_id_map.get(old_product_id)

                if new_product_id:
                    try:
                        await postgres_db.add_stock(
                            product_id=new_product_id,
                            date=item['date'],
                            quantity=item['quantity'],
                            weight=item['weight']
                        )
                        stock_count += 1
                    except Exception as e:
                        print(f"   ⚠️  Ошибка добавления остатка для {date}: {e}")

        print(f"   📊 Всего записей остатков: {stock_count}")

        # 3. Миграция поставок
        print("\n3️⃣  Миграция поставок...")
        async with aiosqlite.connect(sqlite_path) as conn:
            async with conn.execute("SELECT * FROM supplies ORDER BY date") as cursor:
                conn.row_factory = aiosqlite.Row
                async with conn.execute("SELECT * FROM supplies ORDER BY date") as cursor:
                    supplies = await cursor.fetchall()

        supply_count = 0
        for supply in supplies:
            old_product_id = supply['product_id']
            new_product_id = product_id_map.get(old_product_id)

            if new_product_id:
                try:
                    await postgres_db.add_supply(
                        product_id=new_product_id,
                        date=supply['date'],
                        boxes=supply['boxes'],
                        weight=supply['weight'],
                        cost=supply['cost']
                    )
                    supply_count += 1
                except Exception as e:
                    print(f"   ⚠️  Ошибка добавления поставки: {e}")

        print(f"   📊 Всего поставок: {supply_count}")

        print("\n✅ Миграция завершена успешно!")
        print("\n📝 Следующие шаги:")
        print("   1. Проверьте данные в PostgreSQL")
        print("   2. Убедитесь, что DATABASE_URL добавлен в Railway")
        print("   3. Задеплойте обновленный код")

    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await postgres_db.close()


if __name__ == '__main__':
    asyncio.run(migrate_data())
