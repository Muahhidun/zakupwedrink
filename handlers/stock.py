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
from utils.calculations import days_until_stockout, calculate_average_consumption

router = Router()


class StockInput(StatesGroup):
    entering_stock = State()


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
@router.message(F.text == "📝 Ввод остатков (чат)")
async def cmd_stock(message: Message, state: FSMContext, db: Database):
    """Команда и кнопка для ввода остатков через чат"""
    await start_stock_input(message, state, db)


@router.message(F.web_app_data)
async def handle_web_app_data(message: Message, db: Database):
    """Обработчик данных из Mini App"""
    try:
        import json
        # Получаем данные из web_app
        data = json.loads(message.web_app_data.data)

        date_str = data.get('date')
        stock_items = data.get('stock', [])

        # Преобразуем строку даты в datetime.date
        from datetime import datetime
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Сохраняем каждый остаток
        saved = 0
        total_weight = 0

        for item in stock_items:
            await db.add_stock(
                product_id=item['product_id'],
                date=date_obj,
                quantity=item['quantity'],
                weight=item['weight']
            )
            saved += 1
            total_weight += item['weight']

        # Формируем stock_data для отчета
        stock_data = {}
        for item in stock_items:
            stock_data[item['product_id']] = {
                'quantity': item['quantity'],
                'weight': item['weight']
            }

        # Формируем мини-отчет
        report = await format_stock_report(db, stock_data)

        await message.answer(
            f"✅ <b>Остатки сохранены через форму!</b>\n\n"
            f"Товаров: {saved}\n"
            f"Общий вес: {total_weight:.1f} кг\n"
            f"Дата: {date_str}",
            parse_mode="HTML"
        )

        # Отправляем мини-отчет
        await message.answer(report, parse_mode="HTML")

    except Exception as e:
        print(f"Ошибка обработки данных Mini App: {e}")
        await message.answer(
            "❌ Ошибка при сохранении данных. Попробуйте еще раз.",
            parse_mode="HTML"
        )


@router.message(Command("current"))
@router.message(F.text == "📦 Текущие остатки")
async def cmd_current_handler(message: Message, db: Database):
    """Команда и кнопка для текущих остатков"""
    await cmd_current(message, db)


@router.message(Command("verify_data"))
async def cmd_verify_data(message: Message, db: Database):
    """Проверка исторических данных в базе"""
    try:
        # Получаем общую статистику
        total_products = len(await db.get_all_products())
        total_records = await db.get_total_stock_records()
        dates_summary = await db.get_stock_dates_summary()

        lines = ["📊 <b>ПРОВЕРКА ИСТОРИЧЕСКИХ ДАННЫХ</b>\n"]
        lines.append(f"📦 Всего товаров в БД: <b>{total_products}</b>")
        lines.append(f"📝 Всего записей об остатках: <b>{total_records}</b>\n")

        if dates_summary:
            lines.append("<b>📅 Данные по датам:</b>")
            for row in dates_summary:
                date_str = row['date'].strftime('%d.%m.%Y')
                count = row['product_count']
                total_weight = row['total_weight']
                lines.append(
                    f"• {date_str}: <b>{count}</b> товаров "
                    f"({total_weight:.1f} кг)"
                )
        else:
            lines.append("❌ Нет данных об остатках")

        await message.answer("\n".join(lines), parse_mode="HTML")

    except Exception as e:
        await message.answer(
            f"❌ Ошибка при проверке данных: {e}",
            parse_mode="HTML"
        )
