"""
WeDrink Stock Manager Bot
Telegram бот для учета закупок и складских остатков
"""
import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from database import Database as SQLiteDB
from database_pg import DatabasePG
from handlers import start, stock, orders, reports, supply, products, history, migrate, average_consumption, fix_cones, delete_duplicate
from scheduler import setup_scheduler
from webapp.server import create_app

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')  # PostgreSQL URL (на Railway)
DATABASE_PATH = os.getenv('DATABASE_PATH', 'wedrink.db')  # SQLite (локально)


async def main():
    """Основная функция запуска бота"""
    # Инициализация базы данных (автовыбор: PostgreSQL на Railway, SQLite локально)
    if DATABASE_URL:
        logger.info("🐘 Используется PostgreSQL")
        db = DatabasePG(DATABASE_URL)
    else:
        logger.info("📁 Используется SQLite")
        db = SQLiteDB(DATABASE_PATH)

    await db.init_db()

    # Проверка и автоматический импорт данных если БД пустая
    products_list = await db.get_all_products()
    if not products_list:
        logger.info("📦 БД пустая, запускаю автоматический импорт...")
        try:
            from utils.import_csv import import_products_from_csv, import_stock_from_csv

            csv_path = os.path.join(os.path.dirname(__file__), "data.csv")

            if os.path.exists(csv_path):
                logger.info("📦 Импорт товаров...")
                imported_products = await import_products_from_csv(csv_path, db)
                logger.info(f"✅ Импортировано товаров: {imported_products}")

                logger.info("📊 Импорт остатков...")
                date_columns = {
                    "2024-11-17": 8,
                    "2024-11-19": 10,
                    "2024-11-20": 12,
                    "2024-11-22": 14,
                    "2024-11-23": 16,
                    "2024-11-28": 18,
                }
                imported_stock = await import_stock_from_csv(csv_path, db, date_columns)
                logger.info(f"✅ Импортировано записей остатков: {imported_stock}")
            else:
                logger.warning(f"❌ CSV файл не найден: {csv_path}")
        except Exception as e:
            logger.error(f"❌ Ошибка импорта: {e}")

    # Инициализация бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Устанавливаем bot instance для webapp уведомлений
    from webapp.server import set_bot_instance
    set_bot_instance(bot)

    # Запуск встроенного веб-сервера (в том же asyncio loop, что и бот)
    web_app = create_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.getenv('PORT', 5000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Веб-сервер запущен на порту {port}")

    # Добавляем storage для FSM (для сохранения состояний заказов)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Middleware для передачи db во все handlers
    @dp.update.outer_middleware()
    async def db_middleware(handler, event, data):
        data['db'] = db
        return await handler(event, data)

    # Middleware для проверки ролей
    from middleware.auth import RoleMiddleware
    dp.message.middleware(RoleMiddleware())
    dp.callback_query.middleware(RoleMiddleware())

    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(stock.router)
    dp.include_router(supply.router)
    dp.include_router(orders.router)
    dp.include_router(reports.router)
    dp.include_router(products.router)
    dp.include_router(history.router)
    dp.include_router(migrate.router)
    dp.include_router(average_consumption.router)
    dp.include_router(fix_cones.router)
    dp.include_router(delete_duplicate.router)

    # Новые роутеры для системы ролей и модерации
    from handlers import moderation, users
    dp.include_router(moderation.router)
    dp.include_router(users.router)

    # Настройка и запуск планировщика задач
    scheduler = setup_scheduler(bot)
    scheduler.start()

    logger.info("🤖 Бот запущен!")

    # Запуск polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await runner.cleanup()
        scheduler.shutdown()
        if hasattr(db, 'close'):
            await db.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
