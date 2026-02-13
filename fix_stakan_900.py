"""
Фикс: переименовать Стакан большой 900мл в БД.
Миграция не нашла его из-за опечатки в старом имени.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database_pg import DatabasePG

NEW_NAME = "Стакан большой 900мл (200шт/кор)"

async def main():
    db = DatabasePG()
    await db.initialize()

    products = await db.get_all_products()

    # Найти стакан 900мл по частичному совпадению
    candidates = [p for p in products if "900" in (p.get("name_internal") or "")]

    if not candidates:
        # Попробуем поискать по китайскому имени
        candidates = [p for p in products if "吨吨桶" in (p.get("name_chinese") or "")]

    if not candidates:
        print("❌ Стакан 900мл не найден в БД. Вот все товары:")
        for p in products:
            print(f"  ID={p['id']}: {p['name_internal']}")
        return

    for p in candidates:
        old_name = p["name_internal"]
        pid = p["id"]

        if old_name == NEW_NAME:
            print(f"✅ Уже переименован: {old_name}")
            return

        print(f"Найден: ID={pid}, '{old_name}' → '{NEW_NAME}'")

        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE products SET name_internal = $1 WHERE id = $2",
                NEW_NAME, pid
            )
        print(f"✅ Переименовано!")

    await db.pool.close()

asyncio.run(main())
