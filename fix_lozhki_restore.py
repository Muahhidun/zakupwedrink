"""
Срочный откат: скрипт fix_rozhki_price случайно изменил цены ложек.
Восстанавливаем правильные цены.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database_pg import DatabasePG

FIXES = {
    "Ложка большая (черная) (2000шт/кор)": 30000.0,
    "Ложка маленькая (белая) (1000шт/кор)": 8400.0,
}

async def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ Установите DATABASE_URL")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    for name, correct_price in FIXES.items():
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, price_per_box FROM products WHERE name_internal = $1", name
            )
            if row:
                print(f"ID={row['id']}, '{name}': {row['price_per_box']:,.1f} → {correct_price:,.1f} ₸")
                await conn.execute(
                    "UPDATE products SET price_per_box = $1 WHERE id = $2",
                    correct_price, row['id']
                )
                print(f"  ✅ Восстановлено!")
            else:
                print(f"❌ Не найден: {name}")

    # Проверяем рожки — должны остаться 10,937.5
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, price_per_box FROM products WHERE name_internal LIKE '%ожки%'"
        )
        if row:
            print(f"\nРожки (ID={row['id']}): price_per_box = {row['price_per_box']:,.1f} ₸ ✅")

    await db.pool.close()

asyncio.run(main())
