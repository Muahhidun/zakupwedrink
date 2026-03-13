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
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
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
    """Вспомогательная функция для получения текущего пользователя из сессии или Telegram WebApp"""
    
    # 1. Сначала проверяем заголовок x-telegram-init-data (для Mini App)
    init_data = request.headers.get('x-telegram-init-data')
    if init_data:
        bot_token = os.getenv('BOT_TOKEN')
        if bot_token:
            tg_user = verify_telegram_webapp(init_data, bot_token)
            if tg_user:
                # Если токен валиден, возвращаем пользователя (эмуляция сессии)
                user_id = tg_user.get('id')
                user_info = await db.get_user_info(user_id)
                role = user_info.get('role') if user_info else 'user'
                company_id = user_info.get('company_id') if user_info else None
                
                if user_info and not user_info.get('is_active', True):
                    return None
                    
                return {
                    'id': user_id,
                    'username': tg_user.get('username'),
                    'first_name': tg_user.get('first_name'),
                    'last_name': tg_user.get('last_name'),
                    'photo_url': tg_user.get('photo_url'),
                    'role': role,
                    'company_id': company_id,
                    'is_active': user_info.get('is_active', True) if user_info else True
                }

    # 2. Иначе проверяем Cookie сессию (для обычного браузера)
    session = await aiohttp_session.get_session(request)
    if 'user' in session:
        user_data = session['user']
        # Всегда перепроверяем статус активности в БД для безопасности
        user_info = await db.get_user_info(user_data['id'])
        if user_info and not user_info.get('is_active', True):
            session.invalidate()
            return None
            
        # Обновляем роль и компанию на случай если их изменили
        if user_info:
            user_data['role'] = user_info.get('role', user_data.get('role', 'user'))
            user_data['company_id'] = user_info.get('company_id', user_data.get('company_id'))
            session['user'] = user_data
            
        return user_data
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

    path_is_public = any(request.path.startswith(p) for p in public_paths) or request.path == '/'
    
    if not path_is_public:
        user = await get_current_user(request)
        if not user:
            if request.path.startswith('/api/'):
                print(f"🔒 Unauthorized API access to {request.path}")
                return safe_json_response({'error': 'Unauthorized'}, status=401)
            # Для HTML страниц мы не делаем серверный редирект, чтобы Mini App мог загрузить скрипт авторизации.
            # На стороне клиента app.js проверит /api/user/me и сделает редирект если нужно.
        else:
            # Check company subscription status
            company_id = user.get('company_id')
            if company_id and company_id != 1 and not request.path.startswith('/superadmin'):
                async with db.pool.acquire() as conn:
                    status = await conn.fetchval("SELECT subscription_status FROM companies WHERE id = $1", company_id)
                
                if status == 'expired' and request.path != '/expired':
                    if request.path.startswith('/api/'):
                        return safe_json_response({'error': 'Subscription expired'}, status=403)
                    elif request.path.startswith('/dashboard') or request.path == '/' or request.path.startswith('/manager'):
                        raise web.HTTPFound('/expired')
                
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


def verify_telegram_webapp(init_data: str, bot_token: str) -> dict | None:
    """Verifies Telegram WebApp initData and returns parsed user dict if valid"""
    import urllib.parse
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if 'hash' not in parsed_data:
            return None
            
        received_hash = parsed_data.pop('hash')
        
        # Sort keys
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        # Calculate WebAppData secret key
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash != received_hash:
            return None
            
        # Parse user JSON
        if 'user' in parsed_data:
            return json.loads(parsed_data['user'])
        return None
    except Exception as e:
        print(f"❌ Error parsing Telegram WebApp data: {e}")
        return None


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
    
    if user_info and not user_info.get('is_active', True):
        # Если сотрудник удален (неактивен), запрещаем вход
        print(f"❌ Error: Вход заблокирован для удаленного пользователя {user_id}")
        raise web.HTTPFound('/login?error=inactive')
        
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
    
    edit_id = request.query.get('edit_submission_id')
    context = {'user': user, 'edit_submission_id': edit_id}
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
    """Страница текущих остатков"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('current_stock.html', request, context)

async def orders_page(request):
    """Страница параметров заказа"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('orders.html', request, context)

async def history_page(request):
    """Страница истории"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('history.html', request, context)

async def supply_page(request):
    """Страница приемки товаров"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
    context = {'user': user}
    return aiohttp_jinja2.render_template('supply.html', request, context)

