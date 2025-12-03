"""
Проверка поставок за 3 декабря
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG
from datetime import date

load_dotenv()

async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()
    try:
        async with db.pool.acquire() as conn:
            supplies = await conn.fetch("""
                SELECT
                    s.date,
                    p.name_russian,
                    p.name_chinese,
                    s.boxes as packages,
                    s.weight,
                    p.package_weight,
                    p.units_per_box,
                    p.unit,
                    s.cost
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = $1
                ORDER BY s.id
            """, date(2025, 12, 3))

            print('\n📦 ПОСТАВКИ ЗА 03.12.2025 (после исправления):\n')
            print('=' * 120)

            for s in supplies:
                packages = s['packages']
                boxes = packages / s['units_per_box']

                print(f"{s['name_russian']}")
                print(f"   Китайское: {s['name_chinese']}")
                print(f"   Упаковок: {packages:.0f} × {s['package_weight']}{s['unit']} = {s['weight']:.1f} {s['unit']}")
                print(f"   Коробок: {boxes:.2f} (по {s['units_per_box']} уп/кор)")
                print(f"   Стоимость: {s['cost']:,.0f}₸")
                print('-' * 120)
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
