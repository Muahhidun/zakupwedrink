"""
Обработчики для просмотра истории остатков и поставок
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
from database import Database
from keyboards import get_main_menu

router = Router()


@router.message(Command("history"))
@router.message(F.text == "📜 История склада")
async def cmd_history(message: Message, db: Database):
    """Показать последние 7 дней с данными"""
    # Получаем последние 7 дат где есть остатки
    async with db.pool.acquire() as conn:
        dates = await conn.fetch("""
            SELECT DISTINCT date
            FROM stock
            ORDER BY date DESC
            LIMIT 7
        """)

    if not dates:
        await message.answer("❌ Нет данных об остатках", reply_markup=get_main_menu())
        return

    # Создаём кнопки для выбора даты
    keyboard = []
    for row in dates:
        date_obj = row['date']
        date_str = date_obj.strftime('%d.%m.%Y')
        keyboard.append([
            InlineKeyboardButton(
                text=f"📅 {date_str}",
                callback_data=f"history:{date_obj.isoformat()}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="history:back")
    ])

    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await message.answer(
        "📜 <b>История склада</b>\n\n"
        "Выберите дату для просмотра остатков и поставок:",
        reply_markup=markup,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("history:"))
async def history_callback(callback: CallbackQuery, db: Database):
    """Обработка выбора даты"""
    data = callback.data.split(":", 1)[1]

    if data == "back":
        await callback.message.delete()
        await callback.answer()
        return

    # Получаем дату
    date_obj = datetime.fromisoformat(data).date()
    date_str = date_obj.strftime('%d.%m.%Y')

    # Получаем остатки на эту дату
    stocks = await db.get_stock_on_date(date_obj)

    # Получаем поставки на эту дату
    async with db.pool.acquire() as conn:
        supplies = await conn.fetch("""
            SELECT s.*, p.name_russian, p.name_chinese, p.package_weight,
                   p.units_per_box, p.unit
            FROM supplies s
            JOIN products p ON s.product_id = p.id
            WHERE s.date = $1
            ORDER BY p.name_russian
        """, date_obj)

    # Формируем сообщение
    lines = [f"📅 <b>История за {date_str}</b>\n"]

    # Остатки
    lines.append("<b>📦 ОСТАТКИ:</b>")
    if stocks:
        for item in stocks:
            unit = item.get('unit', 'кг')
            if unit == 'шт':
                lines.append(
                    f"• {item['name_internal']}: "
                    f"<b>{item['quantity']:.0f} уп.</b>"
                )
            else:
                lines.append(
                    f"• {item['name_internal']}: "
                    f"<b>{item['quantity']:.0f} уп.</b> ({item['weight']:.1f} кг)"
                )
    else:
        lines.append("❌ Нет данных об остатках")

    # Поставки
    lines.append("\n<b>🚚 ПОСТАВКИ:</b>")
    if supplies:
        for s in supplies:
            boxes = s['boxes']
            packages = boxes * s['units_per_box']
            weight = s['weight']
            unit = s.get('unit', 'кг')

            lines.append(
                f"• {s['name_russian']}:\n"
                f"  <b>{boxes:.0f} кор.</b> = "
                f"{packages:.0f} уп. = "
                f"{weight:.1f} {unit} "
                f"({s['cost']:,.0f}₸)"
            )
    else:
        lines.append("❌ Поставок не было")

    text = "\n".join(lines)

    # Отправляем как новое сообщение
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
