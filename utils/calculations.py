"""
Утилиты для расчетов: прогнозы, средний расход, формирование заказов
"""
from typing import List, Dict, Tuple
from datetime import datetime, timedelta


def calculate_average_consumption(history: List[Dict], supplies: List[Dict] = None) -> Tuple[float, int, str]:
    """
    Рассчитать средний расход за период с учетом поставок и фильтрацией аномалий

    Args:
        history: список остатков, отсортированных по дате (от новых к старым)
        supplies: список поставок за тот же период (опционально)

    Returns:
        (средний расход в день, количество дней с данными, предупреждение)
    """
    if len(history) < 2:
        return 0.0, 0, "Недостаточно данных (менее 2 дней)"

    if supplies is None:
        supplies = []

    # Сортируем по дате (от старых к новым) для правильного расчета
    history_sorted = sorted(history, key=lambda x: x['date'])

    # ПЕРВЫЙ ПРОХОД: собираем все расходы для определения аномалий
    daily_consumptions = []  # Список кортежей (daily_consumption, consumption, days_diff, index)

    for i in range(len(history_sorted) - 1):
        current = history_sorted[i]
        next_record = history_sorted[i + 1]

        current_stock = current['weight']
        next_stock = next_record['weight']
        current_date = current['date']
        next_date = next_record['date']

        # Пропускаем если текущий или следующий остаток = 0
        if current_stock == 0 or next_stock == 0:
            continue

        # Находим поставки между этими датами
        supply_weight = 0.0
        for supply in supplies:
            supply_date = supply['date']
            if current_date <= supply_date <= next_date:
                if supply_date == current_date:
                    if current_stock >= supply['weight'] * 0.9:
                        continue
                supply_weight += supply['weight']

        # Расход = текущий остаток + поставки - следующий остаток
        consumption = current_stock + supply_weight - next_stock

        # Пропускаем если расход отрицательный
        if consumption < 0:
            continue

        # Считаем реальное количество дней
        days_diff = (next_date - current_date).days
        if days_diff <= 0:
            continue

        # Расход в день для этого периода
        daily_consumption = consumption / days_diff
        daily_consumptions.append((daily_consumption, consumption, days_diff, i))

    if len(daily_consumptions) == 0:
        return 0.0, 0, "Нет валидных периодов для расчета"

    # Вычисляем предварительное среднее
    total_consumption_preliminary = sum(dc[1] for dc in daily_consumptions)
    total_days_preliminary = sum(dc[2] for dc in daily_consumptions)
    avg_daily_preliminary = total_consumption_preliminary / total_days_preliminary

    # ВТОРОЙ ПРОХОД: фильтруем аномалии (расход > 5x от среднего)
    ANOMALY_THRESHOLD = 5.0
    filtered_consumptions = []
    anomalies_found = 0

    for daily_consumption, consumption, days_diff, idx in daily_consumptions:
        if daily_consumption > avg_daily_preliminary * ANOMALY_THRESHOLD:
            # Это аномалия - пропускаем
            anomalies_found += 1
            continue
        filtered_consumptions.append((consumption, days_diff))

    if len(filtered_consumptions) == 0:
        # Все периоды были аномалиями - возвращаем предварительное среднее
        warning = "(все данные аномальные, расчёт может быть неточным)"
        return avg_daily_preliminary, total_days_preliminary, warning

    # Финальный расчёт без аномалий
    total_consumed = sum(fc[0] for fc in filtered_consumptions)
    total_days = sum(fc[1] for fc in filtered_consumptions)
    avg_consumption = total_consumed / total_days

    # Предупреждение
    warning = ""
    if len(filtered_consumptions) < 3:
        warning = "(мало данных, риск неправильного расчета)"
    elif anomalies_found > 0:
        warning = f"(исключено {anomalies_found} аномальных дней)"

    return avg_consumption, total_days, warning


def days_until_stockout(current_stock: float, avg_daily_consumption: float) -> int:
    """
    Рассчитать через сколько дней закончится товар
    """
    if avg_daily_consumption <= 0:
        return 999  # не расходуется

    days = current_stock / avg_daily_consumption
    return int(days)


def round_boxes_02_rule(boxes_decimal: float) -> int:
    """
    Округление коробок по правилу 0.2:
    - Если дробная часть <= 0.2 → округляем вниз
    - Если дробная часть > 0.2 → округляем вверх

    Примеры:
    - 1.2 → 1
    - 1.201 → 2
    - 1.19 → 1
    - 1.5 → 2
    """
    import math
    integer_part = int(boxes_decimal)
    fractional_part = boxes_decimal - integer_part

    if fractional_part <= 0.2:
        return integer_part
    else:
        return integer_part + 1


