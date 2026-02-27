"""
Веб-сервер для Telegram Mini App (SaaS Version)
"""
from aiohttp import web
import aiohttp_cors
import aiosqlite
import os
import sys
import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path

import aiohttp_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography.fernet import Fernet
import aiohttp_jinja2
import jinja2

# Добавляем путь к родительской директории
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database
from database_pg import DatabasePG
from dotenv import load_dotenv
from utils.working_day import get_working_date

load_dotenv()

# Инициализация базы данных
DATABASE_URL = os.getenv('DATABASE_URL')
db = None

# Глобальный экземпляр бота для уведомлений
bot_instance = None

# Временное хранилище черновиков заказов
draft_orders = {}


def set_bot_instance(bot):
    """Установить глобальный экземпляр бота (не используется в production)"""
    global bot_instance
    bot_instance = bot


def json_serializer(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)

def safe_json_response(data, status=200):
    """Безопасный ответ JSON с поддержкой дат"""
    return web.json_response(data, status=status, dumps=lambda x: json.dumps(x, default=json_serializer))

def get_bot_instance():
    """Получить или создать экземпляр бота для уведомлений"""
    global bot_instance
    if bot_instance is None:
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
    database_url = os.getenv('DATABASE_URL')
    
    if database_url and database_url.startswith('postgres'):
        print(f"🔌 Подключение к PostgreSQL: {database_url.split('@')[-1]}")
        db = DatabasePG(database_url)
    else:
        db_path = os.getenv('DATABASE_PATH', 'wedrink.db')
        print(f"📁 Использование SQLite: {db_path}")
        db = Database(db_path)
        
    if hasattr(db, 'init_db'):
        await db.init_db()
    print("✅ База данных инициализирована")


async def close_db(app):
    """Закрытие БД при остановке"""
    global db
    if db and hasattr(db, 'close'):
        await db.close()


async def get_current_user(request):
    """Вспомогательная функция для получения текущего пользователя из сессии"""
    session = await aiohttp_session.get_session(request)
    if 'user' in session:
        return session['user']
    return None

async def get_current_company(request):
    """Получить ID компании текущего пользователя"""
    user = await get_current_user(request)
    if user and user.get('company_id'):
        return user['company_id']
    # Fallback для Staging Phase 1 (Все попадают в компанию 1)
    return 1


@web.middleware
async def auth_middleware(request, handler):
    """Мидлвар для проверки авторизации"""
    public_paths = [
        '/api/auth/telegram',
        '/login',
        '/static',
        '/favicon.ico'
    ]
    
    if request.path.startswith('/api/') and 'x-telegram-init-data' in request.headers:
        return await handler(request)

    path_is_public = any(request.path.startswith(p) for p in public_paths)
    
    if not path_is_public:
        user = await get_current_user(request)
        if not user:
            if request.path.startswith('/api/'):
                print(f"🔒 Unauthorized API access to {request.path}")
                return safe_json_response({'error': 'Unauthorized'}, status=401)
            else:
                print(f"🔒 Redirecting to /login from {request.path}")
                raise web.HTTPFound('/login')
                
    return await handler(request)


def verify_telegram_auth(data: dict, bot_token: str) -> bool:
    """Verifies Telegram login widget data"""
    if 'hash' not in data:
        return False

    received_hash = data.pop('hash')

    valid_fields = ['id', 'first_name', 'last_name', 'username', 'photo_url', 'auth_date']
    data_check_list = []
    for k, v in data.items():
        if k in valid_fields and v is not None:
            data_check_list.append(f"{k}={v}")
    
    data_check_string = "\n".join(sorted(data_check_list))
    
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    hmac_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    is_valid = hmac_hash == received_hash
    if not is_valid:
        print(f"❌ Hash mismatch. Expected: {hmac_hash}, got: {received_hash}")
    return is_valid


