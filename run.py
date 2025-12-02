#!/usr/bin/env python3
"""
Запуск веб-сервера и бота одновременно
"""
import os
import sys
import subprocess
import time
import signal

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


def start_web_server():
    """Запустить веб-сервер в отдельном процессе"""
    print(f"📱 Starting web server on port {os.getenv('PORT')}...")

    try:
        # Запускаем веб-сервер БЕЗ захвата вывода - пусть пишет в stdout напрямую
        proc = subprocess.Popen(
            [sys.executable, 'webapp/server.py'],
            # Не захватываем stdout/stderr - пусть веб-сервер пишет напрямую
        )

        # Даем время на старт
        time.sleep(3)

        # Проверяем, что процесс жив
        if proc.poll() is not None:
            # Процесс завершился с ошибкой
            print(f"❌ Web server failed to start! Exit code: {proc.poll()}")
            sys.exit(1)

        print(f"✅ Web server started (PID: {proc.pid})")
        return proc

    except Exception as e:
        print(f"❌ Failed to start web server: {e}")
        sys.exit(1)


def start_bot():
    """Запустить бота в основном процессе"""
    print("🤖 Starting Telegram bot...")

    try:
        # Запускаем бота, заменяя текущий процесс
        os.execv(sys.executable, [sys.executable, 'main.py'])
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        sys.exit(1)


def main():
    print("🚀 Starting WeDrink services...")

    # Проверяем переменные окружения
    check_env()

    # Запускаем веб-сервер
    web_proc = start_web_server()

    # Настраиваем обработку сигналов для корректного завершения
    def signal_handler(sig, frame):
        print("\n👋 Shutting down...")
        if web_proc:
            web_proc.terminate()
            web_proc.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Запускаем бота (это заменит текущий процесс)
    start_bot()


if __name__ == '__main__':
    main()
