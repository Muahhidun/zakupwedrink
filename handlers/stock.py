"""
Обработчики для работы с остатками на складе
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from database import Database
from keyboards import get_main_menu

router = Router()


class StockInput(StatesGroup):
    entering_stock = State()


async def start_stock_input(message: Message, state: FSMContext, db: Database):
    """Начать ввод остатков"""
    products = await db.get_all_products()

    if not products:
        await message.answer("❌ В базе нет товаров! Сначала импортируйте данные.")
        return

    await state.set_state(StockInput.entering_stock)
    await state.update_data(products=products, current_index=0, stock_data={})

    product = products[0]
    await message.answer(
        f"📝 <b>Ввод остатков на {datetime.now().strftime('%d.%m.%Y')}</b>\n\n"
        f"1/{len(products)} <b>{product['name_internal']}</b>\n"
        f"({product['name_russian']})\n"
        f"Вес упаковки: {product['package_weight']} {product['unit']}\n\n"
        f"Введите <b>количество упаковок</b> (или 0 если нет):",
        parse_mode="HTML"
    )


@router.message(StockInput.entering_stock)
async def process_stock_input(message: Message, state: FSMContext, db: Database):
    """Обработка ввода остатков"""
    data = await state.get_data()
    products = data['products']
    current_index = data['current_index']
    stock_data = data['stock_data']

    # Парсим количество упаковок
    try:
        quantity = float(message.text.replace(',', '.'))
        if quantity < 0:
            await message.answer("❌ Количество не может быть отрицательным. Попробуйте еще раз:")
            return
    except ValueError:
        await message.answer("❌ Введите число (например: 10 или 0):")
        return

    # Рассчитываем вес
    product = products[current_index]
    weight = quantity * product['package_weight']

    # Сохраняем данные
    stock_data[product['id']] = {
        'weight': weight,
        'quantity': quantity
    }

    # Переходим к следующему товару
    current_index += 1

    if current_index < len(products):
        # Еще есть товары
        await state.update_data(current_index=current_index, stock_data=stock_data)
        product = products[current_index]

        await message.answer(
            f"{current_index + 1}/{len(products)} <b>{product['name_internal']}</b>\n"
            f"({product['name_russian']})\n"
            f"Вес упаковки: {product['package_weight']} {product['unit']}\n\n"
            f"Введите <b>количество упаковок</b>:",
            parse_mode="HTML"
        )
    else:
        # Все товары введены, сохраняем в БД
        today = datetime.now().strftime('%Y-%m-%d')
        saved = 0
        total_weight = 0

        for product_id, data in stock_data.items():
            try:
                await db.add_stock(
                    product_id=product_id,
                    date=today,
                    quantity=data['quantity'],
                    weight=data['weight']
                )
                saved += 1
                total_weight += data['weight']
            except Exception as e:
                print(f"Ошибка сохранения: {e}")

        await state.clear()
        await message.answer(
            f"✅ <b>Остатки сохранены!</b>\n\n"
            f"Товаров: {saved}\n"
            f"Общий вес: {total_weight:.1f} кг\n"
            f"Дата: {today}\n\n"
            f"Нажмите 🛒 Список закупа чтобы посмотреть что нужно заказать",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )


@router.message(Command("current"))
async def cmd_current(message: Message, db: Database):
    """Показать текущие остатки"""
    stock = await db.get_latest_stock()

    if not stock:
        await message.answer("❌ Нет данных об остатках")
        return

    lines = ["📦 <b>ТЕКУЩИЕ ОСТАТКИ</b>\n"]

    for item in stock:
        # Показываем и упаковки и вес
        packages = item['quantity']
        weight = item['weight']
        lines.append(
            f"• {item['name_internal']}: "
            f"<b>{packages:.0f} уп.</b> ({weight:.1f} кг)"
        )

    await message.answer("\n".join(lines), reply_markup=get_main_menu(), parse_mode="HTML")


# Обработчики команд и кнопок
@router.message(Command("stock"))
@router.message(F.text == "📝 Ввод остатков")
async def cmd_stock(message: Message, state: FSMContext, db: Database):
    """Команда и кнопка для ввода остатков"""
    await start_stock_input(message, state, db)


@router.message(Command("current"))
@router.message(F.text == "📦 Текущие остатки")
async def cmd_current_handler(message: Message, db: Database):
    """Команда и кнопка для текущих остатков"""
    await cmd_current(message, db)
