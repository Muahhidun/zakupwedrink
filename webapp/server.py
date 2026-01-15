"""
Веб-сервер для Telegram Mini App
"""
from aiohttp import web
import aiohttp_cors
import os
import sys
from datetime import datetime
from pathlib import Path

# Добавляем путь к родительской директории
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_pg import DatabasePG
from dotenv import load_dotenv
from utils.working_day import get_working_date

load_dotenv()

# Инициализация базы данных
DATABASE_URL = os.getenv('DATABASE_URL')
db = None

# Глобальный экземпляр бота для уведомлений
bot_instance = None

# Временное хранилище черновиков заказов (ключ: данные заказа)
draft_orders = {}


def set_bot_instance(bot):
    """Установить глобальный экземпляр бота (не используется в production)"""
    global bot_instance
    bot_instance = bot


def get_bot_instance():
    """Получить или создать экземпляр бота для уведомлений"""
    global bot_instance
    if bot_instance is None:
        # Создаем bot для отправки уведомлений
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        BOT_TOKEN = os.getenv('BOT_TOKEN')
        if not BOT_TOKEN:
            print("⚠️ BOT_TOKEN not set, cannot send notifications")
            return None

        bot_instance = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        print("✅ Bot instance created for webapp notifications")

    return bot_instance


async def init_db(app):
    """Инициализация БД при старте приложения"""
    global db
    db = DatabasePG(DATABASE_URL)
    await db.init_db()
    print("✅ База данных инициализирована")


async def close_db(app):
    """Закрытие БД при остановке"""
    global db
    if db:
        await db.close()


async def index(request):
    """Главная страница Mini App"""
    html_path = Path(__file__).parent / 'templates' / 'stock_input.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    return web.Response(text=html_content, content_type='text/html')


async def order_edit(request):
    """Страница редактирования заказа"""
    html_path = Path(__file__).parent / 'templates' / 'order_edit.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    return web.Response(text=html_content, content_type='text/html')