def calculate_order_quantity(avg_daily_consumption: float, days: int,
                            current_stock: float, box_weight: float,
                            use_02_rule: bool = False, pending_weight: float = 0) -> Tuple[float, int]:
    """
    Рассчитать количество для заказа
    Возвращает: (вес в кг, количество коробок)

    Args:
        avg_daily_consumption: средний расход в день
        days: на сколько дней заказывать
        current_stock: текущий остаток
        box_weight: вес одной коробки
        use_02_rule: использовать правило округления 0.2
        pending_weight: вес товара в активных заказах (в пути)
    """
    required_weight = avg_daily_consumption * days
    # Учитываем текущий остаток И товары в пути
    available_weight = current_stock + pending_weight
    needed_weight = max(0, required_weight - available_weight)

    if needed_weight == 0:
        return 0, 0

    # Минимальный порог: если нужно меньше 30% от веса коробки, не заказываем
    # (с учетом товаров в пути хватает запаса)
    MIN_THRESHOLD = 0.3  # 30% от коробки
    if needed_weight < box_weight * MIN_THRESHOLD:
        return 0, 0

    boxes_decimal = needed_weight / box_weight

    if use_02_rule:
        boxes = round_boxes_02_rule(boxes_decimal)
    else:
        # Стандартное округление вверх
        boxes = int(boxes_decimal)
        if needed_weight % box_weight > 0:
            boxes += 1

    # Дополнительная проверка: если получилось 0 коробок, возвращаем 0
    if boxes == 0:
        return 0, 0

    return needed_weight, boxes


def get_products_to_order(stock_data: List[Dict], days_threshold: int = 7,
                          order_days: int = 14, use_02_rule: bool = False,
                          include_pending: bool = False) -> List[Dict]:
    """
    Получить список товаров для заказа
    stock_data: текущие остатки с историей расхода
    days_threshold: заказывать если осталось меньше N дней
    order_days: заказывать на N дней вперед
    use_02_rule: использовать правило округления 0.2
    include_pending: учитывать товары в активных заказах (в пути)
    """
    products_to_order = []

    for item in stock_data:
        avg_consumption = item.get('avg_daily_consumption', 0)
        current_stock = item.get('weight', 0)
        pending_weight = item.get('pending_weight', 0) if include_pending else 0

        # Учитываем товары в пути при расчете "на сколько хватит"
        available_stock = current_stock + pending_weight
        days_left = days_until_stockout(available_stock, avg_consumption)

        if days_left <= days_threshold:
            needed_weight, boxes = calculate_order_quantity(
                avg_consumption, order_days, current_stock, item['box_weight'],
                use_02_rule=use_02_rule,
                pending_weight=pending_weight
            )

            # Пропускаем если ничего не нужно заказывать (достаточно товара в пути)
            if boxes == 0:
                continue

            products_to_order.append({
                'product_id': item['product_id'],
                'name': item['name_internal'],
                'name_russian': item['name_russian'],
                'current_stock': current_stock,
                'pending_weight': pending_weight,
                'avg_daily_consumption': avg_consumption,
                'days_left': days_left,
                'needed_weight': needed_weight,
                'boxes_to_order': boxes,
                'order_cost': boxes * item['price_per_box'],
                'box_weight': item['box_weight'],
                'price_per_box': item['price_per_box'],  # Добавляем для редактирования
                'urgency': 'СРОЧНО' if days_left <= 3 else 'Скоро',
                'unit': item.get('unit', 'кг')
            })

    # Сортируем по срочности (сколько дней осталось)
    products_to_order.sort(key=lambda x: x['days_left'])

    return products_to_order


