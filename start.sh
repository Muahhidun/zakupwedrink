#!/bin/bash
set -e

echo "🚀 Starting WeDrink services..."

# Проверяем переменные окружения
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL not set!"
    exit 1
fi

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ ERROR: BOT_TOKEN not set!"
    exit 1
fi

if [ -z "$PORT" ]; then
    echo "⚠️  PORT not set, using default 5000"
    export PORT=5000
fi

echo "📱 Starting web server on port $PORT..."
python3 webapp/server.py 2>&1 | sed 's/^/[WEB] /' &
WEB_PID=$!

# Даем веб-серверу время на старт
sleep 5

# Проверяем, что веб-сервер запустился
if ! kill -0 $WEB_PID 2>/dev/null; then
    echo "❌ Web server failed to start! Check logs above."
    exit 1
fi

echo "✅ Web server started (PID: $WEB_PID)"
echo "🤖 Starting Telegram bot..."

# Запускаем бота (он будет держать процесс alive)
python3 main.py 2>&1 | sed 's/^/[BOT] /'
