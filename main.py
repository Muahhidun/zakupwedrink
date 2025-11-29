"""
WeDrink Stock Manager Bot
Telegram бот для учета закупок и складских остатков
"""
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from database import Database
from handlers import start, stock, orders, reports, supply, products

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
DATABASE_PATH = os.getenv('DATABASE_PATH', 'wedrink.db')


async def main():
    """Основная функция запуска бота"""
    # Инициализация базы данных
    db = Database(DATABASE_PATH)
    await db.init_db()

    # Инициализация бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Middleware для передачи db во все handlers
    @dp.update.outer_middleware()
    async def db_middleware(handler, event, data):
        data['db'] = db
        return await handler(event, data)

    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(stock.router)
    dp.include_router(supply.router)
    dp.include_router(orders.router)
    dp.include_router(reports.router)
    dp.include_router(products.router)

    logger.info("🤖 Бот запущен!")

    # Запуск polling
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")
