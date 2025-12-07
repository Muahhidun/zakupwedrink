"""
Обработчик для просмотра среднего расхода товаров
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from keyboards import get_main_menu
from utils.calculations import calculate_average_consumption

router = Router()


@router.message(F.text == "📈 Средний расход")
@router.message(Command("avg_consumption"))
async def cmd_average_consumption(message: Message):
    """Показать меню выбора периода для среднего расхода"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="7 дней", callback_data="avg_consumption:7"),
            InlineKeyboardButton(text="10 дней", callback_data="avg_consumption:10"),
        ],
        [
            InlineKeyboardButton(text="20 дней", callback_data="avg_consumption:20"),
            InlineKeyboardButton(text="30 дней", callback_data="avg_consumption:30"),
        ]
    ])

    await message.answer(
        "📊 <b>Средний расход товаров</b>\n\n"
        "Выберите период для расчёта:\n"
        "• 7 дней - недельный расход\n"
        "• 10 дней - полторы недели\n"
        "• 20 дней - три недели\n"
        "• 30 дней - месячный расход (наиболее точный)",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("avg_consumption:"))
async def process_avg_consumption(callback: CallbackQuery, db: Database):
    """Рассчитать и показать средний расход за выбранный период"""
    try:
        # Извлекаем количество дней
        days = int(callback.data.split(":")[1])

        await callback.message.edit_text(
            f"⏳ Рассчитываю средний расход за {days} дней...",
            parse_mode="HTML"
        )

        # Получаем все товары
        products = await db.get_all_products()

        # Рассчитываем средний расход для каждого товара
        consumption_data = []

        for product in products:
            # Получаем историю и поставки
            history = await db.get_stock_history(product['id'], days=days)
            supplies = await db.get_supply_history(product['id'], days=days)

            if len(history) < 2:
                # Недостаточно данных
                continue

            # Рассчитываем средний расход с фильтрацией аномалий
            avg_consumption, total_days, warning = calculate_average_consumption(history, supplies)

            if avg_consumption > 0:
                consumption_data.append({
                    'name': product['name_russian'],
                    'avg_consumption': avg_consumption,
                    'unit': product.get('unit', 'кг'),
                    'days': total_days,
                    'warning': warning
                })

        if not consumption_data:
            await callback.message.edit_text(
                f"❌ Недостаточно данных за {days} дней для расчёта среднего расхода.",
                parse_mode="HTML"
            )
            await callback.answer()
            return

        # Сортируем по убыванию расхода
        consumption_data.sort(key=lambda x: x['avg_consumption'], reverse=True)

        # Формируем сообщение
        lines = [f"📊 <b>СРЕДНИЙ РАСХОД ЗА {days} ДНЕЙ</b>\n"]

        for item in consumption_data:
            avg = item['avg_consumption']
            unit = item['unit']
            warning_text = f" {item['warning']}" if item['warning'] else ""

            lines.append(
                f"• <b>{item['name']}</b>: {avg:.1f} {unit}/день"
                f"{warning_text}"
            )

        lines.append(f"\n📅 Данные основаны на {days} днях истории")
        lines.append("💡 <i>Аномальные дни (x5 от среднего) исключены из расчёта</i>")

        text = "\n".join(lines)

        # Telegram ограничивает длину сообщения 4096 символами
        if len(text) > 4000:
            # Разбиваем на части
            await callback.message.edit_text(
                text[:4000] + "\n\n<i>... сообщение обрезано</i>",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(text, parse_mode="HTML")

        await callback.answer()

    except Exception as e:
        print(f"Ошибка расчёта среднего расхода: {e}")
        import traceback
        traceback.print_exc()

        await callback.message.edit_text(
            f"❌ Ошибка при расчёте: {e}",
            parse_mode="HTML"
        )
        await callback.answer()
