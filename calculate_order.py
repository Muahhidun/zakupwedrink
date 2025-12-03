#!/usr/bin/env python3
"""
Расчет списка закупа на основе исторических данных
"""
import asyncio
import os
from datetime import datetime, timedelta
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def calculate_average_consumption(history):
    """Рассчитать средний дневной расход"""
    if len(history) < 2:
        return 0.0

    # Сортируем по дате (от старых к новым)
    sorted_history = sorted(history, key=lambda x: x['date'])

    # Берём разницу между первым и последним значением
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
    """Рассчитать список закупа"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ERROR: DATABASE_URL не установлен")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    print("=" * 80)
    print("📋 РАСЧЕТ СПИСКА ЗАКУПА НА 10 ДНЕЙ")
    print("=" * 80)
    print()

    # Получаем последние остатки
    latest_stock = await db.get_latest_stock()

    if not latest_stock:
        print("❌ Нет данных об остатках")
        await db.close()
        return

    # Параметры
    ORDER_DAYS = 10  # На сколько дней заказываем
    THRESHOLD_DAYS = 7  # Порог: если товара хватит меньше чем на N дней - включаем в заказ

    products_to_order = []

    for item in latest_stock:
        product_id = item['product_id']
        current_stock = item['weight']

        # Получаем историю за последние 7 дней
        history = await db.get_stock_history(product_id, days=7)

        if len(history) < 2:
            continue

        # Рассчитываем средний дневной расход
        avg_daily = await calculate_average_consumption(history)

        if avg_daily <= 0:
            continue

        # Дни до исчерпания = текущий остаток / средний дневной расход
        days_until_out = current_stock / avg_daily if avg_daily > 0 else 999

        # Если товара хватит меньше чем на THRESHOLD_DAYS дней - включаем в заказ
        if days_until_out < THRESHOLD_DAYS:
            # Нужно заказать столько, чтобы хватило на ORDER_DAYS дней
            needed_weight = avg_daily * ORDER_DAYS
            to_order_weight = needed_weight - current_stock

            if to_order_weight > 0:
                # Переводим в коробки
                box_weight = item['box_weight']
                boxes_needed = to_order_weight / box_weight
                boxes_to_order = round(boxes_needed, 1)

                if boxes_to_order >= 0.5:  # Минимум пол-коробки
                    products_to_order.append({
                        'name': item['name_internal'],
                        'current_stock': current_stock,
                        'avg_daily': avg_daily,
                        'days_left': days_until_out,
                        'boxes_to_order': boxes_to_order,
                        'box_weight': box_weight,
                        'total_weight': boxes_to_order * box_weight,
                        'price_per_box': item['price_per_box'],
                        'total_cost': boxes_to_order * item['price_per_box']
                    })

    # Сортируем по дням до исчерпания (самые срочные первыми)
    products_to_order.sort(key=lambda x: x['days_left'])

    if not products_to_order:
        print("✅ Все товары в достаточном количестве!")
        print("Ничего заказывать не нужно.")
    else:
        print(f"🛒 <b>Найдено товаров для заказа: {len(products_to_order)}</b>\n")

        total_cost = 0

        for i, item in enumerate(products_to_order, 1):
            print(f"{i}. <b>{item['name']}</b>")
            print(f"   Сейчас на складе: {item['current_stock']:.1f} кг")
            print(f"   Средний расход: {item['avg_daily']:.2f} кг/день")
            print(f"   Дней до исчерпания: {item['days_left']:.1f}")
            print(f"   📦 <b>Заказать: {item['boxes_to_order']} кор.</b> ({item['total_weight']:.1f} кг)")
            print(f"   💰 Стоимость: {item['total_cost']:,.0f}₸")
            print()

            total_cost += item['total_cost']

        print("=" * 80)
        print(f"💵 <b>ИТОГО:</b> {total_cost:,.0f}₸")
        print("=" * 80)

    await db.close()


if __name__ == '__main__':
    asyncio.run(main())
