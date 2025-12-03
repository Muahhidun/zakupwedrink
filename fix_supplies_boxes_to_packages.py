"""
Исправить поставки: boxes → packages
Данные были в упаковках, а записались как коробки
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
        print("\n" + "=" * 100)
        print("🔧 ИСПРАВЛЕНИЕ ПОСТАВОК: коробки → упаковки")
        print("=" * 100)

        async with db.pool.acquire() as conn:
            # Получаем все поставки с информацией о товарах
            supplies = await conn.fetch("""
                SELECT
                    s.id,
                    s.product_id,
                    s.date,
                    s.boxes,
                    s.weight,
                    s.cost,
                    p.name_russian,
                    p.package_weight,
                    p.units_per_box,
                    p.price_per_box,
                    p.unit
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                ORDER BY s.date DESC
            """)

            print(f"\nНайдено {len(supplies)} поставок\n")

            fixed_count = 0
            for s in supplies:
                # Текущие значения
                old_boxes = s['boxes']
                old_weight = s['weight']
                old_cost = s['cost']

                # Правильные значения (boxes на самом деле packages)
                packages = old_boxes  # То что записано в boxes - это упаковки
                new_weight = packages * s['package_weight']  # Правильный вес

                # Правильная стоимость
                if s['unit'] == 'кг':
                    # Для товаров в кг: стоимость = (упаковки / упаковок_в_коробке) × цена_коробки
                    boxes_real = packages / s['units_per_box']
                    new_cost = boxes_real * s['price_per_box']
                else:
                    # Для товаров в шт: стоимость = (упаковки / упаковок_в_коробке) × цена_коробки
                    boxes_real = packages / s['units_per_box']
                    new_cost = boxes_real * s['price_per_box']

                # Обновляем только weight и cost
                # boxes оставляем как есть (это упаковки, но колонка называется boxes)
                await conn.execute("""
                    UPDATE supplies
                    SET weight = $1, cost = $2
                    WHERE id = $3
                """, new_weight, new_cost, s['id'])

                print(f"✅ {s['date'].strftime('%d.%m.%Y')} - {s['name_russian']}")
                print(f"   Упаковок: {packages:.0f}")
                print(f"   Вес: {old_weight:.1f} → {new_weight:.1f} {s['unit']}")
                print(f"   Стоимость: {old_cost:,.0f}₸ → {new_cost:,.0f}₸")
                print("-" * 100)

                fixed_count += 1

            print(f"\n✅ Исправлено {fixed_count} поставок")

        print("=" * 100)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
