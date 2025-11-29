"""
Обработчики для фиксации поставок
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from database import Database
from keyboards import get_main_menu

router = Router()


class SupplyInput(StatesGroup):
    selecting_product = State()
    entering_boxes = State()


async def show_product_selection(message: Message, state: FSMContext, db: Database):
    """Показать список товаров для выбора"""
    products = await db.get_all_products()

    # Создаем inline кнопки для каждого товара (по 2 в ряд)
    keyboard_buttons = []
    row = []

    for product in products:
        button = InlineKeyboardButton(
            text=product['name_internal'],
            callback_data=f"supply_product_{product['id']}"
        )
        row.append(button)

        if len(row) == 2:
            keyboard_buttons.append(row)
            row = []

    # Добавляем оставшиеся кнопки
    if row:
        keyboard_buttons.append(row)

    # Кнопка "Завершить поставку"
    keyboard_buttons.append([
        InlineKeyboardButton(
            text="✅ Завершить поставку",
            callback_data="supply_finish"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        "📦 <b>Добавление поставки</b>\n\n"
        "Выберите товар который пришел:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("supply"))
@router.message(F.text == "📦 Добавить поставку")
async def cmd_supply(message: Message, state: FSMContext, db: Database):
    """Начать добавление поставки"""
    await state.set_state(SupplyInput.selecting_product)
    await state.update_data(supply_items={})  # Словарь: product_id -> boxes

    await show_product_selection(message, state, db)


@router.callback_query(F.data.startswith("supply_product_"))
async def process_product_selection(callback: CallbackQuery, state: FSMContext, db: Database):
    """Обработка выбора товара"""
    product_id = int(callback.data.split("_")[2])

    # Получаем информацию о товаре
    products = await db.get_all_products()
    product = next((p for p in products if p['id'] == product_id), None)

    if not product:
        await callback.answer("❌ Товар не найден")
        return

    # Сохраняем выбранный товар
    await state.update_data(selected_product_id=product_id)
    await state.set_state(SupplyInput.entering_boxes)

    await callback.message.edit_text(
        f"📦 <b>{product['name_internal']}</b>\n"
        f"({product['name_russian']})\n\n"
        f"В коробке: {product['units_per_box']} шт. ({product['box_weight']} кг)\n"
        f"Цена: {product['price_per_box']:,.0f}₸\n\n"
        f"<b>Введите количество коробок:</b>",
        parse_mode="HTML"
    )

    await callback.answer()


@router.message(SupplyInput.entering_boxes)
async def process_boxes_input(message: Message, state: FSMContext, db: Database):
    """Обработка ввода количества коробок"""
    try:
        boxes = int(message.text)
        if boxes <= 0:
            await message.answer("❌ Количество должно быть больше 0")
            return
    except ValueError:
        await message.answer("❌ Введите число (например: 3)")
        return

    # Получаем данные из state
    data = await state.get_data()
    product_id = data['selected_product_id']
    supply_items = data.get('supply_items', {})

    # Добавляем товар в список поставки
    supply_items[product_id] = boxes
    await state.update_data(supply_items=supply_items)

    # Получаем товар для подтверждения
    products = await db.get_all_products()
    product = next((p for p in products if p['id'] == product_id), None)

    units = boxes * product['units_per_box']
    weight = boxes * product['box_weight']

    await message.answer(
        f"✅ Добавлено:\n"
        f"<b>{product['name_internal']}</b>: {boxes} кор. "
        f"({units} уп. = {weight:.1f} кг)",
        parse_mode="HTML"
    )

    # Возвращаемся к выбору товара
    await state.set_state(SupplyInput.selecting_product)
    await show_product_selection(message, state, db)


@router.callback_query(F.data == "supply_finish")
async def process_finish_supply(callback: CallbackQuery, state: FSMContext, db: Database):
    """Завершение поставки и показ черновика"""
    data = await state.get_data()
    supply_items = data.get('supply_items', {})

    if not supply_items:
        await callback.answer("⚠️ Не выбрано ни одного товара")
        return

    # Получаем все товары
    products = await db.get_all_products()

    # Формируем черновик
    lines = ["📦 <b>ЧЕРНОВИК ПОСТАВКИ</b>\n"]
    total_cost = 0

    for product_id, boxes in supply_items.items():
        product = next((p for p in products if p['id'] == product_id), None)
        if not product:
            continue

        units = boxes * product['units_per_box']
        weight = boxes * product['box_weight']
        cost = boxes * product['price_per_box']
        total_cost += cost

        lines.append(
            f"• <b>{product['name_internal']}</b>: {boxes} кор.\n"
            f"  ({units} уп. = {weight:.1f} кг) = {cost:,.0f}₸"
        )

    lines.append(f"\n💰 <b>Общая сумма: {total_cost:,.0f}₸</b>")

    # Кнопки подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="supply_confirm"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="supply_cancel")
        ]
    ])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(F.data == "supply_confirm")
async def process_confirm_supply(callback: CallbackQuery, state: FSMContext, db: Database):
    """Подтверждение поставки и обновление остатков"""
    data = await state.get_data()
    supply_items = data.get('supply_items', {})

    if not supply_items:
        await callback.answer("❌ Нет данных о поставке")
        return

    # Получаем все товары и текущие остатки
    products = await db.get_all_products()
    current_stock = await db.get_latest_stock()

    today = datetime.now().strftime('%Y-%m-%d')
    updated = 0

    for product_id, boxes in supply_items.items():
        product = next((p for p in products if p['id'] == product_id), None)
        if not product:
            continue

        # Находим текущий остаток
        stock_item = next((s for s in current_stock if s['product_id'] == product_id), None)
        current_quantity = stock_item['quantity'] if stock_item else 0

        # Рассчитываем новое количество
        units_added = boxes * product['units_per_box']
        new_quantity = current_quantity + units_added
        new_weight = new_quantity * product['package_weight']

        # Сохраняем поставку в таблицу supplies
        weight_added = boxes * product['box_weight']
        cost = boxes * product['price_per_box']

        await db.add_supply(
            product_id=product_id,
            date=today,
            boxes=boxes,
            weight=weight_added,
            cost=cost
        )

        # Обновляем остатки
        await db.add_stock(
            product_id=product_id,
            date=today,
            quantity=new_quantity,
            weight=new_weight
        )

        updated += 1

    await callback.message.edit_text(
        f"✅ <b>Поставка зафиксирована!</b>\n\n"
        f"Обновлено позиций: {updated}\n"
        f"Дата: {today}\n\n"
        f"Остатки на складе обновлены.",
        parse_mode="HTML"
    )

    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_menu()
    )

    await state.clear()
    await callback.answer("✅ Поставка подтверждена")


@router.callback_query(F.data == "supply_cancel")
async def process_cancel_supply(callback: CallbackQuery, state: FSMContext):
    """Отмена поставки"""
    await callback.message.edit_text(
        "❌ <b>Поставка отменена</b>\n\n"
        "Данные не сохранены.",
        parse_mode="HTML"
    )

    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_main_menu()
    )

    await state.clear()
    await callback.answer("Поставка отменена")
