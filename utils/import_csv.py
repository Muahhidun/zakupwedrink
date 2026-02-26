"""
Импорт данных из CSV таблицы WeDrink
"""
import csv
import re
from typing import Dict, List


def parse_weight(value: str) -> float:
    """Парсинг веса из строки (например '1,2 кг' -> 1.2)"""
    if not value or value == '':
        return 0.0
    # Убираем все кроме цифр, точек и запятых
    cleaned = re.sub(r'[^\d.,]', '', str(value))
    cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_number(value: str) -> float:
    """Парсинг числа из строки"""
    if not value or value == '' or value == '-':
        return 0.0
    # Убираем все пробелы, неразрывные пробелы и заменяем запятую на точку
    cleaned = str(value).strip()
    cleaned = cleaned.replace(' ', '').replace('\xa0', '').replace('\u202f', '')
    # Для чисел с запятой как разделителем тысяч (33,600) или как десятичной запятой
    # Если есть и точка и запятая, запятая - разделитель тысяч
    if '.' in cleaned and ',' in cleaned:
        cleaned = cleaned.replace(',', '')
    else:
        # Если только запятая, она может быть десятичным разделителем
        cleaned = cleaned.replace(',', '.')

    # Убираем все нецифровые символы кроме точки и минуса
    result = ''
    for char in cleaned:
        if char.isdigit() or char in '.-':
            result += char

    try:
        return float(result) if result and result not in ('-', '.', '-.') else 0.0
    except ValueError:
        return 0.0


async def import_products_from_csv(csv_path: str, db, company_id: int = 1) -> int:
    """
    Импорт товаров из CSV файла
    Возвращает количество импортированных товаров
    """
    imported = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)

        print(f"Всего строк в CSV: {len(rows)}")

        # Пропускаем первые 2 строки (заголовки)
        for i, row in enumerate(rows[2:], start=3):
            if len(row) < 7:
                continue

            name_chinese = row[0].strip() if len(row) > 0 and row[0] else ""
            name_russian = row[1].strip() if len(row) > 1 and row[1] else ""
            name_internal = row[2].strip() if len(row) > 2 and row[2] else ""
            package_info = row[3].strip() if len(row) > 3 and row[3] else ""
            box_weight_str = row[4].strip() if len(row) > 4 and row[4] else "0"
            price_str = row[5].strip() if len(row) > 5 and row[5] else "0"

            # Пропускаем пустые строки и заголовки
            if not name_internal or name_internal == "Наименовани наше" or name_internal == "":
                continue

            # Парсим информацию о фасовке
            # Формат: "1,2 кг * 12 бан./кор."
            package_weight = 0.0
            units_per_box = 0
            unit = "кг"

            if package_info:
                # Извлекаем вес упаковки
                weight_match = re.search(r'([\d,\.]+)\s*(кг|л|г|мл|шт)', package_info)
                if weight_match:
                    package_weight = parse_weight(weight_match.group(1))
                    unit = weight_match.group(2)

                # Извлекаем количество в коробке
                units_match = re.search(r'\*\s*(\d+)', package_info)
                if units_match:
                    units_per_box = int(units_match.group(1))

            # Парсим цену
            price_per_box = parse_number(price_str)

            # Debug
            if i <= 5:  # Показываем первые несколько строк для отладки
                print(f"\nСтрока {i}:")
                print(f"  Название: {name_internal}")
                print(f"  Фасовка: {package_info}")
                print(f"  Вес упаковки: {package_weight} {unit}")
                print(f"  Штук в коробке: {units_per_box}")
                print(f"  Цена: {price_per_box}")

            # Пропускаем товары без ключевой информации
            if package_weight == 0 or units_per_box == 0:
                print(f"⚠️  Пропущено: {name_internal} (нет данных о фасовке)")
                continue

            if price_per_box == 0:
                print(f"⚠️  Пропущено: {name_internal} (нет цены)")
                continue

            try:
                await db.add_product(
                    company_id=company_id,
                    name_chinese=name_chinese,
                    name_russian=name_russian,
                    name_internal=name_internal,
                    package_weight=package_weight,
                    units_per_box=units_per_box,
                    price_per_box=price_per_box,
                    unit=unit
                )
                imported += 1
                print(f"✅ Импортирован: {name_internal}")
            except Exception as e:
                print(f"❌ Ошибка при импорте {name_internal}: {e}")

    return imported


async def import_stock_from_csv(csv_path: str, db, date_columns: Dict[str, int], company_id: int = 1) -> int:
    """
    Импорт остатков из CSV файла
    date_columns: словарь {дата: номер_колонки_с_весом}
    Например: {"2024-11-17": 8, "2024-11-19": 10, ...}
    """
    imported = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)

        for row in rows[2:]:
            if len(row) < 7:
                continue

            name_internal = row[2].strip() if row[2] else ""

            if not name_internal or name_internal == "Наименовани наше":
                continue

            # Получаем товар из БД
            product = await db.get_product_by_name(company_id=company_id, name=name_internal)
            if not product:
                continue

            # Импортируем остатки по датам
            for date, col_index in date_columns.items():
                if col_index < len(row):
                    weight = parse_number(row[col_index])
                    if weight > 0:
                        # Рассчитываем количество упаковок
                        quantity = weight / product['package_weight'] if product['package_weight'] > 0 else 0

                        try:
                            await db.add_stock(
                                company_id=company_id,
                                product_id=product['id'],
                                date=date,
                                quantity=quantity,
                                weight=weight
                            )
                            imported += 1
                        except Exception as e:
                            print(f"❌ Ошибка при импорте остатка {name_internal} на {date}: {e}")

    return imported