def format_editable_order_list(products: List[Dict]) -> Tuple[str, 'InlineKeyboardMarkup']:
    """
    Форматировать список заказа с inline кнопками для редактирования
    Возвращает: (текст, клавиатура)
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not products:
        return "✅ Все товары в наличии, заказывать ничего не нужно!", None

    total_cost = sum(p['order_cost'] for p in products)

    lines = ["🛒 <b>СПИСОК ДЛЯ ЗАКУПА</b>\n"]

    for i, p in enumerate(products, 1):
        urgency_icon = "🚨" if p['urgency'] == 'СРОЧНО' else "⚠️"
        unit = p.get('unit', 'кг')
        pending_weight = p.get('pending_weight', 0)

        # Формируем строку с остатком
        stock_line = f"   Осталось: {p['current_stock']:.1f} {unit}"
        if pending_weight > 0:
            stock_line += f" + {pending_weight:.1f} {unit} в пути"
        stock_line += f" (на {p['days_left']} дн.)"

        lines.append(
            f"{i}. {urgency_icon} <b>{p['name_russian']}</b>\n"
            f"{stock_line}\n"
            f"   Расход: {p['avg_daily_consumption']:.1f} {unit}/день\n"
            f"   📦 <b>{p['boxes_to_order']} кор.</b> "
            f"({p['needed_weight']:.1f} {unit}) = {p['order_cost']:,.0f}₸\n"
        )

    lines.append(f"\n💰 <b>Общая сумма: {total_cost:,.0f}₸</b>")
    lines.append(f"\n💡 Нажмите на номер товара для редактирования:")

    # Создаем кнопки с номерами товаров (по 5 в ряд)
    buttons = []
    row = []
    for i, p in enumerate(products, 1):
        row.append(InlineKeyboardButton(text=f"{i}", callback_data=f"edit_item_{p['product_id']}"))
        if len(row) == 5 or i == len(products):
            buttons.append(row)
            row = []

    # Кнопка сохранения
    buttons.append([
        InlineKeyboardButton(text="💾 Сохранить заказ", callback_data="save_edited_order")
    ])
    buttons.append([
        InlineKeyboardButton(text="📋 Активные заказы", callback_data="view_pending_orders")
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    return "\n".join(lines), keyboard


def format_edit_item_menu(product: Dict, index: int) -> Tuple[str, 'InlineKeyboardMarkup']:
    """
    Форматировать меню редактирования конкретного товара
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    unit = product.get('unit', 'кг')

    text = (
        f"✏️ <b>Редактирование товара #{index}</b>\n\n"
        f"📦 <b>{product['name_russian']}</b>\n"
        f"Текущее количество: <b>{product['boxes_to_order']} коробок</b>\n"
        f"Вес: {product['needed_weight']:.1f} {unit}\n"
        f"Стоимость: {product['order_cost']:,.0f}₸\n\n"
        f"Что хотите сделать?"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖ Уменьшить", callback_data=f"edit_dec_{product['product_id']}"),
            InlineKeyboardButton(text="➕ Увеличить", callback_data=f"edit_inc_{product['product_id']}")
        ],
        [
            InlineKeyboardButton(text="❌ Удалить из заказа", callback_data=f"edit_del_{product['product_id']}")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_order_list")
        ]
    ])

    return text, keyboard


def format_order_list(products: List[Dict]) -> str:
    """
    Форматировать список заказа для отображения
    """
    if not products:
        return "✅ Все товары в наличии, заказывать ничего не нужно!"

    total_cost = sum(p['order_cost'] for p in products)

    lines = ["🛒 <b>СПИСОК ДЛЯ ЗАКУПА</b>\n"]

    for p in products:
        urgency_icon = "🚨" if p['urgency'] == 'СРОЧНО' else "⚠️"
        unit = p.get('unit', 'кг')
        pending_weight = p.get('pending_weight', 0)

        # Формируем строку с остатком
        stock_line = f"   Осталось: {p['current_stock']:.1f} {unit}"
        if pending_weight > 0:
            stock_line += f" + {pending_weight:.1f} {unit} в пути"
        stock_line += f" (на {p['days_left']} дн.)"

        lines.append(
            f"{urgency_icon} <b>{p['name_russian']}</b>\n"
            f"{stock_line}\n"
            f"   Расход: {p['avg_daily_consumption']:.1f} {unit}/день\n"
            f"   📦 Заказать: <b>{p['boxes_to_order']} коробок</b> "
            f"({p['needed_weight']:.1f} {unit}) = {p['order_cost']:,.0f}₸\n"
        )

    lines.append(f"\n💰 <b>Общая сумма заказа: {total_cost:,.0f}₸</b>")

    return "\n".join(lines)


