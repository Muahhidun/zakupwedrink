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

echo "🤖 Starting bot + web server on port $PORT..."
exec python3 main.py