async def reports_page(request):
    """Страница отчетов"""
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
        
        if days <= 0:
            return safe_json_response({'error': 'Параметры должны быть больше 0'}, status=400)
            
        from utils.calculations import calculate_order
        result = await calculate_order(db, company_id, days)
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
        
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        has_data = await db.has_stock_for_date(company_id, date_obj)
        
        if not has_data:
            return safe_json_response({
                'date': date_str,
                'consumption': [],
                'total_supply_cost': await db.get_supply_total(company_id, date_str)
            })
            
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
        
        # If no data for end_date, find the most recent day with data
        date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        has_end_data = await db.has_stock_for_date(company_id, date_obj)
        
        actual_end_date = end_date
        if not has_end_data:
            latest_date_str = await db.get_latest_date_before(company_id, end_date)
            if latest_date_str:
                actual_end_date = str(latest_date_str)
            else:
                # No data at all in DB
                return safe_json_response({
                    'start_date': end_date,
                    'end_date': end_date,
                    'consumption': [],
                    'total_supply_cost': 0
                })

        from datetime import timedelta
        actual_end_dt = datetime.strptime(actual_end_date, '%Y-%m-%d')
        start_dt = actual_end_dt - timedelta(days=7)
        start_date = start_dt.strftime('%Y-%m-%d')
        
        # Check if we have data on start_date, if not find nearest before
        has_start_data = await db.has_stock_for_date(company_id, start_dt.date())
        actual_start_date = start_date
        if not has_start_data:
            prev_start = await db.get_latest_date_before(company_id, start_date)
            if prev_start:
                actual_start_date = str(prev_start)

        consumption = await db.calculate_consumption(company_id, actual_start_date, actual_end_date)
        total_supply_cost = await db.get_supply_total_period(company_id, actual_start_date, actual_end_date)
                
        return safe_json_response({
            'start_date': actual_start_date,
            'end_date': actual_end_date,
            'consumption': consumption,
            'total_supply_cost': total_supply_cost
        })

    except Exception as e:
        print(f"Ошибка API недельного отчета: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_reports_advanced(request):
    """API: Продвинутая аналитика за 30 дней (ABC, круговая диаграмма)"""
    try:
        company_id = await get_current_company(request)
        end_date = get_working_date()
        
        date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        has_end_data = await db.has_stock_for_date(company_id, date_obj)
        
        actual_end_date = end_date
        if not has_end_data:
            latest = await db.get_latest_date_before(company_id, end_date)
            if latest:
                actual_end_date = str(latest)
            else:
                return safe_json_response({'consumption': []})
                
        actual_end_dt = datetime.strptime(actual_end_date, '%Y-%m-%d')
        from datetime import timedelta
        start_dt = actual_end_dt - timedelta(days=30)
        start_date = start_dt.strftime('%Y-%m-%d')
        
        has_start_data = await db.has_stock_for_date(company_id, start_dt.date())
        actual_start_date = start_date
        if not has_start_data:
            prev = await db.get_latest_date_before(company_id, start_date)
            if prev: actual_start_date = str(prev)
            
        consumption = await db.calculate_consumption(company_id, actual_start_date, actual_end_date)
        
        results = []
        for c in consumption:
            weight = c.get('consumed_weight', 0)
            if weight <= 0: continue
            price = c.get('price_per_box', 0)
            unit = c.get('unit', 'кг')
            
            if unit == 'шт':
                divisor = c.get('units_per_box', 1) or 1
            else:
                divisor = c.get('box_weight', 1) or 1
                
            cost = (weight / divisor) * price
            c['total_cost'] = cost
            results.append(c)
            
        return safe_json_response({
            'start_date': actual_start_date,
            'end_date': actual_end_date,
            'consumption': results
        })
    except Exception as e:
        print(f"Ошибка Advanced Report: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def index(request):
    """Главная страница Mini App / Web App"""
    user = await get_current_user(request) or {'role': 'user'}
    
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
        active_only = request.query.get('active_only', 'false').lower() == 'true'
        products = await db.get_all_products(company_id, active_only=active_only)

        for product in products:
            if 'created_at' in product and product['created_at']:
                product['created_at'] = str(product['created_at'])

        return safe_json_response(products)
    except Exception as e:
        print(f"Ошибка получения товаров: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def toggle_product_status_route(request):
    """API: Включить/выключить продукт"""
    try:
        user = await get_current_user(request)
        if not user or user['role'] not in ['admin', 'manager']:
             return safe_json_response({'error': 'Unauthorized'}, status=401)
             
        company_id = await get_current_company(request)
        product_id = int(request.match_info.get('id'))
        
        data = await request.json()
        is_active = data.get('is_active', True)
        
        success = await db.toggle_product_status(company_id, product_id, is_active)
        if success:
            return safe_json_response({'success': True})
        return safe_json_response({'error': 'Product not found'}, status=404)
    except Exception as e:
        print(f"Ошибка переключения статуса товара: {e}")
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
        resolve_pending_order_id = data.get('resolve_pending_order_id')
        debts = data.get('debts', [])
        
        for item in items:
            product_id = item.get('product_id')
            boxes = float(item.get('boxes', 0))
            weight = float(item.get('weight', 0))
            cost = float(item.get('cost', 0))
            
            if boxes > 0 or weight > 0:
                await db.add_supply(company_id, product_id, date_str, int(boxes), weight, cost)
                
                # Обновляем ценник товара в базе, если мы указали количество и стоимость
                if boxes > 0 and cost > 0:
                    new_price = round(cost / boxes, 2)
                    await db.update_product_price(company_id, product_id, new_price)
                
        if resolve_pending_order_id:
            await db.resolve_order_without_insert(int(resolve_pending_order_id))

        for db_item in debts:
            product_id = db_item.get('product_id')
            boxes = float(db_item.get('boxes', 0))
            weight = float(db_item.get('weight', 0))
            cost = float(db_item.get('cost', 0))
            if boxes > 0 or weight > 0:
                await db.add_supplier_debt(company_id, product_id, boxes, weight, cost)

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

        if not user_id or str(user_id) == 'unknown':
            return safe_json_response({'error': 'User ID required'}, status=400)
            
        try:
            user_id = int(user_id)
        except ValueError:
            return safe_json_response({'error': 'Invalid User ID format'}, status=400)

        user_role = await db.get_user_role(user_id)
        
        custom_date_str = data.get('date')
        if custom_date_str and user_role in ('admin', 'manager', 'superadmin'):
            try:
                date_obj = datetime.strptime(custom_date_str, '%Y-%m-%d').date()
                working_date_str = custom_date_str
            except ValueError:
                return safe_json_response({'error': 'Invalid date format, use YYYY-MM-DD'}, status=400)
        else:
            working_date_str = get_working_date()
            date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()


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
    """API: Получить последние остатки (с расчетом расхода)"""
    try:
        company_id = await get_current_company(request)
        stock = await db.get_stock_with_consumption(company_id)

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
        
        custom_date = request.query.get('date')
        if custom_date:
            working_date_str = custom_date
            date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()
        else:
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
        
        custom_date = request.query.get('date')
        if custom_date:
            working_date_str = custom_date
            date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()
        else:
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
        
        custom_date = request.query.get('date')
        if custom_date:
            working_date_str = custom_date
            date_obj = datetime.strptime(working_date_str, '%Y-%m-%d').date()
        else:
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


async def submissions_page(request):
    """Страница со списком всех заявок на модерации"""
    user = await get_current_user(request)
    if not user or user['role'] not in ['admin', 'manager']:
        raise web.HTTPFound('/')
        
    context = {'user': user}
    return aiohttp_jinja2.render_template('submissions.html', request, context)


async def api_get_submissions(request):
    """API: Получить список всех заявок франшизы"""
    try:
        company_id = await get_current_company(request)
        submissions = await db.get_pending_submissions(company_id)
        
        # Serialize datetime objects
        for sub in submissions:
            if 'submission_date' in sub and sub['submission_date']:
                sub['submission_date'] = str(sub['submission_date'])
            if 'created_at' in sub and sub['created_at']:
                sub['created_at'] = str(sub['created_at'])
                
        return safe_json_response({'submissions': submissions})
    except Exception as e:
        print(f"Ошибка получения списка заявок: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def api_approve_submission(request):
    """API: Утвердить заявку через Web UI"""
    try:
        company_id = await get_current_company(request)
        user = await get_current_user(request)
        if not user or user['role'] not in ['admin', 'manager']:
             return safe_json_response({'error': 'Unauthorized'}, status=403)
        data = await request.json()
        submission_id = data.get('submission_id')
        
        if not submission_id:
             return safe_json_response({'error': 'submission_id required'}, status=400)
             
        # Проверим, существует ли заявка для этой компании
        sub = await db.get_submission_by_id(company_id, submission_id)
        if not sub:
             return safe_json_response({'error': 'Submission not found'}, status=404)
             
        await db.approve_submission(submission_id, user['id'])
        
        # Опционально: отправить уведомление в Telegram сотруднику
        bot = get_bot_instance()
        if bot:
             try:
                 await bot.send_message(
                     chat_id=sub['submitted_by'],
                     text=f"✅ <b>ЗАЯВКА УТВЕРЖДЕНА</b>\n\nВаша заявка #{submission_id} от {sub['submission_date']} была утверждена.\n\nДанные успешно сохранены в базе.",
                     parse_mode="HTML"
                 )
             except Exception as notify_err:
                 print(f"Failed to notify user about approval: {notify_err}")

        return safe_json_response({'success': True, 'message': 'Заявка успешно утверждена'})
    except Exception as e:
        print(f"Ошибка утверждения заявки через Web UI: {e}")
        return safe_json_response({'error': str(e)}, status=500)


async def api_reject_submission(request):
    """API: Отклонить заявку через Web UI"""
    try:
        company_id = await get_current_company(request)
        user = await get_current_user(request)
        if not user or user['role'] not in ['admin', 'manager']:
             return safe_json_response({'error': 'Unauthorized'}, status=403)
        data = await request.json()
        submission_id = data.get('submission_id')
        reason = data.get('reason', 'Отвергнуто администратором без объяснения причин')
        
        if not submission_id:
             return safe_json_response({'error': 'submission_id required'}, status=400)
             
        sub = await db.get_submission_by_id(company_id, submission_id)
        if not sub:
             return safe_json_response({'error': 'Submission not found'}, status=404)
             
        await db.reject_submission(submission_id, user['id'], reason)
        
        # Отправить уведомление в Telegram сотруднику
        bot = get_bot_instance()
        if bot:
             try:
                 await bot.send_message(
                     chat_id=sub['submitted_by'],
                     text=f"❌ <b>ЗАЯВКА ОТКЛОНЕНА</b>\n\nВаша заявка #{submission_id} была отклонена.\n\n<b>Причина:</b> {reason}\n\nПроверьте данные и отправьте заново.",
                     parse_mode="HTML"
                 )
             except Exception as notify_err:
                 print(f"Failed to notify user about rejection: {notify_err}")
                 
        return safe_json_response({'success': True, 'message': 'Заявка отклонена'})
    except Exception as e:
        print(f"Ошибка отклонения заявки через Web UI: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def send_order_telegram_api(request):
    """API: Отправить сгенерированный список закупа в Telegram"""
    try:
        user = await get_current_user(request)
        if not user:
             return safe_json_response({'error': 'Unauthorized'}, status=403)
             
        data = await request.json()
        days = data.get('days')
        total_cost = data.get('total_cost')
        items = data.get('items', [])
        
        bot = get_bot_instance()
        if not bot:
             return safe_json_response({'error': 'Бот не инициализирован. Уведомление не отправлено.'}, status=500)
             
        # Формируем официальное сообщение для поставщика
        message_lines = [
            f"<b>Заявка на поставку (на {days} дней)</b>\n"
        ]
        
        for item in items:
            name = item.get('name')
            boxes = item.get('order_boxes')
            
            if boxes > 0:
                message_lines.append(f"- {name}: {boxes} уп.")
                
        message = "\n".join(message_lines)
        
        await bot.send_message(
            chat_id=user['id'],
            text=message,
            parse_mode="HTML"
        )
        
        return safe_json_response({'success': True, 'message': 'Список закупа успешно отправлен в ваш Telegram'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return safe_json_response({'error': str(e)}, status=500)

# ================================
# Shift Schedule API
# ================================

async def api_get_shifts(request):
    """API: Получить график смен"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        start_date = request.query.get('start')
        end_date = request.query.get('end')
        if not start_date or not end_date:
            return safe_json_response({'error': 'start and end dates required'}, status=400)
            
        shifts = await db.get_shifts(company_id, start_date, end_date)
        return safe_json_response({'success': True, 'shifts': shifts})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_assign_shift(request):
    """API: Назначить смену сотруднику"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        return safe_json_response({'error': 'Forbidden'}, status=403)
    company_id = await get_current_company(request)
    try:
        data = await request.json()
        user_ids = data.get('user_ids')
        if not user_ids and data.get('user_id'):
            user_ids = [data.get('user_id')]
            
        date = data.get('date')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        if not user_ids or not date:
            return safe_json_response({'error': 'user_ids and date required'}, status=400)
            
        for uid in user_ids:
            await db.assign_shift(company_id, uid, date, start_time, end_time)
            
        return safe_json_response({'success': True})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_delete_shift(request):
    """API: Удалить смену"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        return safe_json_response({'error': 'Forbidden'}, status=403)
    company_id = await get_current_company(request)
    try:
        shift_id = request.match_info.get('id')
        if not shift_id:
            return safe_json_response({'error': 'shift id required'}, status=400)
        
        success = await db.delete_shift(company_id, int(shift_id))
        return safe_json_response({'success': success})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def schedule_page(request):
    """Страница графика смен"""
    user = await get_current_user(request)
    company_id = await get_current_company(request)
    staff = await db.get_users_by_company(company_id)
    
    # stringify datetimes for tojson in template
    staff_json_ready = []
    for d in staff:
        d_copy = dict(d)
        if d_copy.get('created_at'): d_copy['created_at'] = d_copy['created_at'].isoformat()
        if d_copy.get('last_seen'): d_copy['last_seen'] = d_copy['last_seen'].isoformat()
        staff_json_ready.append(d_copy)
    company_details = await db.get_company_details(company_id)
    default_start = company_details.get('default_shift_start') if company_details else None
    default_end = company_details.get('default_shift_end') if company_details else None
        
    return aiohttp_jinja2.render_template('schedule.html', request, {
        'user': user, 
        'role': user['role'] if user else None,
        'staff': staff_json_ready,
        'default_shift_start': str(default_start)[:5] if default_start else '',
        'default_shift_end': str(default_end)[:5] if default_end else ''
    })


async def send_order_telegram_api(request):
    """API: Отправить сгенерированный список закупа в Telegram"""
    try:
        user = await get_current_user(request)
        if not user:
             return safe_json_response({'error': 'Unauthorized'}, status=403)
             
        data = await request.json()
        days = data.get('days')
        total_cost = data.get('total_cost')
        items = data.get('items', [])
        
        bot = get_bot_instance()
        if not bot:
             return safe_json_response({'error': 'Бот не инициализирован. Уведомление не отправлено.'}, status=500)
             
        # Fetch all box_weights once for efficiency
        product_ids = [item.get('product_id') for item in items if item.get('product_id')]
        products_info = {}
        if product_ids:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, box_weight, units_per_box FROM products WHERE id = ANY($1)", product_ids)
                for r in rows:
                    products_info[r['id']] = {'box_weight': r['box_weight'], 'units_per_box': r.get('units_per_box', 1)}

        # 1. Сохраняем в базу как "Ожидающий приход"
        try:
            company_id = await get_current_company(request)
            order_type = data.get('type', 'auto') 
            notes = f"Автоматический смарт план на {days} дней" if order_type == 'auto' else "Ручной заказ через Web"
            
            # Создаем заказ
            order_id = await db.create_pending_order(company_id, total_cost, notes)
            
            # Добавляем товары
            # В items у нас должен быть product_id и box_weight. Иначе пропускаем.
            for item in items:
                product_id = item.get('product_id')
                boxes = item.get('order_boxes', 0)
                
                if not product_id or boxes <= 0:
                    continue
                    
                cost = item.get('item_total', 0)
                
                # Fetch reliable box_weight from the database instead of trusting the frontend payload
                p_info = products_info.get(product_id, {})
                box_weight = float(p_info.get('box_weight', item.get('box_weight', 1.0)))
                
                # Если товар в штуках (unit == 'шт'), то вес это просто кол-во штук = boxes * units_per_box
                # Но так как мы не всегда знаем unit в этом объекте на 100%, 
                # мы полагаемся на логику: если weight_ordered был передан, берем его. 
                # Иначе считаем классический (коробки * вес коробки).
                weight_ordered = boxes * box_weight
                
                await db.add_item_to_order(order_id, product_id, boxes, weight_ordered, cost)
                
        except Exception as db_err:
            print(f"Ошибка сохранения ожидающего заказа в БД: {db_err}")
            # Мы не прерываем отправку в ТГ, если БД упала, но логируем.

        # 2. Формируем официальное сообщение для поставщика
        message_lines = [
            f"<b>Заявка на поставку ({notes})</b>\n"
        ]
        
        for item in items:
            name = item.get('name')
            boxes = item.get('order_boxes')
            
            if boxes > 0:
                message_lines.append(f"- {name}: {boxes} уп.")
                # Fetch Active Debts to append reminder
        company_id = await get_current_company(request) # Ensure company_id is available here
        debts = await db.get_active_debts(company_id)
        if debts:
            message_lines.append("\n\n⚠️ <b>Напоминание о долгах поставщика:</b>\n")
            message_lines.append("<i>Вы не довезли нам следующие товары с прошлых поставок:</i>\n")
            for d in debts:
                message_lines.append(f"• {d['name_russian']} ({d['name_internal']}): <b>{d['boxes']} кор.</b>\n")
            message_lines.append("Обязательно добавьте их к этому заказу!")

        message = "\n".join(message_lines)

        # Send via telegram
        bot = get_bot_instance()
        if not bot:
            return safe_json_response({'error': 'Бот не инициализирован (telegram_mode error)'}, status=500)
            
        admin_ids = await db.get_admins_for_company(company_id)
        if not admin_ids:
            return safe_json_response({'error': 'Нет администраторов для уведомления в текущей компании'}, status=400)
            
        success_count = 0
        for admin_id in admin_ids:
            try:
                await bot.send_message(chat_id=admin_id, text=message, parse_mode="HTML")
                success_count += 1
            except Exception as tg_err:
                print(f"Ошибка отправки заказа админу {admin_id}: {tg_err}")
                
        if success_count == 0:
            return safe_json_response({'error': 'Не удалось доставить список закупа в Telegram'}, status=500)
            
        return safe_json_response({'success': True, 'message': f'Список закупа успешно отправлен в Telegram ({success_count}/{len(admin_ids)} чел.)'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return safe_json_response({'error': str(e)}, status=500)


async def api_get_pending_orders(request):
    """API: Получить ожидающие заказы для Приемки"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        orders_list = await db.get_pending_orders(company_id)
        for order in orders_list:
            if 'created_at' in order and order['created_at']:
                order['created_at'] = order['created_at'].strftime('%Y-%m-%d %H:%M')
            items = await db.get_pending_order_items(order['id'])
            order['items'] = items
        return safe_json_response({'success': True, 'orders': orders_list})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_accept_pending_order(request):
    """API: Принять ожидающий заказ полностью"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    try:
        order_id = int(request.match_info.get('id'))
        await db.complete_order(order_id)
        return safe_json_response({'success': True})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_cancel_pending_order(request):
    """API: Отменить ожидающий заказ"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    try:
        order_id = int(request.match_info.get('id'))
        await db.cancel_order(order_id)
        return safe_json_response({'success': True})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_get_debts(request):
    """API: Получить активные долги поставщиков"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        debts = await db.get_active_debts(company_id)
        for d in debts:
            if 'created_at' in d and d['created_at']:
                d['created_at'] = d['created_at'].strftime('%Y-%m-%d %H:%M')
        return safe_json_response({'success': True, 'debts': debts})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_resolve_debt(request):
    """API: Закрыть долг (товар привезли)"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    try:
        debt_id = int(request.match_info.get('id'))
        await db.resolve_supplier_debt(debt_id)
        return safe_json_response({'success': True})
    except Exception as e:
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
    app.router.add_get('/submissions', submissions_page)
    app.router.add_get('/orders', orders_page)
    app.router.add_get('/history', history_page)
    app.router.add_get('/reports', reports_page)
    app.router.add_get('/supply', supply_page)
    app.router.add_get('/order_edit', order_edit)
    app.router.add_get('/schedule', schedule_page)
    app.router.add_get('/settings', settings_page)
    app.router.add_get('/staff', staff_page)
    app.router.add_get('/expired', expired_page)
    
    # API endpoints
    app.router.add_get('/api/auth/telegram', telegram_login)
    app.router.add_get('/api/user/me', get_current_user_api)
    app.router.add_get('/api/orders/generate', generate_order_api)
    app.router.add_get('/api/history/{product_id}', get_history_api)
    app.router.add_get('/api/reports/daily', get_daily_report_api)
    app.router.add_get('/api/reports/weekly', get_weekly_report_api)
    app.router.add_get('/api/reports/advanced', api_reports_advanced)
    app.router.add_post('/api/supply', save_supply)
    
    app.router.add_get('/api/pending_orders', api_get_pending_orders)
    app.router.add_post('/api/pending_orders/{id}/accept', api_accept_pending_order)
    app.router.add_post('/api/pending_orders/{id}/cancel', api_cancel_pending_order)
    app.router.add_get('/api/debts', api_get_debts)
    app.router.add_post('/api/debts/{id}/resolve', api_resolve_debt)

    # API Дашборд Заметки
    app.router.add_get('/api/dashboard/notes', api_get_dashboard_notes)
    app.router.add_post('/api/dashboard/notes', api_add_dashboard_note)
    app.router.add_put('/api/dashboard/notes/{id}', api_update_dashboard_note)
    app.router.add_delete('/api/dashboard/notes/{id}', api_delete_dashboard_note)
    
    app.router.add_get('/api/shifts', api_get_shifts)
    app.router.add_post('/api/shifts/assign', api_assign_shift)
    app.router.add_delete('/api/shifts/{id}', api_delete_shift)
    
    app.router.add_get('/api/products', get_products)
    app.router.add_post('/api/products/{id}/toggle', toggle_product_status_route)
    app.router.add_post('/api/stock', save_stock)
    app.router.add_get('/api/stock/latest', get_latest_stock)
    app.router.add_get('/api/stock/check', check_stock_exists)
    app.router.add_get('/api/stock/yesterday', get_yesterday_stock)
    app.router.add_get('/api/stock/{date}', get_stock_for_date)
    app.router.add_get('/api/supplies/today', get_today_supplies)

    app.router.add_get('/superadmin', superadmin_page)
    app.router.add_post('/api/superadmin/companies', api_create_company)
    app.router.add_post('/api/superadmin/companies/{id}/subscription', api_update_company_subscription)
    app.router.add_post('/api/superadmin/products', api_add_superadmin_product)
    app.router.add_delete('/api/superadmin/companies/{id}', api_delete_company)

    app.router.add_get('/staff', staff_page)
    app.router.add_post('/api/company/invite', api_invite_staff)
    app.router.add_post('/api/company/update_role', api_update_staff_role)
    app.router.add_post('/api/company/update_real_name', api_update_real_name)
    app.router.add_post('/api/company/remove_staff', api_remove_staff)
    app.router.add_post('/api/company/restore_staff', api_restore_staff)

    app.router.add_get('/settings', settings_page)
    app.router.add_get('/api/company/details', api_get_company_details)
    app.router.add_post('/api/company/settings', api_update_company_settings)
    app.router.add_post('/api/company/notes', api_update_company_notes)
    app.router.add_post('/api/company/broadcast', api_company_broadcast)
    app.router.add_get('/api/dashboard/metrics', api_get_dashboard_metrics)
    app.router.add_get('/api/dashboard/activity', api_get_dashboard_activity)

    app.router.add_get('/api/submission/{id}', get_submission_data)
    app.router.add_post('/api/submission/update', update_submission)
    app.router.add_get('/api/submissions', api_get_submissions)
    app.router.add_post('/api/submission/approve', api_approve_submission)
    app.router.add_post('/api/submission/reject', api_reject_submission)

    app.router.add_post('/api/draft_order', save_draft_order)
    app.router.add_get('/api/draft_order/{draft_key}', get_draft_order)
    app.router.add_post('/api/orders/send_telegram', send_order_telegram_api)

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
        samesite='None'
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
            
        # Копируем базовые товары от компании 1 (шаблона)
        try:
            inserted_products = await db.duplicate_company_products(source_company_id=1, target_company_id=company['id'])
            print(f"Скопировано {inserted_products} товаров для компании {company['id']}")
        except Exception as copy_err:
            print(f"Ошибка копирования товаров для новой компании: {copy_err}")
            
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
            'invite_url': invite_url,
            'products_copied': inserted_products if 'inserted_products' in locals() else 0
        })
    except Exception as e:
        print(f"Ошибка api_create_company: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_add_superadmin_product(request):
    """API: Добавить новый товар (Опционально глобально)"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin' or user.get('company_id') != 1:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    try:
        data = await request.json()
        name_chinese = data.get('name_chinese', '')
        name_russian = data.get('name_russian', '')
        name_internal = data.get('name_internal')
        
        # Convert strings to floats
        package_weight = float(data.get('package_weight', 0))
        units_per_box = int(data.get('units_per_box', 1))
        price_per_box = float(data.get('price_per_box', 0))
        unit = data.get('unit', 'кг')
        
        distribute_globally = data.get('distribute_globally', False)
        
        if not name_internal:
            return safe_json_response({'error': 'Внутреннее название обязательно'}, status=400)
            
        if distribute_globally:
            await db.add_product_globally(
                name_chinese=name_chinese,
                name_russian=name_russian,
                name_internal=name_internal,
                package_weight=package_weight,
                units_per_box=units_per_box,
                price_per_box=price_per_box,
                unit=unit
            )
        else:
            await db.add_product(
                company_id=1,
                name_chinese=name_chinese,
                name_russian=name_russian,
                name_internal=name_internal,
                package_weight=package_weight,
                units_per_box=units_per_box,
                price_per_box=price_per_box,
                unit=unit
            )
            
        return safe_json_response({'success': True})
    except Exception as e:
        print(f"Ошибка api_add_superadmin_product: {e}")
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
    archived_staff = await db.get_archived_users_by_company(company_id)
    
    context = {
        'page': 'staff',
        'staff': staff,
        'archived_staff': archived_staff,
        'user': user,
        'company_id': company_id
    }
    return aiohttp_jinja2.render_template('staff.html', request, context)

async def expired_page(request):
    """Страница блокировки для истекших подписок"""
    user = await get_current_user(request)
    if not user:
        raise web.HTTPFound('/login')
        
    company_id = await get_current_company(request)
    
    context = {
        'page': 'expired',
        'user': user,
        'company_id': company_id
    }
    return aiohttp_jinja2.render_template('expired.html', request, context)

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

async def api_update_real_name(request):
    """API: Обновить реальное имя (real_name) сотрудника"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'superadmin']:
        return safe_json_response({'error': 'Доступ запрещен. Только администратор может изменять имена.'}, status=403)
        
    company_id = await get_current_company(request)
    if not company_id:
        return safe_json_response({'error': 'Компания не найдена'}, status=404)
        
    try:
        data = await request.json()
        target_user_id = data.get('user_id')
        real_name = data.get('real_name', '').strip()
        
        if not target_user_id:
            return safe_json_response({'error': 'Отсутствует ID пользователя'}, status=400)
            
        await db.update_user_real_name(target_user_id, real_name)
        return safe_json_response({'success': True})
        
    except Exception as e:
        print(f"Ошибка api_update_real_name: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_remove_staff(request):
    """API: Удалить сотрудника (пометить как уволенного)"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'superadmin']:
        return safe_json_response({'error': 'Доступ запрещен. Только администратор может удалять сотрудников.'}, status=403)
        
    company_id = await get_current_company(request)
    if not company_id:
        return safe_json_response({'error': 'Компания не найдена'}, status=404)
        
    try:
        data = await request.json()
        target_user_id = data.get('user_id')
        
        if not target_user_id:
            return safe_json_response({'error': 'Отсутствует ID пользователя'}, status=400)
            
        if target_user_id == user['id']:
            return safe_json_response({'error': 'Вы не можете удалить сами себя'}, status=400)
            
        success = await db.remove_user(target_user_id, company_id)
        if success:
            return safe_json_response({'success': True})
        else:
            return safe_json_response({'error': 'Сотрудник не найден или не может быть удален'}, status=400)
            
    except Exception as e:
        print(f"Ошибка api_remove_staff: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_restore_staff(request):
    """API: Восстановить уволенного сотрудника"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'superadmin']:
        return safe_json_response({'error': 'Доступ запрещен. Только администратор может восстанавливать сотрудников.'}, status=403)
        
    company_id = await get_current_company(request)
    if not company_id:
        return safe_json_response({'error': 'Компания не найдена'}, status=404)
        
    try:
        data = await request.json()
        target_user_id = data.get('user_id')
        
        if not target_user_id:
            return safe_json_response({'error': 'Отсутствует ID пользователя'}, status=400)
            
        success = await db.restore_user(target_user_id, company_id)
        if success:
            return safe_json_response({'success': True})
        else:
            return safe_json_response({'error': 'Сотрудник не найден или не может быть восстановлен'}, status=400)
            
    except Exception as e:
        print(f"Ошибка api_restore_staff: {e}")
        return safe_json_response({'error': str(e)}, status=500)

# ==========================================
# COMPANY SETTINGS (SaaS)
# ==========================================

async def settings_page(request):
    """Страница настроек компании (только Admin)"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'superadmin']:
        raise web.HTTPFound('/login')
        
    company_id = await get_current_company(request)
    
    context = {
        'page': 'settings',
        'user': user,
        'company_id': company_id
    }
    return aiohttp_jinja2.render_template('settings.html', request, context)

async def api_get_company_details(request):
    """API: Получить данные компании для страницы настроек"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'superadmin']:
        return safe_json_response({'error': 'Доступ запрещен'}, status=403)
        
    company_id = await get_current_company(request)
    
    try:
        details = await db.get_company_details(company_id)
        if details:
            # Преобразуем datetime в строку, если нужно
            if 'subscription_ends_at' in details and details['subscription_ends_at']:
                details['subscription_ends_at'] = details['subscription_ends_at'].strftime('%Y-%m-%d %H:%M:%S')
            if 'created_at' in details and details['created_at']:
                details['created_at'] = details['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                
            return safe_json_response({'success': True, 'company': details})
        return safe_json_response({'error': 'Компания не найдена'}, status=404)
    except Exception as e:
        print(f"Ошибка api_get_company_details: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_update_company_settings(request):
    """API: Обновить основные настройки компании"""
    user = await get_current_user(request)
    if not user or user.get('role') != 'admin':
        return safe_json_response({'error': 'Только владелец (Админ) может менять настройки'}, status=403)
        
    company_id = await get_current_company(request)
    
    try:
        data = await request.json()
        new_name = data.get('name')
        default_shift_start = data.get('default_shift_start')
        default_shift_end = data.get('default_shift_end')
        
        if not new_name or not new_name.strip():
            return safe_json_response({'error': 'Название не может быть пустым'}, status=400)
            
        success = await db.update_company_details(company_id, new_name.strip(), default_shift_start, default_shift_end)
        
        if success:
            return safe_json_response({'success': True, 'message': 'Настройки успешно сохранены'})
        else:
            return safe_json_response({'error': 'Ошибка при сохранении'}, status=500)
            
    except Exception as e:
        print(f"Ошибка api_update_company_settings: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_get_dashboard_metrics(request):
    """API: Получить метрики для дашборда (Stock Value, Pending Orders, Next Purchase)"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    
    try:
        latest_stock = await db.get_latest_stock(company_id)
        stock_value = 0.0
        next_purchase_days = None
        
        for item in latest_stock:
            price = item.get('price_per_box')
            if price is None: price = 0
            
            if item.get('unit') == 'шт':
                divisor = item.get('units_per_box')
                if not divisor: divisor = 1
                qty = item.get('quantity')
                if qty is None: qty = 0
                stock_value += (qty / divisor) * price
            else:
                divisor = item.get('box_weight')
                if not divisor: divisor = 1
                weight = item.get('weight')
                if weight is None: weight = 0
                stock_value += (weight / divisor) * price
            
            
            days_rem = item.get('total_days_remaining', item.get('days_remaining'))
            if isinstance(days_rem, (int, float)) and days_rem >= 0:
                if next_purchase_days is None or days_rem < next_purchase_days:
                    next_purchase_days = days_rem

        pending_orders = await db.get_pending_orders(company_id)
        pending_value = sum(o.get('total_cost', 0) for o in pending_orders if o.get('status') == 'pending')

        details = await db.get_company_details(company_id)
        notes = details.get('notes', '') if details else ''
        
        dashboard_notes = await db.get_dashboard_notes(company_id)
        for dn in dashboard_notes:
            if 'created_at' in dn and dn['created_at']:
                dn['created_at'] = dn['created_at'].strftime('%Y-%m-%d %H:%M')

        return safe_json_response({
            'success': True,
            'stock_value': stock_value,
            'pending_value': pending_value,
            'next_purchase_days': next_purchase_days,
            'notes': notes,
            'dashboard_notes': dashboard_notes
        })
    except Exception as e:
        print(f"Ошибка api_get_dashboard_metrics: {e}")
        return safe_json_response({'error': str(e)}, status=500)

async def api_get_dashboard_activity(request):
    """API: Получить последние действия для дашборда"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        limit = int(request.query.get('limit', 5))
        activity = await db.get_recent_activity(company_id, limit)
        return safe_json_response({'success': True, 'activity': activity})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_update_company_notes(request):
    """API: Обновить личные заметки франчайзи на Дашборде"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        return safe_json_response({'error': 'Forbidden'}, status=403)
    company_id = await get_current_company(request)
    try:
        data = await request.json()
        await db.update_company_notes(company_id, data.get('notes', ''))
        return safe_json_response({'success': True})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

# --- Новые API для раздельных заметок на дашборде ---
async def api_get_dashboard_notes(request):
    """API: Получить все заметки дашборда"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        notes = await db.get_dashboard_notes(company_id)
        for n in notes:
            if 'created_at' in n and n['created_at']:
                n['created_at'] = n['created_at'].strftime('%Y-%m-%d %H:%M')
        return safe_json_response({'success': True, 'notes': notes})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_add_dashboard_note(request):
    """API: Добавить заметку на дашборд"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        data = await request.json()
        content = data.get('content')
        if not content:
            return safe_json_response({'error': 'Empty content'}, status=400)
        note_id = await db.add_dashboard_note(company_id, content)
        return safe_json_response({'success': True, 'id': note_id})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_update_dashboard_note(request):
    """API: Редактировать заметку на дашборде"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        note_id = int(request.match_info.get('id'))
        data = await request.json()
        content = data.get('content')
        if not content:
            return safe_json_response({'error': 'Empty content'}, status=400)
        success = await db.update_dashboard_note(note_id, company_id, content)
        return safe_json_response({'success': success})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_delete_dashboard_note(request):
    """API: Удалить заметку на дашборде"""
    user = await get_current_user(request)
    if not user: return safe_json_response({'error': 'Unauthorized'}, status=401)
    company_id = await get_current_company(request)
    try:
        note_id = int(request.match_info.get('id'))
        success = await db.delete_dashboard_note(note_id, company_id)
        return safe_json_response({'success': success})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)

async def api_company_broadcast(request):
    """API: Отправить объявление всем сотрудникам франшизы в Telegram"""
    user = await get_current_user(request)
    if not user or user.get('role') not in ['admin', 'manager']:
        return safe_json_response({'error': 'Forbidden'}, status=403)
    company_id = await get_current_company(request)
    try:
        data = await request.json()
        message = data.get('message')
        if not message:
            return safe_json_response({'error': 'Empty message'}, status=400)
            
        users = await db.get_users_by_company(company_id)
        bot = get_bot_instance()
        count = 0
        if bot:
            for u in users:
                if u.get('is_active'):
                    try:
                        await bot.send_message(
                            chat_id=u['id'], 
                            text=f"📢 <b>Объявление от администратора</b>\n\n{message}"
                        )
                        count += 1
                    except Exception:
                        pass
        return safe_json_response({'success': True, 'sent_count': count})
    except Exception as e:
        return safe_json_response({'error': str(e)}, status=500)
