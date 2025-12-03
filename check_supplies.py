"""
Временный скрипт для проверки данных о поставках
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

# Загружаем переменные окружения
load_dotenv()

async def main():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL не найден")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    try:
        # Получаем все поставки с информацией о товарах
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    s.id,
                    s.date,
                    p.name_russian,
                    p.name_internal,
                    s.boxes,
                    s.weight,
                    s.cost,
                    s.created_at
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                ORDER BY s.date DESC, s.created_at DESC
            """)

            if not rows:
                print("📦 Поставок в базе данных нет")
                return

            print(f"📦 ДАННЫЕ О ПОСТАВКАХ (всего: {len(rows)})\n")
            print("=" * 80)

            for row in rows:
                print(f"\nID: {row['id']}")
                print(f"📅 Дата: {row['date'].strftime('%d.%m.%Y')}")
                print(f"📦 Товар: {row['name_russian']}")
                print(f"   ({row['name_internal']})")
                print(f"📊 Коробок: {row['boxes']}")
                print(f"⚖️  Вес: {row['weight']:.2f} кг")
                print(f"💰 Стоимость: {row['cost']:,.0f} ₸")
                print(f"🕐 Создано: {row['created_at'].strftime('%d.%m.%Y %H:%M:%S')}")
                print("-" * 80)

    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