async def telegram_login(request):
    """API: Обработка входа через Telegram Login Widget"""
    data = dict(request.query)
    print(f"🔑 Telegram Auth Callback received: {json.dumps(data)}")
    
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        print("❌ Error: BOT_TOKEN not found in environment")
        return safe_json_response({'error': 'Server configuration error'}, status=500)
        
    if not verify_telegram_auth(data.copy(), bot_token):
        print("❌ Error: Telegram hash verification failed")
        return safe_json_response({'error': 'Invalid Telegram authentication'}, status=403)
        
    auth_date = int(data.get('auth_date', 0))
    if datetime.now().timestamp() - auth_date > 86400:
        return safe_json_response({'error': 'Authentication expired'}, status=403)
        
    user_id = int(data.get('id'))
    username = data.get('username')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    photo_url = data.get('photo_url')
    
    # Обновляем инфу о пользователе в БД.
    await db.add_or_update_user(user_id, username, first_name, last_name, company_id=None)
    
    # Делаем пользователя Супер-Админом (admin) с company_id=1, если он первый в базе Staging
    async with db.pool.acquire() as conn:
        admin_check = await conn.fetchval("SELECT count(*) FROM users WHERE role = 'admin'")
        if admin_check == 0:
            await conn.execute("UPDATE users SET role = 'admin', company_id = 1 WHERE id = $1", user_id)
        else:
            # На случай если админ уже был создан, но company_id еще не был равен 1 (старый лог)
            user_current_role = await conn.fetchrow("SELECT role, company_id FROM users WHERE id = $1", user_id)
            if user_current_role and user_current_role['role'] == 'admin' and user_current_role['company_id'] is None:
                await conn.execute("UPDATE users SET company_id = 1 WHERE id = $1", user_id)

    user_info = await db.get_user_info(user_id)
    role = await db.get_user_role(user_id)
    company_id = user_info.get('company_id') if user_info and user_info.get('company_id') else 1
    
    session = await aiohttp_session.get_session(request)
    session['user'] = {
        'id': user_id,
        'username': username,
        'first_name': first_name,
        'last_name': last_name,
        'photo_url': photo_url,
        'role': role,
        'company_id': company_id
    }
    
    raise web.HTTPFound('/')


async def login_page(request):
    """Страница логина"""
    user = await get_current_user(request)
    if user:
        raise web.HTTPFound('/')
        
    bot_username = os.getenv('BOT_USERNAME', 'Zakupformbot')
    auth_url = "/api/auth/telegram"
    host = request.headers.get('Host', request.host)
    print(f"📱 Serving login page. Host: {host}, Bot: {bot_username}")
    
    context = {
        'bot_username': bot_username,
        'auth_url': auth_url
    }
    
    return aiohttp_jinja2.render_template('login.html', request, context)


async def logout(request):
    """Выход из системы"""
    session = await aiohttp_session.get_session(request)
    session.invalidate()
    raise web.HTTPFound('/login')


async def get_current_user_api(request):
    """API: Получить текущего пользователя"""
    user = await get_current_user(request)
    if user:
        user['is_superadmin'] = (user.get('role') == 'admin' and user.get('company_id') == 1)
        return safe_json_response({'user': user})
    return safe_json_response({'error': 'Not logged in'}, status=401)


async def dashboard_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('dashboard.html', request, context)


async def stock_input_page(request):
    user = await get_current_user(request)
    if not user:
        raise web.HTTPFound('/login')
    context = {'user': user, 'edit_submission_id': None}
    return aiohttp_jinja2.render_template('stock_input.html', request, context)

