"""
Обработчики для работы с остатками на складе
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from database import Database
from keyboards import get_main_menu
from utils.calculations import days_until_stockout, calculate_average_consumption

router = Router()


class StockInput(StatesGroup):
    entering_stock = State()
    entering_bulk_stock = State()
    confirming_bulk_stock = State()


async def format_stock_report(db: Database, stock_data: dict) -> str:
    """Форматировать мини-отчет по складу с цветовой индикацией"""
    lines = ["📊 <b>ОТЧЕТ ПО СКЛАДУ</b>\n"]

    red_items = []      # нет в наличии
    orange_items = []   # до 3 дней
    yellow_items = []   # 4-7 дней
    green_items = []    # больше 7 дней

    for product_id, data in stock_data.items():
        # Получаем историю для расчета среднего расхода
        history = await db.get_stock_history(product_id, days=7)
        avg_consumption = calculate_average_consumption(history)

        # Получаем информацию о продукте
        products = await db.get_all_products()
        product = next((p for p in products if p['id'] == product_id), None)
        if not product:
            continue

        current_stock = data['weight']
        days_left = days_until_stockout(current_stock, avg_consumption)

        item_text = f"• {product['name_russian']}: <b>{data['quantity']:.0f} уп.</b> ({current_stock:.1f} кг)"

        if current_stock <= 0:
            red_items.append(f"🔴 {item_text} - <b>НЕТ В НАЛИЧИИ</b>")
        elif days_left <= 3:
            orange_items.append(f"🟠 {item_text} - <b>на {days_left} дн.</b>")
        elif days_left <= 7:
            yellow_items.append(f"🟡 {item_text} - <b>на {days_left} дн.</b>")
        else:
            green_items.append(f"🟢 {item_text} - на {days_left} дн.")

    if red_items:
        lines.append("<b>❗️ СРОЧНО - НЕТ В НАЛИЧИИ:</b>")
        lines.extend(red_items)
        lines.append("")

    if orange_items:
        lines.append("<b>⚠️ КРИТИЧЕСКИЙ ЗАПАС (до 3 дней):</b>")
        lines.extend(orange_items)
        lines.append("")

    if yellow_items:
        lines.append("<b>📌 НИЗКИЙ ЗАПАС (4-7 дней):</b>")
        lines.extend(yellow_items)
        lines.append("")

    # Зеленые товары не показываем - лишний шум
    # if green_items and len(green_items) <= 10:
    #     lines.append("<b>✅ НОРМАЛЬНЫЙ ЗАПАС:</b>")
    #     lines.extend(green_items)

    if not red_items and not orange_items and not yellow_items:
        lines.append("<b>✅ Все товары в нормальном запасе!</b>")

    return "\n".join(lines)


async def start_stock_input(message: Message, state: FSMContext, db: Database):
    """Начать ввод остатков - выбор способа"""
    products = await db.get_all_products()

    if not products:
        await message.answer("❌ В базе нет товаров! Сначала импортируйте данные.")
        return

    # Создаем inline клавиатуру для выбора способа ввода
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Все товары списком", callback_data="stock_bulk")],
        [InlineKeyboardButton(text="🔄 По одному товару", callback_data="stock_sequential")]
    ])

    await message.answer(
        f"📝 <b>Ввод остатков на {datetime.now().strftime('%d.%m.%Y')}</b>\n\n"
        f"Товаров в базе: {len(products)}\n\n"
        f"Выберите способ ввода:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def start_bulk_stock_input(message: Message, state: FSMContext, db: Database):
    """Начать массовый ввод остатков"""
    products = await db.get_all_products()

    if not products:
        await message.answer("❌ В базе нет товаров! Сначала импортируйте данные.")
        return

    await state.set_state(StockInput.entering_bulk_stock)
    await state.update_data(products=products, stock_data={})

    # Формируем список товаров
    lines = [f"📝 <b>Массовый ввод остатков на {datetime.now().strftime('%d.%m.%Y')}</b>\n"]
    lines.append("Введите количество упаковок для каждого товара через пробел или запятую.\n")

    for i, product in enumerate(products, 1):
        lines.append(
            f"{i}. <b>{product['name_internal']}</b> "
            f"({product['name_russian']}) - "
            f"{product['package_weight']} {product['unit']}/уп."
        )

    lines.append(f"\n<b>Пример:</b> 4 218 0 5 10 ... (всего {len(products)} чисел)")
    lines.append("Если товара нет - пишите 0")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def start_sequential_stock_input(message: Message, state: FSMContext, db: Database):
    """Начать последовательный ввод остатков (старый способ)"""
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

        # Формируем мини-отчет
        report = await format_stock_report(db, stock_data)

        await state.clear()
        await message.answer(
            f"✅ <b>Остатки сохранены!</b>\n\n"
            f"Товаров: {saved}\n"
            f"Общий вес: {total_weight:.1f} кг\n"
            f"Дата: {today}",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )

        # Отправляем мини-отчет отдельным сообщением
        await message.answer(report, reply_markup=get_main_menu(), parse_mode="HTML")


@router.message(StockInput.entering_bulk_stock)
async def process_bulk_stock_input(message: Message, state: FSMContext, db: Database):
    """Обработка массового ввода остатков"""
    data = await state.get_data()
    products = data['products']

    # Парсим ввод - разделители: пробелы, запятые, точки с запятой
    import re
    quantities_str = re.split(r'[,;\s]+', message.text.strip())

    # Фильтруем пустые строки
    quantities_str = [q for q in quantities_str if q]

    if len(quantities_str) != len(products):
        await message.answer(
            f"❌ <b>Ошибка!</b>\n\n"
            f"Вы ввели {len(quantities_str)} чисел, а товаров {len(products)}.\n"
            f"Введите ровно {len(products)} чисел через пробел или запятую.\n\n"
            f"<b>Попробуйте еще раз:</b>",
            parse_mode="HTML"
        )
        return

    # Парсим числа
    try:
        quantities = [float(q.replace(',', '.')) for q in quantities_str]
    except ValueError:
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "Все значения должны быть числами (например: 10 или 0).\n\n"
            "<b>Попробуйте еще раз:</b>",
            parse_mode="HTML"
        )
        return

    # Проверяем, что все числа неотрицательные
    if any(q < 0 for q in quantities):
        await message.answer(
            "❌ <b>Ошибка!</b>\n\n"
            "Количество не может быть отрицательным.\n\n"
            "<b>Попробуйте еще раз:</b>",
            parse_mode="HTML"
        )
        return

    # Формируем данные для сохранения
    stock_data = {}
    for i, product in enumerate(products):
        quantity = quantities[i]
        weight = quantity * product['package_weight']
        stock_data[product['id']] = {
            'weight': weight,
            'quantity': quantity,
            'name': product['name_russian'],
            'name_internal': product['name_internal']
        }

    # Показываем подтверждение с предпросмотром
    confirmation_lines = ["📋 <b>Проверьте данные перед сохранением:</b>\n"]
    total_weight = 0

    for i, (product_id, data) in enumerate(stock_data.items(), 1):
        if data['quantity'] > 0:  # Показываем только ненулевые
            confirmation_lines.append(
                f"{i}. {data['name_russian']}: "
                f"<b>{data['quantity']:.0f} уп.</b> ({data['weight']:.1f} кг)"
            )
            total_weight += data['weight']

    confirmation_lines.append(f"\n<b>Общий вес: {total_weight:.1f} кг</b>")
    confirmation_lines.append("\n✅ Все верно? Напишите <b>ДА</b> для сохранения")
    confirmation_lines.append("❌ Или <b>НЕТ</b> для отмены")

    # Сохраняем данные в state для последующего сохранения
    await state.update_data(stock_data=stock_data)
    await state.set_state(StockInput.confirming_bulk_stock)

    await message.answer("\n".join(confirmation_lines), parse_mode="HTML")


@router.message(StockInput.confirming_bulk_stock)
async def confirm_bulk_stock_input(message: Message, state: FSMContext, db: Database):
    """Подтверждение сохранения массового ввода"""
    user_answer = message.text.strip().upper()

    if user_answer in ["ДА", "YES", "Y", "Д", "+"]:
        # Получаем данные из state
        data = await state.get_data()
        stock_data = data.get('stock_data', {})

        # Сохраняем в БД
        today = datetime.now().strftime('%Y-%m-%d')
        saved = 0
        total_weight = 0

        for product_id, data_item in stock_data.items():
            try:
                await db.add_stock(
                    product_id=product_id,
                    date=today,
                    quantity=data_item['quantity'],
                    weight=data_item['weight']
                )
                saved += 1
                total_weight += data_item['weight']
            except Exception as e:
                print(f"Ошибка сохранения: {e}")

        # Формируем мини-отчет
        report = await format_stock_report(db, stock_data)

        await state.clear()
        await message.answer(
            f"✅ <b>Остатки сохранены!</b>\n\n"
            f"Товаров: {saved}\n"
            f"Общий вес: {total_weight:.1f} кг\n"
            f"Дата: {today}",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )

        # Отправляем мини-отчет отдельным сообщением
        await message.answer(report, reply_markup=get_main_menu(), parse_mode="HTML")

    elif user_answer in ["НЕТ", "NO", "N", "Н", "-"]:
        await state.clear()
        await message.answer(
            "❌ Ввод остатков отменен.\n\n"
            "Нажмите 📝 Ввод остатков чтобы начать заново.",
            reply_markup=get_main_menu()
        )
    else:
        await message.answer(
            "❓ Не понял ответ.\n\n"
            "Напишите <b>ДА</b> для сохранения или <b>НЕТ</b> для отмены.",
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


# Callback обработчики для inline кнопок
@router.callback_query(F.data == "stock_bulk")
async def callback_stock_bulk(callback: CallbackQuery, state: FSMContext, db: Database):
    """Обработчик кнопки массового ввода"""
    await callback.answer()
    await start_bulk_stock_input(callback.message, state, db)


@router.callback_query(F.data == "stock_sequential")
async def callback_stock_sequential(callback: CallbackQuery, state: FSMContext, db: Database):
    """Обработчик кнопки последовательного ввода"""
    await callback.answer()
    await start_sequential_stock_input(callback.message, state, db)


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
