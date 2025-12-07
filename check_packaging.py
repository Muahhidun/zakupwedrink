"""
Скрипт для проверки настроек упаковочных товаров
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
    print("📦 УПАКОВОЧНЫЕ ТОВАРЫ В БД")
    print("=" * 70)

    products = await db.get_all_products()
    packaging_products = [p for p in products if p.get('unit') == 'шт']

    for p in packaging_products:
        print(f"\n{p['name_russian']}:")
        print(f"  Внутреннее имя: {p['name_internal']}")
        print(f"  package_weight: {p['package_weight']} {p['unit']}")
        print(f"  units_per_box: {p['units_per_box']}")
        print(f"  box_weight: {p['box_weight']} {p['unit']}")
        print(f"  price_per_box: {p['price_per_box']:,.0f}₸")

    print("\n" + "=" * 70)
    print("📊 ОСТАТКИ УПАКОВОЧНЫХ ТОВАРОВ")
    print("=" * 70)

    stock = await db.get_latest_stock()
    for s in stock:
        if s.get('unit') == 'шт':
            print(f"\n{s['name_internal']}:")
            print(f"  quantity (введено упаковок): {s['quantity']}")
            print(f"  weight (расчёт: quantity × package_weight): {s['weight']}")
            print(f"  date: {s['date']}")

    print("\n" + "=" * 70)
    print("🔍 ИСТОРИЯ ОСТАТКОВ (Стакан 500)")
    print("=" * 70)

    # Находим product_id для Стакан 500
    cup_product = next((p for p in products if 'Стакан 500' in p.get('name_internal', '')), None)
    if cup_product:
        history = await db.get_stock_history(cup_product['id'], days=30)
        print(f"\nТовар: {cup_product['name_russian']}")
        print(f"package_weight: {cup_product['package_weight']} шт")
        print(f"\nИстория:")
        for h in history:
            print(f"  {h['date']}: quantity={h['quantity']}, weight={h['weight']}")

    await db.close()

if __name__ == '__main__':
    asyncio.run(main())
