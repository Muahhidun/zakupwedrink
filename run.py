#!/usr/bin/env python3
"""
Запуск бота и веб-сервера (веб-сервер встроен в main.py)
"""
import os
import sys


def check_env():
    """Проверка переменных окружения"""
    required = ['BOT_TOKEN', 'DATABASE_URL']
    missing = [var for var in required if not os.getenv(var)]

    if missing:
        print(f"❌ ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    if not os.getenv('PORT'):
        print("⚠️  PORT not set, using default 5000")
        os.environ['PORT'] = '5000'

    print("✅ Environment variables OK")


def main():
    print("🚀 Starting WeDrink services...")
    check_env()

    # Запускаем main.py (бот + встроенный веб-сервер в одном процессе)
    os.execv(sys.executable, [sys.executable, 'main.py'])


if __name__ == '__main__':
    main()
