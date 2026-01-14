"""
Команда для запуска миграции через бота (только для первого запуска)
"""
import asyncio
import sys
import os
from migrate_users_roles import migrate

if __name__ == '__main__':
    print("🚀 Запуск миграции...")
    try:
        asyncio.run(migrate())
        print("\n✅ Миграция завершена успешно!")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)
