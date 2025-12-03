#!/usr/bin/env python3
"""
Добавить шоколадный порошок для мороженого в базу данных
"""
import asyncio
import os
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def main():
    """Добавить шоколадный порошок"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ERROR: DATABASE_URL не установлен")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    print("✅ Подключено к PostgreSQL\n")

    # Проверим, не существует ли уже такой товар
    products = await db.get_all_products()
    for p in products:
        if 'шоколадный' in p['name_internal'].lower() and 'коктейль' in p['name_internal'].lower():
            print(f"⚠️  Товар уже существует: {p['name_internal']} (ID: {p['id']})")
            await db.close()
            return

    # Добавляем шоколадный порошок с теми же параметрами что у сливочного
    print("📦 Добавляю товар: Порошок со вкусом молочного коктейля (шоколадный)  3кг")

    product_id = await db.add_product(
        name_chinese="巧克力冰淇淋粉 Шоколадный порошок для мороженого",
        name_russian="Порошок со вкусом молочного коктейля (шоколадный)  3кг",
        name_internal="Порошок со вкусом молочного коктейля (шоколадный)  3кг",
        package_weight=3.0,
        units_per_box=8,
        price_per_box=56000.0,  # Та же цена что у сливочного
        unit="кг"
    )

    print(f"✅ Товар добавлен! ID: {product_id}")
    print(f"   Упаковка: 3.0 кг")
    print(f"   В коробке: 8 упаковок")
    print(f"   Коробка: 24.0 кг")
    print(f"   Закупочная цена: 56,000 ₸/кор")

    await db.close()

    print("\n💡 Теперь можете запустить повторный импорт:")
    print("   python3 import_user_data.py")


if __name__ == '__main__':
    asyncio.run(main())
