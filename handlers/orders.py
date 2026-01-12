"""
Обработчики для формирования заказов
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import Database
from keyboards import get_main_menu
from utils.calculations import (
    calculate_average_consumption,
    days_until_stockout,
    get_products_to_order,
    format_order_list,
    format_editable_order_list,
    format_edit_item_menu
)

router = Router()


class OrderStates(StatesGroup):
    """Состояния для работы с заказами"""
    waiting_for_save = State()


async def prepare_order_data(db: Database):
    """Подготовить данные для формирования заказа с учетом товаров в пути"""
    stock = await db.get_latest_stock()
    enriched_stock = []

    for item in stock:
        # Получаем историю остатков за последние 30 дней для стабильного среднего
        history = await db.get_stock_history(item['product_id'], days=30)
        supplies = await db.get_supply_history(item['product_id'], days=30)

        # Рассчитываем средний расход с учетом поставок
        avg_consumption, days_with_data, warning = calculate_average_consumption(history, supplies)

        # Получаем вес товара в активных заказах (в пути)
        pending_weight = await db.get_pending_weight_for_product(item['product_id'])

        enriched_stock.append({
            **item,
            'avg_daily_consumption': avg_consumption,
            'consumption_warning': warning,
            'pending_weight': pending_weight  # Добавляем вес в пути
        })

    return enriched_stock


async def generate_order(message: Message, db: Database, days: int,
                        threshold: int = 7, state: FSMContext = None):
    """Универсальная функция генерации заказа"""
    await message.answer("⏳ Рассчитываю заказ с учетом товаров в пути...")

    stock_data = await prepare_order_data(db)
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=threshold,
        order_days=days,
        include_pending=True  # Учитываем товары в пути
    )

    if not products_to_order:
        await message.answer(
            "✅ Все товары в наличии (с учетом заказов в пути)!\n"
            "Заказывать ничего не нужно.",
            reply_markup=get_main_menu()
        )
        return

    # Используем редактируемый формат с inline кнопками
    order_text, keyboard = format_editable_order_list(products_to_order)

    # Сохраняем данные заказа в state для последующего редактирования
    if state:
        await state.update_data(
            products_to_order=products_to_order,
            order_days=days
        )
        await state.set_state(OrderStates.waiting_for_save)

    await message.answer(
        order_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.message(Command("order"))
@router.message(F.text == "14 дней")
async def cmd_order(message: Message, db: Database, state: FSMContext):
    """Список товаров для закупа (стандартный - на 14 дней)"""
    await generate_order(message, db, days=14, threshold=14, state=state)


@router.message(Command("order20"))
@router.message(F.text == "20 дней")
async def cmd_order20(message: Message, db: Database, state: FSMContext):
    """Заказ на 20 дней"""
    await generate_order(message, db, days=20, threshold=20, state=state)


@router.message(Command("order30"))
@router.message(F.text == "30 дней")
async def cmd_order30(message: Message, db: Database, state: FSMContext):
    """Заказ на 30 дней"""
    await generate_order(message, db, days=30, threshold=30, state=state)


@router.callback_query(F.data.startswith("edit_item_"))
async def callback_edit_item(callback: CallbackQuery, db: Database, state: FSMContext):
    """Показать меню редактирования товара"""
    try:
        product_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])

        # Находим товар
        product = None
        index = 0
        for i, p in enumerate(products_to_order, 1):
            if p['product_id'] == product_id:
                product = p
                index = i
                break

        if not product:
            await callback.answer("❌ Товар не найден", show_alert=True)
            return

        # Показываем меню редактирования
        text, keyboard = format_edit_item_menu(product, index)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "back_to_order_list")
async def callback_back_to_list(callback: CallbackQuery, db: Database, state: FSMContext):
    """Вернуться к списку заказа"""
    try:
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])

        if products_to_order:
            order_text, keyboard = format_editable_order_list(products_to_order)
            await callback.message.edit_text(order_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text("✅ Все товары удалены из заказа", parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("edit_dec_"))
async def callback_edit_decrease(callback: CallbackQuery, db: Database, state: FSMContext):
    """Уменьшить количество коробок на 1"""
    try:
        product_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])

        # Находим товар и уменьшаем количество
        product = None
        index = 0
        for i, p in enumerate(products_to_order, 1):
            if p['product_id'] == product_id:
                if p['boxes_to_order'] > 1:
                    p['boxes_to_order'] -= 1
                    p['needed_weight'] = p['boxes_to_order'] * p['box_weight']
                    p['order_cost'] = p['boxes_to_order'] * p['price_per_box']
                    product = p
                    index = i
                else:
                    # Если было 1, то удаляем товар и возвращаемся к списку
                    products_to_order.remove(p)
                    await state.update_data(products_to_order=products_to_order)

                    if products_to_order:
                        order_text, keyboard = format_editable_order_list(products_to_order)
                        await callback.message.edit_text(order_text, reply_markup=keyboard, parse_mode="HTML")
                        await callback.answer("✅ Товар удален")
                    else:
                        await callback.message.edit_text("✅ Все товары удалены из заказа", parse_mode="HTML")
                        await state.clear()
                        await callback.answer()
                    return
                break

        # Обновляем state
        await state.update_data(products_to_order=products_to_order)

        # Обновляем меню редактирования товара
        if product:
            text, keyboard = format_edit_item_menu(product, index)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("edit_inc_"))
async def callback_edit_increase(callback: CallbackQuery, db: Database, state: FSMContext):
    """Увеличить количество коробок на 1"""
    try:
        product_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])

        # Находим товар и увеличиваем количество
        product = None
        index = 0
        for i, p in enumerate(products_to_order, 1):
            if p['product_id'] == product_id:
                p['boxes_to_order'] += 1
                p['needed_weight'] = p['boxes_to_order'] * p['box_weight']
                p['order_cost'] = p['boxes_to_order'] * p['price_per_box']
                product = p
                index = i
                break

        # Обновляем state
        await state.update_data(products_to_order=products_to_order)

        # Обновляем меню редактирования товара
        if product:
            text, keyboard = format_edit_item_menu(product, index)
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("edit_del_"))
async def callback_edit_delete(callback: CallbackQuery, db: Database, state: FSMContext):
    """Удалить товар из заказа"""
    try:
        product_id = int(callback.data.split("_")[2])
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])

        # Удаляем товар
        products_to_order = [p for p in products_to_order if p['product_id'] != product_id]

        # Обновляем state
        await state.update_data(products_to_order=products_to_order)

        # Возвращаемся к списку заказа
        if products_to_order:
            order_text, keyboard = format_editable_order_list(products_to_order)
            await callback.message.edit_text(order_text, reply_markup=keyboard, parse_mode="HTML")
            await callback.answer("✅ Товар удален")
        else:
            await callback.message.edit_text(
                "✅ Все товары удалены из заказа.\n\n"
                "Заказ не будет сохранен.",
                parse_mode="HTML"
            )
            await state.clear()
            await callback.answer()

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "save_edited_order")
async def callback_save_order(callback: CallbackQuery, db: Database, state: FSMContext):
    """Сохранить заказ в базу данных"""
    try:
        # Получаем данные заказа из state
        data = await state.get_data()
        products_to_order = data.get('products_to_order', [])
        order_days = data.get('order_days', 14)

        if not products_to_order:
            await callback.answer("⚠️ Нет данных для сохранения", show_alert=True)
            return

        # Создаем заказ
        total_cost = sum(p['order_cost'] for p in products_to_order)
        notes = f"Заказ на {order_days} дней, {len(products_to_order)} позиций"

        order_id = await db.create_pending_order(total_cost, notes)

        # Добавляем товары в заказ
        for product in products_to_order:
            await db.add_item_to_order(
                order_id=order_id,
                product_id=product['product_id'],
                boxes=product['boxes_to_order'],
                weight=product['needed_weight'],
                cost=product['order_cost']
            )

        # Очищаем state
        await state.clear()

        # Отправляем подтверждение
        await callback.message.edit_text(
            f"✅ <b>Заказ #{order_id} сохранен!</b>\n\n"
            f"📦 Позиций: {len(products_to_order)}\n"
            f"💰 Сумма: {total_cost:,.0f}₸\n"
            f"📅 На {order_days} дней\n\n"
            f"Используйте /pending_orders для просмотра активных заказов.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Заказ сохранен!")

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data == "view_pending_orders")
@router.message(Command("pending_orders"))
@router.message(F.text == "📦 Заказы в пути")
async def cmd_view_pending_orders(update, db: Database):
    """Просмотр активных заказов"""
    # Определяем тип update (callback или message)
    if isinstance(update, CallbackQuery):
        message = update.message
        callback = update
    else:
        message = update
        callback = None

    try:
        orders = await db.get_pending_orders()

        if not orders:
            text = "📦 <b>Активных заказов нет</b>\n\nВсе товары поступили на склад."
            if callback:
                await callback.message.edit_text(text, parse_mode="HTML")
                await callback.answer()
            else:
                await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())
            return

        # Формируем список заказов
        lines = ["📦 <b>ЗАКАЗЫ В ПУТИ</b>\n"]

        for order in orders:
            created = order['created_at'].strftime('%d.%m.%Y')
            lines.append(
                f"🔸 Заказ #{order['id']} от {created}\n"
                f"   Позиций: {order['items_count']}\n"
                f"   Вес: {order['total_weight']:,.1f} кг\n"
                f"   Сумма: {order['total_cost']:,.0f}₸\n"
            )

        lines.append(f"\n💡 Используйте /order_details [id] для деталей")

        text = "\n".join(lines)

        if callback:
            await callback.message.edit_text(text, parse_mode="HTML")
            await callback.answer()
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())

    except Exception as e:
        error_text = f"❌ Ошибка: {str(e)}"
        if callback:
            await callback.answer(error_text, show_alert=True)
        else:
            await message.answer(error_text)


@router.message(Command("order_details"))
async def cmd_order_details(message: Message, db: Database):
    """Детали конкретного заказа"""
    try:
        # Извлекаем order_id из команды
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Укажите ID заказа: /order_details 123")
            return

        order_id = int(parts[1])
        items = await db.get_pending_order_items(order_id)

        if not items:
            await message.answer(f"❌ Заказ #{order_id} не найден или уже закрыт")
            return

        # Формируем детальный список
        lines = [f"📦 <b>ЗАКАЗ #{order_id} (детали)</b>\n"]

        total_cost = 0
        for item in items:
            unit = item.get('unit', 'кг')
            lines.append(
                f"▫️ {item['name_russian']}\n"
                f"   {item['boxes_ordered']} коробок × {item['box_weight']} {unit} = "
                f"{item['weight_ordered']:.1f} {unit}\n"
                f"   💰 {item['cost']:,.0f}₸\n"
            )
            total_cost += item['cost']

        lines.append(f"\n💰 <b>Итого: {total_cost:,.0f}₸</b>")

        # Добавляем кнопки действий
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Закрыть заказ", callback_data=f"complete_order_{order_id}")],
            [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"cancel_order_{order_id}")]
        ])

        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except ValueError:
        await message.answer("❌ Неверный формат ID заказа")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")


@router.callback_query(F.data.startswith("complete_order_"))
async def callback_complete_order(callback: CallbackQuery, db: Database):
    """Закрыть заказ (пометить как выполненный)"""
    try:
        order_id = int(callback.data.split("_")[2])
        await db.complete_order(order_id)

        await callback.message.edit_text(
            f"✅ Заказ #{order_id} закрыт и удален из списка товаров в пути.",
            parse_mode="HTML"
        )
        await callback.answer("✅ Заказ закрыт!")

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.callback_query(F.data.startswith("cancel_order_"))
async def callback_cancel_order(callback: CallbackQuery, db: Database):
    """Отменить заказ"""
    try:
        order_id = int(callback.data.split("_")[2])
        await db.cancel_order(order_id)

        await callback.message.edit_text(
            f"❌ Заказ #{order_id} отменен.",
            parse_mode="HTML"
        )
        await callback.answer("Заказ отменен")

    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


@router.message(Command("test_auto_order"))
async def cmd_test_auto_order(message: Message, db: Database):
    """
    Тестовая команда: проверить автоматический заказ с порогом 500,000₸
    """
    await message.answer("🧪 Тестирую автоматический заказ...")

    try:
        from utils.calculations import get_auto_order_with_threshold, format_auto_order_list

        # Подготавливаем данные
        stock_data = await prepare_order_data(db)

        # Получаем заказ с порогом
        products_to_order, total_cost, should_notify = get_auto_order_with_threshold(
            stock_data,
            order_days=14,
            threshold_amount=500000
        )

        # Формируем ответ
        if not should_notify:
            response = (
                f"💰 Сумма заказа: <b>{total_cost:,.0f}₸</b>\n\n"
                f"⚠️ Порог не достигнут (минимум: 500,000₸)\n"
                f"Уведомление не будет отправлено автоматически.\n\n"
                f"Товаров для закупа: {len(products_to_order)}"
            )
            await message.answer(response, parse_mode="HTML")
            return

        # Отправляем список заказа
        order_text = format_auto_order_list(products_to_order, total_cost)
        await message.answer(
            f"✅ Порог достигнут! Уведомление будет отправлено.\n\n{order_text}",
            parse_mode="HTML"
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}", parse_mode="HTML")