async def submission_edit_page(request):
    """Страница модерации заявки по ссылке из Телеграм"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
        
    submission_id = request.query.get('id')
    if not submission_id:
        raise web.HTTPFound('/stock_input')
        
    context = {'user': user, 'edit_submission_id': submission_id}
    # Используем ту же страницу `stock_input.html`, но с флагом редактирования
    return aiohttp_jinja2.render_template('stock_input.html', request, context)

async def current_stock_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('current_stock.html', request, context)

async def orders_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('orders.html', request, context)

async def history_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('history.html', request, context)

async def supply_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('supply.html', request, context)

async def reports_page(request):
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('reports.html', request, context)

async def generate_order_api(request):
    """API: Генерация заказа на указанное кол-во дней"""
    try:
        company_id = await get_current_company(request)
        days = int(request.query.get('days', 10))
        lookback = int(request.query.get('lookback', 30))
        
        if days <= 0 or lookback <= 0:
            return safe_json_response({'error': 'Параметры должны быть больше 0'}, status=400)
            
        from utils.calculations import calculate_order
        result = await calculate_order(db, company_id, days, lookback_days=lookback)
        return safe_json_response(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return safe_json_response({'error': str(e)}, status=500)

async def get_history_api(request):
    """API: История остатков"""
    try:
        company_id = await get_current_company(request)
        product_id = int(request.match_info.get('product_id'))
        days = int(request.query.get('days', 14))
        history = await db.get_stock_history(company_id, product_id, days)
        return safe_json_response(history)
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def get_daily_report_api(request):
    """API: Отчет за день"""
    try:
        company_id = await get_current_company(request)
        date_str = request.query.get('date', get_working_date())
        
        prev_date = await db.get_latest_date_before(company_id, date_str)
        
        if not prev_date:
            return safe_json_response({
                'date': date_str,
                'consumption': [],
                'total_supply_cost': await db.get_supply_total(company_id, date_str)
            })

        consumption = await db.calculate_consumption(company_id, str(prev_date), date_str)
        total_supply_cost = await db.get_supply_total(company_id, date_str)
                
        return safe_json_response({
            'date': date_str,
            'prev_date': str(prev_date),
            'consumption': consumption,
            'total_supply_cost': total_supply_cost
        })

    except Exception as e:
        print(f"Ошибка API отчета: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def get_weekly_report_api(request):
    """API: Отчет за неделю"""
    try:
        company_id = await get_current_company(request)
        end_date = get_working_date()
        from datetime import timedelta
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        start_dt = end_dt - timedelta(days=7)
        start_date = start_dt.strftime('%Y-%m-%d')
        
        consumption = await db.calculate_consumption(company_id, start_date, end_date)
        total_supply_cost = await db.get_supply_total_period(company_id, start_date, end_date)
                
        return safe_json_response({
            'start_date': start_date,
            'end_date': end_date,
            'consumption': consumption,
            'total_supply_cost': total_supply_cost
        })

    except Exception as e:
        print(f"Ошибка API недельного отчета: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def index(request):
    """Главная страница Mini App / Web App"""
    user = await get_current_user(request)
    html_file = 'dashboard.html' if user['role'] in ['admin', 'manager'] else 'stock_input.html'
    html_path = Path(__file__).parent / 'templates' / html_file
    
    if not html_path.exists():
        html_file = 'stock_input.html'
        
    context = {'user': user}
    return aiohttp_jinja2.render_template(html_file, request, context)


async def order_edit(request):
    user = await get_current_user(request)
    context = {'user': user}
    return aiohttp_jinja2.render_template('order_edit.html', request, context)


async def get_products(request):
    """API: Получить список всех товаров"""
    try:
        company_id = await get_current_company(request)
        products = await db.get_all_products(company_id)

        for product in products:
            if 'created_at' in product and product['created_at']:
                product['created_at'] = str(product['created_at'])

        return safe_json_response(products)
    except Exception as e:
        print(f"Ошибка получения товаров: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def save_supply(request):
    """API: Сохранить поставку"""
    try:
        user = await get_current_user(request)
        if not user or user['role'] not in ['admin', 'manager']:
             return safe_json_response({'error': 'Unauthorized'}, status=401)
             
        company_id = await get_current_company(request)
        data = await request.json()
        items = data.get('items', [])
        date_str = data.get('date', get_working_date())
        
        for item in items:
            product_id = item.get('product_id')
            boxes = float(item.get('boxes', 0))
            weight = float(item.get('weight', 0))
            cost = float(item.get('cost', 0))
            
            if boxes > 0 or weight > 0:
                await db.add_supply(company_id, product_id, date_str, int(boxes), weight, cost)
                
        return safe_json_response({'status': 'ok'})
    except Exception as e:
        print(f"Ошибка сохранения поставки: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def save_stock(request):
    """API: Сохранить остатки (с модерацией для сотрудников)"""
    try:
        company_id = await get_current_company(request)
        data = await request.json()
        stock_items = data.get('stock', [])
        user_id = data.get('user_id')

        if not user_id or user_id == 'unknown':
            return safe_json_response({'error': 'User ID required'}, status=400)

        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        user_role = await db.get_user_role(user_id)

        if user_role == 'admin':
            for item in stock_items:
                await db.add_stock(
                    company_id=company_id,
                    product_id=item['product_id'],
                    date=date_obj,
                    quantity=item['quantity'],
                    weight=item['weight']
                )

            print(f"✅ Админ {user_id} (Co:{company_id}) сохранил {len(stock_items)} позиций")

            return safe_json_response({
                'success': True,
                'message': f'Сохранено {len(stock_items)} позиций',
                'working_date': working_date_str,
                'requires_moderation': False
            })
        else:
            try:
                submission_id = await db.create_stock_submission(
                    company_id=company_id,
                    user_id=user_id,
                    date=date_obj,
                    items=stock_items
                )
            except ValueError as e:
                return safe_json_response({'error': str(e)}, status=400)

            print(f"📝 Сотрудник {user_id} создал submission #{submission_id} для Co:{company_id}")

            await notify_admins_about_submission(company_id, submission_id, user_id,
                                                working_date_str, stock_items)

            return safe_json_response({
                'success': True,
                'message': 'Остатки отправлены на модерацию',
                'working_date': working_date_str,
                'submission_id': submission_id,
                'requires_moderation': True
            })

    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def get_latest_stock(request):
    """API: Получить последние остатки"""
    try:
        company_id = await get_current_company(request)
        stock = await db.get_latest_stock(company_id)

        for item in stock:
            if 'created_at' in item and item['created_at']:
                item['created_at'] = str(item['created_at'])
            if 'date' in item and item['date']:
                item['date'] = str(item['date'])

        return safe_json_response(stock)
    except Exception as e:
        print(f"Ошибка получения остатков: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def check_stock_exists(request):
    """API: Проверить наличие остатков за текущий рабочий день"""
    try:
        company_id = await get_current_company(request)
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        exists = await db.has_stock_for_date(company_id, date_obj)

        return safe_json_response({
            'exists': exists,
            'working_date': working_date_str
        })
    except Exception as e:
        print(f"Ошибка проверки остатков: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def get_stock_for_date(request):
    """API: Получить остатки за конкретную дату"""
    try:
        company_id = await get_current_company(request)
        date_str = request.match_info.get('date')
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

        stock = await db.get_stock_by_date(company_id, date_obj)

        for item in stock:
            if 'created_at' in item and item['created_at']:
                item['created_at'] = str(item['created_at'])
            if 'date' in item and item['date']:
                item['date'] = str(item['date'])

        return safe_json_response(stock)
    except Exception as e:
        print(f"❌ Ошибка получения остатков: {e}")
        import traceback
        traceback.print_exc()
        return safe_json_response({'error': str(e)}, status=500)


async def get_yesterday_stock(request):
    """АПИ: Получить остатки за последний рабочий день до сегодня"""
    try:
        company_id = await get_current_company(request)
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        latest_previous_date = await db.get_latest_date_before(company_id, str(date_obj))

        if not latest_previous_date:
            return safe_json_response({
                'stock': [],
                'date': None,
                'working_date': working_date_str
            })

        stock = await db.get_stock_by_date(company_id, latest_previous_date)

        for item in stock:
            if 'created_at' in item and item['created_at']:
                item['created_at'] = str(item['created_at'])
            if 'date' in item and item['date']:
                item['date'] = str(item['date'])

        return safe_json_response({
            'stock': stock,
            'date': latest_previous_date,
            'working_date': working_date_str
        })

    except Exception as e:
        print(f"Ошибка получения вчерашних остатков: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def get_today_supplies(request):
    """АПИ: Получить поставки между последними остатками и сегодня"""
    try:
        company_id = await get_current_company(request)
        working_date_str = get_working_date()
        date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()

        latest_prev = await db.get_latest_date_before(company_id, str(date_obj))
        start_date = latest_prev if latest_prev else str(date_obj)

        supplies = await db.get_supplies_between(company_id, start_date, working_date_str)

        supplies_dict = {}
        for supply in supplies:
            pid = supply['product_id']
            packages = supply['boxes'] * supply['units_per_box']
            supplies_dict[pid] = supplies_dict.get(pid, 0) + packages

        return safe_json_response({
            'supplies': supplies_dict,
            'working_date': working_date_str,
            'period': {'from': start_date, 'to': str(date_obj)}
        })

    except Exception as e:
        print(f"Ошибка получения поставок: {e}")
        import traceback
        traceback.print_exc()
        return safe_json_response({'error': str(e)}, status=500)


async def notify_admins_about_submission(company_id, submission_id, user_id, date_str, items):
    """Отправить уведомление админам компании о новой заявке"""
    bot = get_bot_instance()
    if not bot:
        return

    try:
        admin_ids = await db.get_admin_ids(company_id)
        user_info = await db.get_user_info(user_id)
        username = user_info.get('username') or user_info.get('first_name') or 'Неизвестно'

        message = f"""
