"""
Фикс: Рожки — price_per_box должна быть цена за коробку, а не за паллету.
Паллета = 175,000 ₸, в ней 16 коробок.
Цена за коробку = 175,000 / 16 = 10,937.5 ₸
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database_pg import DatabasePG

PALLET_PRICE = 175_000
BOXES_PER_PALLET = 16
CORRECT_PRICE_PER_BOX = PALLET_PRICE / BOXES_PER_PALLET  # 10,937.5

async def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ Установите DATABASE_URL")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    products = await db.get_all_products()

    # Найти рожки
    candidates = [p for p in products if "ожк" in (p.get("name_internal") or "").lower()
                  or "рожк" in (p.get("name_internal") or "").lower()]

    if not candidates:
        print("❌ Рожки не найдены. Все товары:")
        for p in products:
            print(f"  ID={p['id']}: {p['name_internal']} — {p['price_per_box']}₸")
        await db.pool.close()
        return

    for p in candidates:
        pid = p["id"]
        name = p["name_internal"]
        old_price = p["price_per_box"]

        print(f"Найден: ID={pid}, '{name}'")
        print(f"  Текущая price_per_box: {old_price:,.1f} ₸")
        print(f"  Паллета: {PALLET_PRICE:,} ₸ / {BOXES_PER_PALLET} коробок = {CORRECT_PRICE_PER_BOX:,.1f} ₸ за коробку")

        if abs(old_price - CORRECT_PRICE_PER_BOX) < 1:
            print(f"  ✅ Цена уже правильная")
            continue

        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE products SET price_per_box = $1 WHERE id = $2",
                CORRECT_PRICE_PER_BOX, pid
            )
        print(f"  ✅ Обновлено: {old_price:,.1f} → {CORRECT_PRICE_PER_BOX:,.1f} ₸")

    await db.pool.close()

asyncio.run(main())
