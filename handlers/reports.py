"""
Обработчики для отчетов и аналитики
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime, timedelta
from database import Database
from keyboards import get_main_menu
from utils.calculations import calculate_daily_cost

router = Router()


@router.message(Command("report"))
@router.message(F.text == "📅 Вчера")
async def cmd_report(message: Message, db: Database, user_role: str = "admin"):
    """Отчет о расходе за вчера"""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    day_before = yesterday - timedelta(days=1)

    today_str = today.strftime('%Y-%m-%d')
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    day_before_str = day_before.strftime('%Y-%m-%d')

    # Расчет расхода за вчера (разница между позавчера и вчера)
    consumption = await db.calculate_consumption(day_before_str, yesterday_str)

    if not consumption:
        await message.answer("❌ Нет данных о расходе за вчера", reply_markup=get_main_menu(True, user_role))
        return

    total_cost, details = calculate_daily_cost(consumption)

    report_text = f"📊 <b>ОТЧЕТ ЗА {yesterday.strftime('%d.%m.%Y')}</b>\n\n{details}"

    await message.answer(report_text, reply_markup=get_main_menu(True, user_role), parse_mode="HTML")


@router.message(Command("week"))
@router.message(F.text == "📆 Неделя")
async def cmd_week_report(message: Message, db: Database, user_role: str = "admin"):
    """Отчет за неделю"""
    today = datetime.now()
    week_ago = today - timedelta(days=7)

    today_str = today.strftime('%Y-%m-%d')
    week_ago_str = week_ago.strftime('%Y-%m-%d')

    # Используем новый метод, который работает с пропущенными датами
    consumption = await db.calculate_consumption_period(week_ago_str, today_str)

    if not consumption:
        await message.answer("❌ Нет данных о расходе за неделю", reply_markup=get_main_menu(True, user_role))
        return

    total_cost = sum(item.get('cost', 0) for item in consumption if item.get('cost', 0) > 0)

    # Топ-10 расходов
    top_items = sorted(
        [item for item in consumption if item.get('cost', 0) > 0],
        key=lambda x: x['cost'],
        reverse=True
    )[:10]

    lines = [
        f"📊 <b>ОТЧЕТ ЗА НЕДЕЛЮ</b>",
        f"Период: {week_ago.strftime('%d.%m')} - {today.strftime('%d.%m.%Y')}",
        f"\n💰 <b>Общий расход: {total_cost:,.0f}₸</b>",
        f"Средний расход в день: {total_cost / 7:,.0f}₸",
        f"\n<b>Топ-10 расходов:</b>\n"
    ]

    for i, item in enumerate(top_items, 1):
        lines.append(
            f"{i}. {item['name_russian']}\n"
            f"   {item['consumed_weight']:.1f} кг = {item['cost']:,.0f}₸"
        )

    await message.answer("\n".join(lines), reply_markup=get_main_menu(True, user_role), parse_mode="HTML")


@router.message(Command("analytics"))
@router.message(F.text == "📊 Аналитика")
async def cmd_analytics(message: Message, db: Database, user_role: str = "admin"):
    """Аналитика по товарам"""
    # Расход за последние 7 дней
    today = datetime.now()
    week_ago = today - timedelta(days=7)

    # Используем новый метод, который работает с пропущенными датами
    consumption = await db.calculate_consumption_period(
        week_ago.strftime('%Y-%m-%d'),
        today.strftime('%Y-%m-%d')
    )

    if not consumption:
        await message.answer("❌ Недостаточно данных для аналитики", reply_markup=get_main_menu(True, user_role))
        return

    # Сортируем по весу расхода
    sorted_by_weight = sorted(
        [item for item in consumption if item.get('consumed_weight', 0) > 0],
        key=lambda x: x['consumed_weight'],
        reverse=True
    )

    lines = [
        "📊 <b>АНАЛИТИКА РАСХОДА ЗА НЕДЕЛЮ</b>\n",
        "<b>🔥 Топ-5 по объему расхода:</b>"
    ]

    for i, item in enumerate(sorted_by_weight[:5], 1):
        daily_avg = item['consumed_weight'] / 7
        lines.append(
            f"{i}. {item['name_russian']}\n"
            f"   Ушло: {item['consumed_weight']:.1f} кг\n"
            f"   В день: ~{daily_avg:.1f} кг"
        )

    lines.append("\n💡 <b>Рекомендации:</b>")
    lines.append("Держите в большом количестве:")

    for item in sorted_by_weight[:3]:
        lines.append(f"• {item['name_russian']}")

    await message.answer("\n".join(lines), reply_markup=get_main_menu(True, user_role), parse_mode="HTML")