🔔 <b>НОВАЯ ЗАЯВКА НА ОСТАТКИ</b>

🏢 Точка: {user_info.get('company_name', 'Неизвестно')}
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
            except Exception as e:
                print(f"❌ Ошибка отправки уведомления админу {admin_id}: {e}")
    except Exception as e:
        print(f"❌ Ошибка в notify_admins_about_submission: {e}")


async def save_draft_order(request):
    """API: Сохранить черновик заказа"""
    try:
        data = await request.json()
        draft_key = data.get('draft_key')
        order_data = data.get('order_data')

        if not draft_key or not order_data:
            return safe_json_response({'error': 'Missing draft_key or order_data'}, status=400)

        draft_orders[draft_key] = order_data
        return safe_json_response({'success': True, 'draft_key': draft_key})
    except Exception:
        return safe_json_response({'error': 'Error'}, status=500)

async def get_draft_order(request):
    """API: Получить данные черновика заказа"""
    try:
        draft_key = request.match_info.get('draft_key')
        if draft_key not in draft_orders:
            return safe_json_response({'error': 'Draft not found'}, status=404)
        return safe_json_response(draft_orders[draft_key])
    except Exception:
        return safe_json_response({'error': 'Error'}, status=500)


async def get_submission_data(request):
    """API: Получить данные submission для редактирования"""
    try:
        company_id = await get_current_company(request)
        submission_id = int(request.match_info.get('id'))

        submission = await db.get_submission_by_id(company_id, submission_id)
        if not submission:
            return safe_json_response({'error': 'Submission not found or unauthorized'}, status=404)

        items = await db.get_submission_items(submission_id)

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

        return safe_json_response({
            'submission_id': submission_id,
            'date': submission['submission_date'].isoformat(),
            'stock': stock_data,
            'submitted_by': submission['submitted_by'],
            'status': submission['status']
        })

    except Exception as e:
        print(f"Ошибка получения submission: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def update_submission(request):
    """API: Обновить submission (редактирование админом)"""
    try:
        data = await request.json()
        submission_id = data.get('submission_id')
        stock_items = data.get('stock', [])

        for item in stock_items:
            await db.update_submission_item(
                submission_id=submission_id,
                product_id=item['product_id'],
                edited_quantity=item['quantity'],
                edited_weight=item['weight']
            )

        return safe_json_response({
            'success': True,
            'message': 'Изменения сохранены'
        })

    except Exception as e:
        print(f"Ошибка обновления submission: {e}")
        return safe_json_response({'error': str(e)}, status=500)


def create_app():
    """Создать приложение aiohttp"""
    app = web.Application()

    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })

    # Pages routes
    app.router.add_get('/', index)
    app.router.add_get('/login', login_page)
    app.router.add_get('/logout', logout)
    app.router.add_get('/dashboard', dashboard_page)
    app.router.add_get('/stock', current_stock_page)
    app.router.add_get('/stock_input', stock_input_page)
    app.router.add_get('/submission_edit', submission_edit_page)
    app.router.add_get('/orders', orders_page)
    app.router.add_get('/history', history_page)
    app.router.add_get('/reports', reports_page)
    app.router.add_get('/supply', supply_page)
    app.router.add_get('/order_edit', order_edit)
    
    # API endpoints
    app.router.add_get('/api/auth/telegram', telegram_login)
    app.router.add_get('/api/user/me', get_current_user_api)
    app.router.add_get('/api/orders/generate', generate_order_api)
    app.router.add_get('/api/history/{product_id}', get_history_api)
    app.router.add_get('/api/reports/daily', get_daily_report_api)
    app.router.add_get('/api/reports/weekly', get_weekly_report_api)
    app.router.add_post('/api/supply', save_supply)
    
    app.router.add_get('/api/products', get_products)
    app.router.add_post('/api/stock', save_stock)
    app.router.add_get('/api/stock/latest', get_latest_stock)
    app.router.add_get('/api/stock/check', check_stock_exists)
    app.router.add_get('/api/stock/yesterday', get_yesterday_stock)
    app.router.add_get('/api/stock/{date}', get_stock_for_date)
    app.router.add_get('/api/supplies/today', get_today_supplies)

    app.router.add_get('/superadmin', superadmin_page)
    app.router.add_post('/api/superadmin/companies', api_create_company)
    app.router.add_post('/api/superadmin/companies/{id}/subscription', api_update_company_subscription)
    app.router.add_delete('/api/superadmin/companies/{id}', api_delete_company)

    app.router.add_get('/staff', staff_page)
    app.router.add_post('/api/company/invite', api_invite_staff)
    app.router.add_post('/api/company/update_role', api_update_staff_role)

    app.router.add_get('/api/submission/{id}', get_submission_data)
    app.router.add_post('/api/submission/update', update_submission)

    app.router.add_post('/api/draft_order', save_draft_order)
    app.router.add_get('/api/draft_order/{draft_key}', get_draft_order)

    for route in list(app.router.routes()):
        cors.add(route)

    static_dir = Path(__file__).parent / 'static'
    static_dir.mkdir(exist_ok=True)
    app.router.add_static('/static/', path=str(static_dir), name='static')

    templates_dir = Path(__file__).parent / 'templates'
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(str(templates_dir)))

    session_key = os.getenv('SESSION_KEY')
    if not session_key:
        session_key = os.urandom(32)
    elif isinstance(session_key, str):
        session_key = session_key.encode()
        if len(session_key) > 32:
            session_key = session_key[:32]
        elif len(session_key) < 32:
            session_key = session_key.ljust(32, b'\0')
    
    storage = EncryptedCookieStorage(
        session_key, 
        cookie_name='WeDrink_Session',
        max_age=86400 * 30,
        httponly=True,
        secure=True,
        samesite='Lax'
    )
    aiohttp_session.setup(app, storage)

    app.middlewares.append(auth_middleware)

    app.on_startup.append(init_db)
    app.on_cleanup.append(close_db)

    return app


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app = create_app()
    print(f"🚀 Запуск веб-сервера на порту {port}")
    web.run_app(app, host='0.0.0.0', port=port)

