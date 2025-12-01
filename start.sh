#!/bin/bash
# Запуск обоих сервисов: бот и веб-сервер

# Запускаем веб-сервер в фоне
python3 webapp/server.py &

# Запускаем бота
python3 main.py
