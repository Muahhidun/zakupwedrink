"""
Отладка расчёта списка закупа
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
        print(f"   ID: {powder['id']}")
        print(f"   Unit: {powder['unit']}")
        print(f"   Package weight: {powder['package_weight']}")
        print(f"   Box weight: {powder['box_weight']}")
        print(f"   Price per box: {powder['price_per_box']:,.0f}₸")
        print("=" * 100)

        # Получаем текущие остатки
        stock = await db.get_latest_stock()
        powder_stock = None
        for s in stock:
            if s['product_id'] == powder['id']:
                powder_stock = s
                break

        if powder_stock:
            print(f"\n📊 ТЕКУЩИЕ ОСТАТКИ:")
            print(f"   Quantity: {powder_stock['quantity']}")
            print(f"   Weight: {powder_stock['weight']}")
            print(f"   Date: {powder_stock['date']}")
            print("=" * 100)

        # Получаем историю за 14 дней
        history = await db.get_stock_history(powder['id'], days=14)
        print(f"\n📜 ИСТОРИЯ ОСТАТКОВ (14 дней):")
        for h in history:
            print(f"   {h['date']}: quantity={h['quantity']}, weight={h['weight']:.1f}")
        print("=" * 100)

        # Получаем поставки за 14 дней
        supplies = await db.get_supply_history(powder['id'], days=14)
        print(f"\n🚚 ПОСТАВКИ (14 дней):")
        for s in supplies:
            print(f"   {s['date']}: boxes={s['boxes']}, weight={s['weight']:.1f}")
        print("=" * 100)

        # Рассчитываем средний расход вручную
        from utils.calculations import calculate_average_consumption, get_products_to_order, days_until_stockout

        avg_consumption, days_with_data, warning = calculate_average_consumption(history, supplies)

        print(f"\n🧮 РАСЧЁТ СРЕДНЕГО РАСХОДА:")
        print(f"   Средний расход: {avg_consumption:.2f} кг/день")
        print(f"   Дней с данными: {days_with_data}")
        print(f"   Предупреждение: {warning}")
        print("=" * 100)

        # Проверяем prepare_order_data вручную
        all_stock = await db.get_latest_stock()
        enriched = []

        for item in all_stock:
            # Получаем историю остатков за последние 14 дней
            h = await db.get_stock_history(item['product_id'], days=14)
            s = await db.get_supply_history(item['product_id'], days=14)

            # Рассчитываем средний расход с учетом поставок
            avg_cons, days_data, warn = calculate_average_consumption(h, s)

            enriched.append({
                **item,
                'avg_daily_consumption': avg_cons,
                'consumption_warning': warn
            })

        powder_enriched = None
        for e in enriched:
            if e['product_id'] == powder['id']:
                powder_enriched = e
                break

        if powder_enriched:
            print(f"\n📋 ОБОГАЩЕННЫЕ ДАННЫЕ (prepare_order_data):")
            print(f"   name_russian: {powder_enriched['name_russian']}")
            print(f"   current stock (weight): {powder_enriched['weight']:.1f}")
            print(f"   avg_daily_consumption: {powder_enriched['avg_daily_consumption']:.2f}")
            print(f"   consumption_warning: {powder_enriched['consumption_warning']}")
            print(f"   unit: {powder_enriched.get('unit', 'НЕТ UNIT!')}")

            # Вручную рассчитываем days_left
            days_left = days_until_stockout(powder_enriched['weight'], powder_enriched['avg_daily_consumption'])
            print(f"   days_left (calculated): {days_left}")
            print("=" * 100)

        # Проверяем что вернёт get_products_to_order
        to_order = get_products_to_order(enriched, days_threshold=7, order_days=10)
        powder_order = None
        for o in to_order:
            if o['product_id'] == powder['id']:
                powder_order = o
                break

        if powder_order:
            print(f"\n🛒 ДАННЫЕ ДЛЯ ЗАКАЗА (get_products_to_order):")
            print(f"   current_stock: {powder_order['current_stock']:.1f}")
            print(f"   avg_daily_consumption: {powder_order['avg_daily_consumption']:.2f}")
            print(f"   days_left: {powder_order['days_left']}")
            print(f"   needed_weight: {powder_order['needed_weight']:.1f}")
            print(f"   boxes_to_order: {powder_order['boxes_to_order']}")
            print(f"   order_cost: {powder_order['order_cost']:,.0f}₸")
            print("=" * 100)
        else:
            print(f"\n⚠️ Порошок НЕ в списке заказа (остатков хватает)")

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
