"""
Детальная отладка алгоритма расчёта среднего расхода
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

        print(f"\n📦 ТОВАР: {powder['name_russian']}")
        print("=" * 120)

        # Получаем историю за 21 день
        history = await db.get_stock_history(powder['id'], days=21)
        supplies = await db.get_supply_history(powder['id'], days=21)

        print(f"\n📜 ИСТОРИЯ ОСТАТКОВ:")
        for h in history:
            print(f"   {h['date']}: {h['weight']:.1f} кг")

        print(f"\n🚚 ПОСТАВКИ:")
        for s in supplies:
            print(f"   {s['date']}: {s['weight']:.1f} кг")
        print("=" * 120)

        # РАСЧЁТ ЧЕРЕЗ НАСТОЯЩУЮ ФУНКЦИЮ
        from utils.calculations import calculate_average_consumption

        avg_consumption, days_with_data, warning = calculate_average_consumption(history, supplies)

        print(f"\n🧮 РЕЗУЛЬТАТ calculate_average_consumption():")
        print("=" * 120)
        print(f"   📊 Средний расход: {avg_consumption:.2f} кг/день")
        print(f"   Дней с данными: {days_with_data}")
        print(f"   Предупреждение: {warning}")
        print("=" * 120)

        # Проверяем все поставки в БД
        print(f"\n🔍 ПРОВЕРКА ВСЕХ ПОСТАВОК В БД:")
        async with db.pool.acquire() as conn:
            all_supplies = await conn.fetch("""
                SELECT * FROM supplies
                WHERE product_id = $1
                ORDER BY date
            """, powder['id'])

            for s in all_supplies:
                print(f"   {s['date']}: boxes={s['boxes']}, weight={s['weight']:.1f} кг")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