async def get_products(request):
    """API: Получить список всех товаров"""
    try:
        products = await db.get_all_products()

        # Конвертируем datetime в строки для JSON
        for product in products:
            if 'created_at' in product and product['created_at']:
                product['created_at'] = product['created_at'].isoformat()

        return web.json_response(products)
    except Exception as e:
        print(f"Ошибка получения товаров: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def save_stock(request):
    """API: Сохранить остатки (с модерацией для сотрудников)"""
    try:
        data = await request.json()
        stock_items = data.get('stock', [])
        user_id = data.get('user_id')

        if not user_id or user_id == 'unknown':
            return web.json_response({'error': 'User ID required'}, status=400)

        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        # Проверяем роль пользователя
        user_role = await db.get_user_role(user_id)

        if user_role == 'admin':
            # Админ - сохраняем напрямую
            for item in stock_items:
                await db.add_stock(
                    product_id=item['product_id'],
                    date=date_obj,
                    quantity=item['quantity'],
                    weight=item['weight']
                )

            print(f"✅ Админ {user_id} сохранил {len(stock_items)} позиций")

            return web.json_response({
                'success': True,
                'message': f'Сохранено {len(stock_items)} позиций',
                'working_date': working_date_str,
                'requires_moderation': False
            })
        else:
            # Сотрудник - создаем submission
            try:
                submission_id = await db.create_stock_submission(
                    user_id=user_id,
                    date=date_obj,
                    items=stock_items
                )
            except ValueError as e:
                # Уже есть pending заявка
                return web.json_response({'error': str(e)}, status=400)

            print(f"📝 Сотрудник {user_id} создал submission #{submission_id}")

            # Уведомляем админов
            await notify_admins_about_submission(submission_id, user_id,
                                                working_date_str, stock_items)

            return web.json_response({
                'success': True,
                'message': 'Остатки отправлены на модерацию',
                'working_date': working_date_str,
                'submission_id': submission_id,
                'requires_moderation': True
            })

    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_latest_stock(request):
    """API: Получить последние остатки"""
    try:
        stock = await db.get_latest_stock()

        # Конвертируем datetime и date в строки для JSON
        for item in stock:
            if 'created_at' in item and item['created_at']:
                item['created_at'] = item['created_at'].isoformat()
            if 'date' in item and item['date']:
                item['date'] = item['date'].isoformat()

        return web.json_response(stock)
    except Exception as e:
        print(f"Ошибка получения остатков: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def check_stock_exists(request):
    """API: Проверить наличие остатков за текущий рабочий день"""
    try:
        # Определяем текущий рабочий день
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        # Проверяем наличие данных
        exists = await db.has_stock_for_date(date_obj)

        return web.json_response({
            'exists': exists,
            'working_date': working_date_str
        })
    except Exception as e:
        print(f"Ошибка проверки остатков: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_stock_for_date(request):
    """API: Получить остатки за конкретную дату"""
    try:
        date_str = request.match_info.get('date')
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        print(f"📅 API запрос остатков за дату: {date_str}")
        stock = await db.get_stock_by_date(date_obj)
        print(f"📦 Найдено {len(stock)} записей")

        if len(stock) > 0:
            # Показываем первые 3 записи для отладки
            for i, item in enumerate(stock[:3]):
                print(f"  [{i+1}] ID={item.get('product_id')}, qty={item.get('quantity')}, name={item.get('name_internal', 'N/A')}")

        # Конвертируем datetime и date в строки для JSON
        for item in stock:
            if 'created_at' in item and item['created_at']:
                item['created_at'] = item['created_at'].isoformat()
            if 'date' in item and item['date']:
                item['date'] = item['date'].isoformat()

        return web.json_response(stock)
    except Exception as e:
        print(f"❌ Ошибка получения остатков: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({'error': str(e)}, status=500)


async def get_yesterday_stock(request):
    """API: Получить остатки за вчерашний рабочий день"""
    try:
        from datetime import timedelta

        # Определяем текущий рабочий день
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        # Вчерашний день (может быть не рабочим)
        yesterday = date_obj - timedelta(days=1)

        # Ищем последний день с данными до сегодня
        async with db.pool.acquire() as conn:
            # Находим максимальную дату, которая меньше сегодняшней
            latest_previous_date = await conn.fetchval("""
                SELECT MAX(date)
                FROM stock
                WHERE date < $1
            """, date_obj)

            if not latest_previous_date:
                # Нет предыдущих данных
                return web.json_response({
                    'stock': [],
                    'date': None,
                    'working_date': working_date_str
                })

            # Получаем остатки за эту дату
            stock = await db.get_stock_by_date(latest_previous_date)

            # Конвертируем datetime и date в строки для JSON
            for item in stock:
                if 'created_at' in item and item['created_at']:
                    item['created_at'] = item['created_at'].isoformat()
                if 'date' in item and item['date']:
                    item['date'] = item['date'].isoformat()

            return web.json_response({
                'stock': stock,
                'date': latest_previous_date.isoformat(),
                'working_date': working_date_str
            })

    except Exception as e:
        print(f"Ошибка получения вчерашних остатков: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_today_supplies(request):
    """API: Получить поставки между последней датой остатков и сегодня"""
    try:
        # Определяем текущий рабочий день
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        # Получаем поставки между последней датой остатков и текущей датой
        async with db.pool.acquire() as conn:
            # Находим последнюю дату с остатками (вчерашнюю)
            latest_previous_date = await conn.fetchval("""
                SELECT MAX(date)
                FROM stock
                WHERE date < $1
            """, date_obj)

            if not latest_previous_date:
                # Нет предыдущих данных, берем поставки только на сегодня
                start_date = date_obj
            else:
                # Берем поставки начиная с даты последних остатков
                # (поставки могли прийти в тот же день после подсчета остатков)
                start_date = latest_previous_date

            print(f"📦 Загрузка поставок с {start_date} по {date_obj}")

            # Получаем поставки за период
            supplies = await conn.fetch("""
                SELECT s.product_id, s.boxes, s.date,
                       p.units_per_box, p.package_weight
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE s.date >= $1 AND s.date <= $2
            """, start_date, date_obj)

            print(f"📦 Найдено {len(supplies)} записей поставок")

            # Группируем поставки по product_id (суммируем все за период)
            supplies_dict = {}
            for supply in supplies:
                product_id = supply['product_id']
                packages = supply['boxes'] * supply['units_per_box']

                if product_id in supplies_dict:
                    supplies_dict[product_id] += packages
                else:
                    supplies_dict[product_id] = packages

            print(f"📦 Сгруппированные поставки: {supplies_dict}")

            return web.json_response({
                'supplies': supplies_dict,
                'working_date': working_date_str,
                'period': {
                    'from': start_date.isoformat(),
                    'to': date_obj.isoformat()
                }
            })

    except Exception as e:
        print(f"Ошибка получения поставок: {e}")
        import traceback
        traceback.print_exc()
        return web.json_response({'error': str(e)}, status=500)


async def notify_admins_about_submission(submission_id, user_id, date_str, items):
    """Отправить уведомление админам о новой заявке"""
    bot = get_bot_instance()
    if not bot:
        print("⚠️ Cannot create bot instance, notifications disabled")
        return

    try:
        admin_ids = await db.get_admin_ids()
        user_info = await db.get_user_info(user_id)
        # Приоритет: display_name > username > first_name
        username = user_info.get('display_name') or user_info.get('username') or user_info.get('first_name') or 'Неизвестно'

        message = f"""
🔔 <b>НОВАЯ ЗАЯВКА НА ОСТАТКИ</b>

👤 Сотрудник: {username}
📅 Дата: {date_str}
📦 Товаров: {len(items)}

Заявка №{submission_id}
"""

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁️ Просмотреть", callback_data=f"review_{submission_id}")],
            [
                InlineKeyboardButton(text="✅ Утвердить", callback_data=f"approve_{submission_id}"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{submission_id}")
            ],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{submission_id}")]
        ])

        for admin_id in admin_ids:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                print(f"✅ Уведомление отправлено админу {admin_id}")
            except Exception as e:
                print(f"❌ Ошибка отправки уведомления админу {admin_id}: {e}")
    except Exception as e:
        print(f"❌ Ошибка в notify_admins_about_submission: {e}")
        import traceback
        traceback.print_exc()


async def save_draft_order(request):
    """API: Сохранить черновик заказа"""
    try:
        data = await request.json()
        draft_key = data.get('draft_key')
        order_data = data.get('order_data')

        if not draft_key or not order_data:
            return web.json_response({'error': 'Missing draft_key or order_data'}, status=400)

        draft_orders[draft_key] = order_data
        print(f"✅ Черновик заказа сохранен: {draft_key}")
        return web.json_response({'success': True, 'draft_key': draft_key})
    except Exception as e:
        print(f"❌ Ошибка сохранения черновика заказа: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_draft_order(request):
    """API: Получить данные черновика заказа"""
    try:
        draft_key = request.match_info.get('draft_key')

        if draft_key not in draft_orders:
            return web.json_response({'error': 'Draft not found'}, status=404)

        order_data = draft_orders[draft_key]
        return web.json_response(order_data)
    except Exception as e:
        print(f"❌ Ошибка получения черновика заказа: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def get_submission_data(request):
    """API: Получить данные submission для редактирования"""
    try:
        submission_id = int(request.match_info.get('id'))

        submission = await db.get_submission_by_id(submission_id)
        if not submission:
            return web.json_response({'error': 'Submission not found'}, status=404)

        items = await db.get_submission_items(submission_id)

        # Конвертируем в формат для WebApp
        stock_data = []
        for item in items:
            stock_data.append({
                'product_id': item['product_id'],
                'name_russian': item['name_russian'],
                'quantity': item.get('edited_quantity') or item['quantity'],
                'weight': item.get('edited_weight') or item['weight'],
                'package_weight': item['package_weight'],
                'unit': item['unit']
            })

        return web.json_response({
            'submission_id': submission_id,
            'date': submission['submission_date'].isoformat(),
            'stock': stock_data,
            'submitted_by': submission['submitted_by'],
            'status': submission['status']
        })

    except Exception as e:
        print(f"Ошибка получения submission: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def update_submission(request):
    """API: Обновить submission (редактирование админом)"""
    try:
        data = await request.json()
        submission_id = data.get('submission_id')
        stock_items = data.get('stock', [])

        # Обновляем items
        for item in stock_items:
            await db.update_submission_item(
                submission_id=submission_id,
                product_id=item['product_id'],
                quantity=item['quantity'],
                weight=item['weight']
            )

        print(f"✅ Submission #{submission_id} обновлен")

        return web.json_response({
            'success': True,
            'message': 'Изменения сохранены'
        })

    except Exception as e:
        print(f"Ошибка обновления submission: {e}")
        return web.json_response({'error': str(e)}, status=500)


def create_app():
    """Создать приложение aiohttp"""
    app = web.Application()

    # Настройка CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })

    # Роуты
    app.router.add_get('/', index)
    app.router.add_get('/order_edit', order_edit)
    app.router.add_get('/api/products', get_products)
    app.router.add_post('/api/stock', save_stock)
    app.router.add_get('/api/stock/latest', get_latest_stock)
    app.router.add_get('/api/stock/check', check_stock_exists)
    app.router.add_get('/api/stock/yesterday', get_yesterday_stock)
    app.router.add_get('/api/stock/{date}', get_stock_for_date)
    app.router.add_get('/api/supplies/today', get_today_supplies)

    # Роуты для модерации
    app.router.add_get('/api/submission/{id}', get_submission_data)
    app.router.add_post('/api/submission/update', update_submission)

    # Роуты для редактирования заказов
    app.router.add_post('/api/draft_order', save_draft_order)
    app.router.add_get('/api/draft_order/{draft_key}', get_draft_order)

    # Применяем CORS ко всем роутам
    for route in list(app.router.routes()):
        cors.add(route)

    # Хуки жизненного цикла
    app.on_startup.append(init_db)
    app.on_cleanup.append(close_db)

    return app


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app = create_app()
    print(f"🚀 Запуск веб-сервера на порту {port}")
    web.run_app(app, host='0.0.0.0', port=port)
