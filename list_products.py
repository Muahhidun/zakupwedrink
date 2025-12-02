#!/usr/bin/env python3
"""
Показать список всех товаров в базе данных
Используйте эти названия в add_historical_stock.py
"""
import asyncio
import os
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def main():
    """Показать все товары"""

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ERROR: DATABASE_URL не установлен в .env")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    products = await db.get_all_products()

    print("\n" + "=" * 70)
    print(f"📦 СПИСОК ТОВАРОВ В БАЗЕ ДАННЫХ ({len(products)} шт.)")
    print("=" * 70)
    print("\nИспользуйте эти названия в add_historical_stock.py:\n")

    for i, product in enumerate(products, 1):
        print(f"{i:2}. \"{product['name_internal']}\"")
        print(f"    Упаковка: {product['package_weight']:.2f} {product['unit']} × {product['units_per_box']} = {product['box_weight']:.2f} {product['unit']}/коробка")
        print()

    await db.close()

    print("=" * 70)
    print("💡 Копируйте названия точно как указано (с учетом регистра)")
    print("=" * 70)


if __name__ == '__main__':
    asyncio.run(main())