# ==========================================
# SUPERADMIN ROUTES & APIs
# ==========================================

async def superadmin_page(request):
    """Страница управления франшизами (Только для Super-Admin)"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin':
        raise web.HTTPFound('/login')
        
    # Двойная проверка, что пользователь именно Супер-Админ (создатель Платформы)
    # В этой версии Супер-Админ - это тот, кто первым зарегистрировался (id=1) 
    # или чья `company_id` = 1, но для надежности можно проверить БД:
    async with db.pool.acquire() as conn:
        record = await conn.fetchrow("SELECT role, company_id FROM users WHERE id = $1", user['id'])
        if not record or record['role'] != 'admin' or record['company_id'] != 1:
            return web.Response(text="Доступ запрещен. Только для Платформодержателя.", status=403)
            
    companies = await db.get_all_companies()
    
    total_companies = len(companies)
    active_companies = sum(1 for c in companies if c['subscription_status'] == 'active')
    total_users = sum(c['user_count'] for c in companies)

    context = {
        'page': 'superadmin',
        'companies': companies,
        'total_companies': total_companies,
        'active_companies': active_companies,
        'total_users': total_users,
        'user': user
    }
    return aiohttp_jinja2.render_template('superadmin.html', request, context)


async def api_create_company(request):
    """API: Создать новую компанию (Франшизу)"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin' or user.get('company_id') != 1:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    try:
        data = await request.json()
        name = data.get('name')
        trial_days = data.get('trial_days', 14)
        
        if not name:
            return safe_json_response({'error': 'Имя компании обязательно'}, status=400)
            
        company = await db.create_company(name, trial_days)
        if not company:
            return safe_json_response({'error': 'Ошибка создания компании в БД'}, status=500)
            
        # Генерируем инвайт-ссылку для Владельца новой компании
        # В идеале нужно хранить токены в БД, но для простоты зашифруем данные в base64
        import base64
        import json
        invite_data = json.dumps({'c': company['id'], 'r': 'admin', 't': int(datetime.now().timestamp())})
        invite_token = base64.urlsafe_b64encode(invite_data.encode()).decode().rstrip('=')
        
        bot_username = os.getenv('BOT_USERNAME', 'Zakupformbot')
        invite_url = f"https://t.me/{bot_username}?start=invite_{invite_token}"
            
        return safe_json_response({
            'success': True,
            'company': company,
            'invite_url': invite_url
        })
    except Exception as e:
        print(f"Ошибка api_create_company: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_update_company_subscription(request):
    """API: Обновить статус подписки или продлить её (Только Super-Admin)"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin' or user.get('company_id') != 1:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    try:
        company_id = int(request.match_info['id'])
        if company_id == 1:
            return safe_json_response({'error': 'Нельзя изменить системную компанию'}, status=400)
            
        data = await request.json()
        status = data.get('status')
        days_to_add = data.get('days_to_add')
        
        if not status:
            return safe_json_response({'error': 'Статус обязателен'}, status=400)
            
        await db.update_company_subscription(company_id, status, days_to_add)
        return safe_json_response({'success': True})
    except Exception as e:
        print(f"Ошибка api_update_company_subscription: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_delete_company(request):
    """API: Удалить компанию (Только Super-Admin)"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin' or user.get('company_id') != 1:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    try:
        company_id = int(request.match_info['id'])
        if company_id == 1:
            return safe_json_response({'error': 'Нельзя удалить системную компанию'}, status=400)
            
        await db.delete_company(company_id)
        return safe_json_response({'success': True})
    except Exception as e:
        print(f"Ошибка api_delete_company: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def staff_page(request):
    """Страница управления сотрудниками (Только для Admin/Manager)"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        raise web.HTTPFound('/login')
        
    company_id = await get_current_company(request)
    staff = await db.get_users_by_company(company_id)
    
    context = {
        'page': 'staff',
        'staff': staff,
        'user': user,
        'company_id': company_id
    }
    return aiohttp_jinja2.render_template('staff.html', request, context)

async def api_invite_staff(request):
    """API: Сгенерировать инвайт для нового сотрудника"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    company_id = await get_current_company(request)
    
    try:
        data = await request.json()
        role = data.get('role', 'employee')
        
        # Зашифруем данные в base64
        import base64
        import json
        invite_data = json.dumps({'c': company_id, 'r': role, 't': int(datetime.now().timestamp())})
        
        # Исправленный алгоритм (без лишних =)
        invite_token_raw = base64.urlsafe_b64encode(invite_data.encode()).decode()
        invite_token = invite_token_raw.rstrip('=')
        
        bot_username = os.getenv('BOT_USERNAME', 'Zakupformbot')
        invite_url = f"https://t.me/{bot_username}?start=invite_{invite_token}"
            
        return safe_json_response({
            'success': True,
            'invite_url': invite_url
        })
    except Exception as e:
        print(f"Ошибка api_invite_staff: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_update_staff_role(request):
    """API: Изменить роль сотрудника"""
    user = await get_current_user(request)
    # Только admin может менять роли
    if not user or user.get('role') != 'admin':
        return safe_json_response({'error': 'Доступ запрещен. Только Администратор может изменять роли.'}, status=403)
        
    company_id = await get_current_company(request)
    
    try:
        data = await request.json()
        target_user_id = data.get('user_id')
        new_role = data.get('role')
        
        if not target_user_id or not new_role:
            return safe_json_response({'error': 'Отсутствуют обязательные параметры'}, status=400)
            
        if new_role not in ['employee', 'manager', 'admin']:
            return safe_json_response({'error': 'Недействительная роль'}, status=400)
            
        if target_user_id == user['id']:
            return safe_json_response({'error': 'Вы не можете изменить свою собственную роль'}, status=400)

        # Проверим, принадлежит ли юзер этой компании
        target_role = await db.get_user_role(target_user_id)
        if not target_role:
             return safe_json_response({'error': 'Сотрудник не найден'}, status=404)
             
        # TODO: В идеале здесь нужна строгая проверка company_id таргета
        
        await db.update_user_role(target_user_id, new_role)
            
        return safe_json_response({'success': True})
    except Exception as e:
        print(f"Ошибка api_update_staff_role: {e}")
        return safe_json_response({'error': str(e)}, status=500)
