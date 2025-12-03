"""
Тест новой логики расчета среднего расхода
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG
from utils.calculations import calculate_average_consumption, days_until_stockout

load_dotenv()

async def main():
    database_url = os.getenv('DATABASE_URL')
    db = DatabasePG(database_url)
    await db.init_db()

    try:
        # Находим "Порошок со вкусом молочного коктейля (сливочный)"
        products = await db.get_all_products()
        slivochny = next(
            (p for p in products if 'сливочн' in p['name_russian'].lower()),
            None
        )

        if not slivochny:
            print("❌ Порошок сливочный не найден")
            return

        print("=" * 100)
        print(f"🧪 ТЕСТ РАСЧЕТА ДЛЯ: {slivochny['name_russian']}")
        print("=" * 100)

        # Получаем историю
        history = await db.get_stock_history(slivochny['id'], days=14)
        supplies = await db.get_supply_history(slivochny['id'], days=14)

        print(f"\n📊 История остатков ({len(history)} записей):")
        for h in sorted(history, key=lambda x: x['date']):
            print(f"   {h['date']}: {h['weight']:.1f} кг ({h['quantity']:.0f} уп.)")

        print(f"\n📦 Поставки ({len(supplies)} записей):")
        for s in sorted(supplies, key=lambda x: x['date']):
            print(f"   {s['date']}: +{s['weight']:.1f} кг ({s['boxes']} кор.)")

        # Рассчитываем средний расход
        avg_consumption, days_with_data, warning = calculate_average_consumption(history, supplies)

        print(f"\n📈 РЕЗУЛЬТАТЫ РАСЧЕТА:")
        print(f"   Средний расход: {avg_consumption:.2f} кг/день")
        print(f"   Дней с данными: {days_with_data}")
        print(f"   Предупреждение: {warning if warning else 'нет'}")

        # Получаем текущий остаток
        latest_stock = await db.get_latest_stock()
        current = next(
            (s for s in latest_stock if s['product_id'] == slivochny['id']),
            None
        )

        if current:
            current_stock = current['weight']
            current_quantity = current['quantity']
            days_left = days_until_stockout(current_stock, avg_consumption)

            print(f"\n📦 ТЕКУЩИЙ ОСТАТОК:")
            print(f"   {current_quantity:.0f} упаковок ({current_stock:.1f} кг)")

            print(f"\n⏱️  ПРОГНОЗ:")
            print(f"   Хватит на: {days_left} дней")
            print(f"   Расход в день: {avg_consumption:.2f} кг (~{avg_consumption / 3:.1f} упаковок)")
            print(f"   Расход в месяц: {avg_consumption * 30:.1f} кг (~{avg_consumption * 30 / 3:.0f} упаковок)")

        print("\n" + "=" * 100)

    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
