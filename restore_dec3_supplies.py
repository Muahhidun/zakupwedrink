"""
Восстановить поставки 3 декабря (откатить неправильное исправление)
3 декабря вводили КОРОБКИ через бота, а не упаковки
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG
from datetime import date

load_dotenv()

async def main():
    database_url = os.getenv('DATABASE_URL')
    db = DatabasePG(database_url)
    await db.init_db()

    try:
        print("\n" + "=" * 100)
        print("🔄 ВОССТАНОВЛЕНИЕ ПОСТАВОК 3 ДЕКАБРЯ")
        print("=" * 100)

        async with db.pool.acquire() as conn:
            # Получаем поставки 3 декабря
            supplies = await conn.fetch("""
                SELECT
                    s.id,
                    s.product_id,
                    s.date,
                    s.boxes,
                    s.weight,
                    s.cost,
                    p.name_russian,
                    p.box_weight,
                    p.price_per_box,
                    p.unit
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = $1
                ORDER BY s.id
            """, date(2025, 12, 3))

            print(f"\nНайдено {len(supplies)} поставок за 3 декабря\n")

            for s in supplies:
                # Правильные значения (boxes = коробки)
                boxes = s['boxes']
                correct_weight = boxes * s['box_weight']
                correct_cost = boxes * s['price_per_box']

                # Обновляем
                await conn.execute("""
                    UPDATE supplies
                    SET weight = $1, cost = $2
                    WHERE id = $3
                """, correct_weight, correct_cost, s['id'])

                print(f"✅ {s['name_russian']}")
                print(f"   Коробок: {boxes:.0f}")
                print(f"   Вес: {s['weight']:.1f} → {correct_weight:.1f} {s['unit']}")
                print(f"   Стоимость: {s['cost']:,.0f}₸ → {correct_cost:,.0f}₸")
                print("-" * 100)

            print(f"\n✅ Восстановлено {len(supplies)} поставок")

        print("=" * 100)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
