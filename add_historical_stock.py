#!/usr/bin/env python3
"""
Скрипт для добавления исторических данных остатков

Использование:
1. Отредактируйте STOCK_DATA ниже - укажите свои данные
2. Запустите: python3 add_historical_stock.py
"""
import asyncio
import os
from datetime import datetime
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# ВАШИ ДАННЫЕ - РЕДАКТИРУЙТЕ ЗДЕСЬ
# ============================================================================

STOCK_DATA = [
    # Формат: ("ГГГГ-ММ-ДД", [
    #     ("Название товара точно как в базе", количество_упаковок),
    # ])

    ("2024-11-25", [
        ("Виноград консервированный 850 г", 5),
        ("Латте 1 кг", 10),
        ("Манговое пюре 1,2 кг", 3),
        # Добавьте свои товары здесь...
    ]),

    ("2024-11-26", [
        ("Виноград консервированный 850 г", 4),
        ("Латте 1 кг", 8),
        # Добавьте свои товары здесь...
    ]),

    # Добавьте больше дат по необходимости...
]

# ============================================================================


async def main():
    """Импорт исторических данных"""

    # Подключаемся к базе данных
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ ERROR: DATABASE_URL не установлен в .env")
        return

    db = DatabasePG(database_url)
    await db.init_db()

    print("✅ Подключено к PostgreSQL")

    # Получаем все товары для сопоставления названий
    products = await db.get_all_products()
    print(f"📦 Найдено товаров в БД: {len(products)}")

    # Создаем словарь для быстрого поиска по названию
    product_map = {}
    for product in products:
        # Используем name_internal для поиска
        key = product['name_internal'].lower().strip()
        product_map[key] = product

    print("\n🔄 Начинаю импорт исторических данных...\n")

    total_imported = 0
    total_skipped = 0

    for date_str, items in STOCK_DATA:
        # Конвертируем строку в date объект
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            print(f"❌ Неверный формат даты: {date_str} (используйте ГГГГ-ММ-ДД)")
            continue

        print(f"📅 {date_str}")

        for product_name, quantity in items:
            # Ищем товар в базе
            key = product_name.lower().strip()
            product = product_map.get(key)

            if not product:
                print(f"   ⚠️  Товар не найден: '{product_name}'")
                total_skipped += 1
                continue

            # Рассчитываем вес
            weight = quantity * product['package_weight']

            # Добавляем в базу
            try:
                await db.add_stock(
                    product_id=product['id'],
                    date=date_obj,
                    quantity=quantity,
                    weight=weight
                )
                print(f"   ✅ {product_name}: {quantity} уп. ({weight:.1f} {product['unit']})")
                total_imported += 1
            except Exception as e:
                print(f"   ❌ Ошибка сохранения '{product_name}': {e}")
                total_skipped += 1

        print()  # Пустая строка между датами

    await db.close()

    print("=" * 60)
    print(f"✅ Импорт завершен!")
    print(f"   Добавлено записей: {total_imported}")
    if total_skipped > 0:
        print(f"   Пропущено: {total_skipped}")
    print("=" * 60)
    print("\n💡 Совет: Запустите /verify_data в боте чтобы проверить данные")


if __name__ == '__main__':
    asyncio.run(main())
