"""
Проверка товаров в базе данных
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    database_url = os.getenv('DATABASE_URL')
    db = DatabasePG(database_url)
    await db.init_db()

    try:
        # Получаем все товары
        products = await db.get_all_products()

        print(f"📦 ВСЕГО ТОВАРОВ В БД: {len(products)}\n")
        print("=" * 100)

        # Ищем мороженое и каппучино
        ice_cream_products = []
        cappuccino_products = []
        unit_sht_products = []

        for p in products:
            name = p['name_russian'].lower()

            if 'мороженое' in name or 'мороженное' in name:
                ice_cream_products.append(p)

            if 'каппучино' in name or 'капучино' in name:
                cappuccino_products.append(p)

            if p.get('unit') == 'шт':
                unit_sht_products.append(p)

        # Показываем мороженое
        if ice_cream_products:
            print("\n🍦 МОРОЖЕНОЕ:\n")
            for p in ice_cream_products:
                print(f"ID: {p['id']}")
                print(f"📦 {p['name_russian']}")
                print(f"   ({p['name_internal']})")
                print(f"   Вес упаковки: {p['package_weight']} {p['unit']}")
                print(f"   Упаковок в коробке: {p['units_per_box']}")
                print(f"   Вес коробки: {p['box_weight']} {p['unit']}")
                print(f"   Цена за коробку: {p['price_per_box']:,.0f} ₸")
                print("-" * 100)
        else:
            print("\n❌ Мороженое не найдено в БД\n")

        # Показываем каппучино
        if cappuccino_products:
            print("\n☕ КАППУЧИНО:\n")
            for p in cappuccino_products:
                print(f"ID: {p['id']}")
                print(f"📦 {p['name_russian']}")
                print(f"   ({p['name_internal']})")
                print(f"   Вес упаковки: {p['package_weight']} {p['unit']}")
                print(f"   Упаковок в коробке: {p['units_per_box']}")
                print(f"   Вес коробки: {p['box_weight']} {p['unit']}")
                print(f"   Цена за коробку: {p['price_per_box']:,.0f} ₸")
                print("-" * 100)
        else:
            print("\n❌ Каппучино не найдено в БД\n")

        # Показываем товары в штуках
        print(f"\n📊 ТОВАРЫ В ШТУКАХ (unit='шт'): {len(unit_sht_products)}\n")
        for p in unit_sht_products:
            print(f"ID: {p['id']} | {p['name_russian']}")
            print(f"   Упаковок в коробке: {p['units_per_box']} шт")
            print(f"   Вес упаковки: {p['package_weight']} (должно быть 1 шт)")
            print(f"   Вес коробки: {p['box_weight']} (должно быть {p['units_per_box']} шт)")
            print("-" * 100)

        # Проверяем остатки на сегодня
        print("\n\n📋 ПРОВЕРКА ОСТАТКОВ НА СЕГОДНЯ:\n")
        latest_stock = await db.get_latest_stock()

        # Ищем мороженое и каппучино в остатках
        stock_ice_cream = [s for s in latest_stock if 'мороженое' in s['name_russian'].lower() or 'мороженное' in s['name_russian'].lower()]
        stock_cappuccino = [s for s in latest_stock if 'каппучино' in s['name_russian'].lower() or 'капучино' in s['name_russian'].lower()]

        if stock_ice_cream:
            print("🍦 Мороженое в остатках:")
            for s in stock_ice_cream:
                print(f"   • {s['name_russian']}: {s['quantity']:.0f} уп. ({s['weight']:.1f} {s.get('unit', 'кг')})")
        else:
            print("❌ Мороженое в остатках НЕ найдено")

        if stock_cappuccino:
            print("\n☕ Каппучино в остатках:")
            for s in stock_cappuccino:
                print(f"   • {s['name_russian']}: {s['quantity']:.0f} уп. ({s['weight']:.1f} {s.get('unit', 'кг')})")
        else:
            print("❌ Каппучино в остатках НЕ найдено")

    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
