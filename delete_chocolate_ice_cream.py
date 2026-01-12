"""
Скрипт для удаления товара "Шоколадное мороженое" из базы данных
Этот товар дублирует "Порошок со вкусом молочного коктейля (шоколадный) 3кг"
"""
import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def delete_duplicate_product():
    """Удалить дубликат товара 'Шоколадное мороженое'"""
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        print("❌ DATABASE_URL не установлен")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    try:
        # Ищем товар по названию
        product_name = "Шоколадное мороженое"

        # Получаем информацию о товаре
        query = "SELECT id, name_ru, name_cn FROM products WHERE name_ru = $1"
        product = await db.pool.fetchrow(query, product_name)

        if not product:
            print(f"⚠️ Товар '{product_name}' не найден в базе данных")
            await db.close()
            return

        product_id = product['id']
        print(f"✅ Найден товар: {product['name_ru']} (ID: {product_id})")
        print(f"   Китайское название: {product['name_cn']}")

        # Проверяем связанные записи
        stock_count = await db.pool.fetchval(
            "SELECT COUNT(*) FROM stock WHERE product_id = $1",
            product_id
        )
        supply_count = await db.pool.fetchval(
            "SELECT COUNT(*) FROM supplies WHERE product_id = $1",
            product_id
        )

        print(f"\n📊 Связанные данные:")
        print(f"   - Записей остатков: {stock_count}")
        print(f"   - Записей поставок: {supply_count}")

        # Удаляем товар и все связанные записи
        print(f"\n🗑️ Удаление товара и связанных данных...")

        # Сначала удаляем связанные записи
        await db.pool.execute("DELETE FROM stock WHERE product_id = $1", product_id)
        print(f"   ✅ Удалено {stock_count} записей остатков")

        await db.pool.execute("DELETE FROM supplies WHERE product_id = $1", product_id)
        print(f"   ✅ Удалено {supply_count} записей поставок")

        # Затем удаляем сам товар
        await db.pool.execute("DELETE FROM products WHERE id = $1", product_id)
        print(f"   ✅ Удален товар '{product_name}'")

        print(f"\n✅ Товар '{product_name}' успешно удален из базы данных!")

    except Exception as e:
        print(f"❌ Ошибка при удалении товара: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(delete_duplicate_product())
