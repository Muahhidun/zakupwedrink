"""
Утилиты для расчетов: прогнозы, средний расход, формирование заказов
"""
from typing import List, Dict, Tuple
from datetime import datetime, timedelta


def calculate_average_consumption(history: List[Dict]) -> float:
    """
    Рассчитать средний расход за период
    history: список остатков, отсортированных по дате (от новых к старым)
    """
    if len(history) < 2:
        return 0.0

    total_consumed = 0.0
    days = 0

    for i in range(len(history) - 1):
        current = history[i]['weight']
        previous = history[i + 1]['weight']
        consumed = previous - current  # предыдущий был больше
        if consumed > 0:  # учитываем только расход, не поставки
            total_consumed += consumed
            days += 1

    return total_consumed / days if days > 0 else 0.0


def days_until_stockout(current_stock: float, avg_daily_consumption: float) -> int:
    """
    Рассчитать через сколько дней закончится товар
    """
    if avg_daily_consumption <= 0:
        return 999  # не расходуется

    days = current_stock / avg_daily_consumption
    return int(days)


def calculate_order_quantity(avg_daily_consumption: float, days: int,
                            current_stock: float, box_weight: float) -> Tuple[float, int]:
    """
    Рассчитать количество для заказа
    Возвращает: (вес в кг, количество коробок)
    """
    required_weight = avg_daily_consumption * days
    needed_weight = max(0, required_weight - current_stock)

    boxes = int(needed_weight / box_weight)
    if needed_weight % box_weight > 0:
        boxes += 1  # округляем вверх

    return needed_weight, boxes


def get_products_to_order(stock_data: List[Dict], days_threshold: int = 7,
                          order_days: int = 14) -> List[Dict]:
    """
    Получить список товаров для заказа
    stock_data: текущие остатки с историей расхода
    days_threshold: заказывать если осталось меньше N дней
    order_days: заказывать на N дней вперед
    """
    products_to_order = []

    for item in stock_data:
        avg_consumption = item.get('avg_daily_consumption', 0)
        current_stock = item.get('weight', 0)
        days_left = days_until_stockout(current_stock, avg_consumption)

        if days_left <= days_threshold:
            needed_weight, boxes = calculate_order_quantity(
                avg_consumption, order_days, current_stock, item['box_weight']
            )

            products_to_order.append({
                'product_id': item['product_id'],
                'name': item['name_internal'],
                'name_russian': item['name_russian'],
                'current_stock': current_stock,
                'avg_daily_consumption': avg_consumption,
                'days_left': days_left,
                'needed_weight': needed_weight,
                'boxes_to_order': boxes,
                'order_cost': boxes * item['price_per_box'],
                'urgency': 'СРОЧНО' if days_left <= 3 else 'Скоро'
            })

    # Сортируем по срочности (сколько дней осталось)
    products_to_order.sort(key=lambda x: x['days_left'])

    return products_to_order


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
        lines.append(
            f"{urgency_icon} <b>{p['name_russian']}</b>\n"
            f"   Осталось: {p['current_stock']:.1f} кг (на {p['days_left']} дн.)\n"
            f"   Расход: {p['avg_daily_consumption']:.1f} кг/день\n"
            f"   📦 Заказать: <b>{p['boxes_to_order']} коробок</b> "
            f"({p['needed_weight']:.1f} кг) = {p['order_cost']:,.0f}₸\n"
        )

    lines.append(f"\n💰 <b>Общая сумма заказа: {total_cost:,.0f}₸</b>")

    return "\n".join(lines)


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