def format_auto_order_list(products: List[Dict], total_cost: float) -> str:
    """
    Форматировать автоматический список заказа с общим весом
    """
    if not products:
        return "✅ Все товары в наличии, заказывать ничего не нужно!"

    # Рассчитываем общий вес
    total_weight = sum(p['boxes_to_order'] * p['box_weight'] for p in products)

    lines = ["🛒 <b>АВТОМАТИЧЕСКАЯ ЗАЯВКА НА ЗАКУП (на 14 дней)</b>\n"]

    for i, p in enumerate(products, 1):
        urgency_icon = "🚨" if p['urgency'] == 'СРОЧНО' else "⚠️"
        unit = p.get('unit', 'кг')
        pending_weight = p.get('pending_weight', 0)

        # Формируем строку с остатком
        stock_line = f"   Осталось: {p['current_stock']:.1f} {unit}"
        if pending_weight > 0:
            stock_line += f" + {pending_weight:.1f} {unit} в пути"
        stock_line += f" (на {p['days_left']} дн.)"

        lines.append(
            f"{i}. {urgency_icon} <b>{p['name_russian']}</b>\n"
            f"{stock_line}\n"
            f"   📦 Заказать: <b>{p['boxes_to_order']} коробок</b>\n"
            f"   💰 Сумма: {p['order_cost']:,.0f}₸\n"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━━━━")
    lines.append(f"💰 <b>Общая сумма: {total_cost:,.0f}₸</b>")
    lines.append(f"⚖️ <b>Общий вес: {total_weight:,.1f} кг</b>")

    return "\n".join(lines)


def get_auto_order_with_threshold(stock_data: List[Dict],
                                   order_days: int = 14,
                                   threshold_amount: float = 500000) -> Tuple[List[Dict], float, bool]:
    """
    Получить автоматический заказ с порогом суммы

    Args:
        stock_data: данные об остатках
        order_days: на сколько дней заказывать (по умолчанию 14)
        threshold_amount: минимальная сумма заказа для отправки уведомления (по умолчанию 500,000₸)

    Returns:
        (список товаров для заказа, общая сумма, отправлять ли уведомление)
    """
    # Рассчитываем товары для заказа с правилом округления 0.2
    products_to_order = get_products_to_order(
        stock_data,
        days_threshold=order_days,  # Если остатка < чем на 14 дней → включаем в закуп
        order_days=order_days,
        use_02_rule=True,
        include_pending=True  # Учитываем товары в пути!
    )

    # Считаем общую сумму
    total_cost = sum(p['order_cost'] for p in products_to_order)

    # Определяем, нужно ли отправлять уведомление
    should_notify = total_cost >= threshold_amount

    return products_to_order, total_cost, should_notify


def calculate_daily_cost(consumption_data: List[Dict]) -> Tuple[float, str]:
    """
    Рассчитать стоимость расхода за день
    Возвращает: (общая сумма, детализация)
    """
    if not consumption_data:
        return 0.0, "Нет данных о расходе"

    total_cost = sum(item.get('cost', 0) for item in consumption_data if item.get('cost', 0) > 0)

    # Топ-5 самых дорогих расходов
    top_items = sorted(
        [item for item in consumption_data if item.get('cost', 0) > 0],
        key=lambda x: x['cost'],
        reverse=True
    )[:5]

    lines = [f"💰 <b>Общий расход: {total_cost:,.0f}₸</b>\n\n<b>Топ-5 расходов:</b>"]

    for i, item in enumerate(top_items, 1):
        lines.append(
            f"{i}. {item['name_russian']}: "
            f"{item['consumed_weight']:.1f} кг = {item['cost']:,.0f}₸"
        )

    return total_cost, "\n".join(lines)


async def calculate_order(db, days: int, lookback_days: int = 30) -> Dict:
    """
    Рассчитывает необходимое количество товара для заказа на заданное число дней.
    lookback_days: за сколько дней анализировать расход для среднего значения.
    """
    try:
        from handlers.orders import prepare_order_data
        # Получаем данные об остатках и расходе за указанный период ретроспективы (с фильтрацией)
        stock_data = await prepare_order_data(db, lookback_days=lookback_days)
        
        # Получаем список для заказа на указанное кол-во дней вперед
        products_to_order = get_products_to_order(
            stock_data,
            days_threshold=days,  # Порог закупа равен количеству планируемых дней
            order_days=days,
            use_02_rule=True,
            include_pending=True
        )
        
        total_cost = sum(p['order_cost'] for p in products_to_order)
        
        # Форматируем под формат ответа API
        api_items = []
        for p in products_to_order:
            api_items.append({
                'product_id': p['product_id'],
                'name': p['name_russian'],
                'daily_consumption': p['avg_daily_consumption'],
                'current_stock': p['current_stock'],
                'needed_quantity': p['needed_weight'],
                'order_boxes': p['boxes_to_order'],
                'price_per_box': p['price_per_box'],
                'item_total': p['order_cost']
            })
            
        return {
            'days': days,
            'lookback_days': lookback_days,
            'total_cost': total_cost,
            'items': api_items
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise e
