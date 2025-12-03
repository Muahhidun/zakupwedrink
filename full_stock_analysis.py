#!/usr/bin/env python3
"""
Полный анализ остатков всех товаров
"""
import asyncio
import os
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def calculate_average_consumption(history):
    """Рассчитать средний дневной расход"""
    if len(history) < 2:
        return 0.0

    sorted_history = sorted(history, key=lambda x: x['date'])
    first = sorted_history[0]
    last = sorted_history[-1]

    days_diff = (last['date'] - first['date']).days
    if days_diff == 0:
        return 0.0

    weight_diff = first['weight'] - last['weight']
    if weight_diff <= 0:
        return 0.0

    return weight_diff / days_diff


async def main():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ERROR: DATABASE_URL не установлен")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    print("=" * 100)
    print("📊 ПОЛНЫЙ АНАЛИЗ ОСТАТКОВ ВСЕХ ТОВАРОВ")
    print("=" * 100)
    print()

    latest_stock = await db.get_latest_stock()

    if not latest_stock:
        print("❌ Нет данных об остатках")
        await db.close()
        return

    THRESHOLD_DAYS = 7

    all_products = []

    for item in latest_stock:
        product_id = item['product_id']
        current_stock = item['weight']

        history = await db.get_stock_history(product_id, days=7)

        if len(history) < 2:
            status = "⚠️  Недостаточно истории"
            avg_daily = 0.0
            days_left = 999
        else:
            avg_daily = await calculate_average_consumption(history)

            if avg_daily <= 0:
                status = "✅ Расход = 0 (не используется)"
                days_left = 999
            else:
                days_left = current_stock / avg_daily

                if days_left < THRESHOLD_DAYS:
                    status = f"🔴 СРОЧНО! Хватит на {days_left:.1f} дней"
                elif days_left < 14:
                    status = f"🟡 Скоро закончится ({days_left:.1f} дней)"
                else:
                    status = f"✅ В норме ({days_left:.1f} дней)"

        all_products.append({
            'name': item['name_internal'],
            'stock': current_stock,
            'avg_daily': avg_daily,
            'days_left': days_left,
            'status': status,
            'history_count': len(history)
        })

    # Сортируем по дням до исчерпания
    all_products.sort(key=lambda x: x['days_left'])

    print(f"Всего товаров: {len(all_products)}\n")

    for i, prod in enumerate(all_products, 1):
        print(f"{i}. {prod['name']}")
        print(f"   Остаток: {prod['stock']:.1f} кг")
        print(f"   Расход: {prod['avg_daily']:.2f} кг/день")
        print(f"   Статус: {prod['status']}")
        print()

    # Статистика
    need_order = [p for p in all_products if p['days_left'] < THRESHOLD_DAYS and p['avg_daily'] > 0]
    warning = [p for p in all_products if THRESHOLD_DAYS <= p['days_left'] < 14 and p['avg_daily'] > 0]
    ok = [p for p in all_products if p['days_left'] >= 14]

    print("=" * 100)
    print("📊 СТАТИСТИКА:")
    print(f"   🔴 Нужно заказать срочно: {len(need_order)} товаров")
    print(f"   🟡 Скоро закончатся: {len(warning)} товаров")
    print(f"   ✅ В норме: {len(ok)} товаров")
    print("=" * 100)

    await db.close()


if __name__ == '__main__':
    asyncio.run(main())
