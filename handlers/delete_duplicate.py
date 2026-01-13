"""
Handler для удаления дубликата товара "Шоколадное мороженое"
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("delete_duplicate"))
async def delete_duplicate_product(message: Message, db):
    """Удалить дубликат товара 'Шоколадное мороженое'"""

    try:
        product_name = "Шоколадное мороженое"

        # Получаем информацию о товаре
        query = "SELECT id, name_russian, name_chinese FROM products WHERE name_russian = $1"
        product = await db.pool.fetchrow(query, product_name)

        if not product:
            await message.answer(f"⚠️ Товар '{product_name}' не найден в базе данных")
            return

        product_id = product['id']

        # Проверяем связанные записи
        stock_count = await db.pool.fetchval(
            "SELECT COUNT(*) FROM stock WHERE product_id = $1",
            product_id
        )
        supply_count = await db.pool.fetchval(
            "SELECT COUNT(*) FROM supplies WHERE product_id = $1",
            product_id
        )

        # Удаляем товар и все связанные записи
        await db.pool.execute("DELETE FROM stock WHERE product_id = $1", product_id)
        await db.pool.execute("DELETE FROM supplies WHERE product_id = $1", product_id)
        await db.pool.execute("DELETE FROM products WHERE id = $1", product_id)

        result_text = (
            f"✅ <b>Товар успешно удален!</b>\n\n"
            f"📦 Товар: {product['name_russian']}\n"
            f"🔢 ID: {product_id}\n"
            f"🇨🇳 Название CN: {product['name_chinese']}\n\n"
            f"🗑️ Удалено:\n"
            f"   • Записей остатков: {stock_count}\n"
            f"   • Записей поставок: {supply_count}\n"
            f"   • Товар из базы данных"
        )

        await message.answer(result_text)

    except Exception as e:
        await message.answer(f"❌ Ошибка при удалении товара: {e}")
