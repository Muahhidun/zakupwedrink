"""
Проверка данных за начало декабря
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()

    try:
        # Найти порошок сливочный
        products = await db.get_all_products()
        powder = None
        for p in products:
            if 'сливочн' in p['name_russian'].lower():
                powder = p
                break

        if not powder:
            print("❌ Не найден порошок сливочный")
            return

        print(f"📦 ТОВАР: {powder['name_russian']}")
        print("=" * 100)

        # Получаем ВСЕ остатки за декабрь
        async with db.pool.acquire() as conn:
            stocks = await conn.fetch("""
                SELECT date, quantity, weight
                FROM stock
                WHERE product_id = $1
                  AND date >= '2025-12-01'
                ORDER BY date
            """, powder['id'])

            print(f"\n📊 ОСТАТКИ ЗА ДЕКАБРЬ:")
            if stocks:
                for s in stocks:
                    print(f"   {s['date']}: {s['quantity']:.0f} уп. = {s['weight']:.1f} кг")
            else:
                print("   ❌ Нет записей!")

            # Получаем поставки за декабрь
            supplies = await conn.fetch("""
                SELECT date, boxes, weight, cost
                FROM supplies
                WHERE product_id = $1
                  AND date >= '2025-12-01'
                ORDER BY date
            """, powder['id'])

            print(f"\n🚚 ПОСТАВКИ ЗА ДЕКАБРЬ:")
            if supplies:
                for s in supplies:
                    print(f"   {s['date']}: {s['boxes']:.0f} кор. = {s['weight']:.1f} кг ({s['cost']:,.0f}₸)")
            else:
                print("   ❌ Нет записей!")

            print("=" * 100)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
