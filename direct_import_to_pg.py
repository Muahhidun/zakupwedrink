"""
Прямой импорт товаров и остатков в PostgreSQL
"""
import asyncio
import os
import csv
from database_pg import DatabasePG
from dotenv import load_dotenv

load_dotenv()


async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()

    print("📦 Импорт товаров из CSV...")

    # Импортируем товары
    count = 0
    with open('data.csv', 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)

        # Пропускаем первые 2 строки (заголовки)
        for i, row in enumerate(rows[2:], start=3):
            try:
                if len(row) < 6:
                    continue

                name_chinese = row[1].strip() if len(row) > 1 else ""
                name_russian = row[2].strip() if len(row) > 2 else ""
                fasovka = row[3].strip() if len(row) > 3 else ""
                weight_box_str = row[4].strip() if len(row) > 4 else ""
                price_str = row[5].strip() if len(row) > 5 else ""

                if not name_russian or not weight_box_str or not price_str:
                    continue

                # Парсим фасовку: "1,2 кг * 12 бан./кор." или "400 шт./кор."
                import re
                fasovka_match = re.search(r'([\d,\.]+)\s*(\w+)\s*\*\s*(\d+)', fasovka)

                if not fasovka_match:
                    # Пробуем формат "400 шт./кор."
                    fasovka_match = re.search(r'(\d+)\s*шт\./кор\.', fasovka)
                    if fasovka_match:
                        units_per_box = int(fasovka_match.group(1))
                        package_weight = units_per_box  # Для штук вес = количество
                        unit = "шт"
                    else:
                        print(f"⚠️  Строка {i}: Не удалось распарсить фасовку: {fasovka}")
                        continue
                else:
                    package_weight = float(fasovka_match.group(1).replace(',', '.'))
                    unit = fasovka_match.group(2)
                    units_per_box = int(fasovka_match.group(3))

                # Очищаем цену от пробелов (включая неразрывные пробелы \xa0)
                price = float(price_str.replace(',', '.').replace(' ', '').replace('\xa0', ''))

                await db.add_product(
                    name_chinese=name_chinese,
                    name_russian=name_russian,
                    name_internal=name_russian,
                    package_weight=package_weight,
                    units_per_box=units_per_box,
                    price_per_box=price,
                    unit=unit
                )
                print(f"✅ {name_russian}")
                count += 1
            except Exception as e:
                print(f"⚠️  Строка {i}: {e}")

    print(f"\n📊 Импортировано товаров: {count}")

    await db.close()


if __name__ == '__main__':
    asyncio.run(main())
