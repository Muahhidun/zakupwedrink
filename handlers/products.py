"""
Справочник товаров и цен
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from database import Database
from keyboards import get_main_menu

router = Router()


@router.message(Command("products"))
async def cmd_products(message: Message, db: Database):
    """Показать справочник всех товаров"""
    products = await db.get_all_products()

    if not products:
        await message.answer("❌ Нет товаров в базе")
        return

    lines = ["📋 <b>СПРАВОЧНИК ТОВАРОВ</b>\n"]

    for product in products:
        price_per_kg = product['price_per_box'] / product['box_weight'] if product['box_weight'] > 0 else 0

        lines.append(
            f"<b>{product['name_internal']}</b>\n"
            f"├─ Упаковка: {product['package_weight']} {product['unit']}\n"
            f"├─ В коробке: {product['units_per_box']} шт.\n"
            f"├─ Вес коробки: {product['box_weight']} кг\n"
            f"└─ Цена: {product['price_per_box']:,.0f}₸ ({price_per_kg:,.0f}₸/кг)\n"
        )

    # Разбиваем на несколько сообщений если слишком длинное
    message_text = "\n".join(lines)

    # Telegram ограничение ~4096 символов на сообщение
    if len(message_text) > 4000:
        # Отправляем по частям
        current_message = ["📋 <b>СПРАВОЧНИК ТОВАРОВ</b>\n"]
        current_length = len(current_message[0])

        for i, product in enumerate(products):
            price_per_kg = product['price_per_box'] / product['box_weight'] if product['box_weight'] > 0 else 0

            product_text = (
                f"<b>{product['name_internal']}</b>\n"
                f"├─ Упаковка: {product['package_weight']} {product['unit']}\n"
                f"├─ В коробке: {product['units_per_box']} шт.\n"
                f"├─ Вес коробки: {product['box_weight']} кг\n"
                f"└─ Цена: {product['price_per_box']:,.0f}₸ ({price_per_kg:,.0f}₸/кг)\n\n"
            )

            if current_length + len(product_text) > 4000:
                # Отправляем текущее сообщение
                await message.answer("\n".join(current_message), parse_mode="HTML")
                current_message = [product_text]
                current_length = len(product_text)
            else:
                current_message.append(product_text)
                current_length += len(product_text)

        # Отправляем последнее сообщение
        if current_message:
            await message.answer(
                "\n".join(current_message),
                reply_markup=get_main_menu(),
                parse_mode="HTML"
            )
    else:
        await message.answer(message_text, reply_markup=get_main_menu(), parse_mode="HTML")
