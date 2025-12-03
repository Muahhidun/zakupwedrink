"""
База данных PostgreSQL для учета складских остатков WeDrink
"""
import asyncpg
import os
from typing import List, Dict, Optional
from datetime import datetime


class DatabasePG:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None

    async def init_db(self):
        """Инициализация пула соединений и создание таблиц"""
        # Создаем пул соединений
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)

        async with self.pool.acquire() as conn:
            # Таблица товаров
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name_chinese TEXT,
                    name_russian TEXT,
                    name_internal TEXT NOT NULL UNIQUE,
                    package_weight REAL NOT NULL,
                    units_per_box INTEGER NOT NULL,
                    box_weight REAL NOT NULL,
                    price_per_box REAL NOT NULL,
                    unit TEXT DEFAULT 'кг',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица остатков на складе
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    date DATE NOT NULL,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(product_id, date)
                )
            """)

            # Таблица поставок
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS supplies (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    date DATE NOT NULL,
                    boxes INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    cost REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        print("✅ PostgreSQL база данных инициализирована")

    async def close(self):
        """Закрыть пул соединений"""
        if self.pool:
            await self.pool.close()

    async def add_product(self, name_chinese: str, name_russian: str, name_internal: str,
                         package_weight: float, units_per_box: int, price_per_box: float,
                         unit: str = "кг") -> int:
        """Добавить товар"""
        box_weight = package_weight * units_per_box
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                INSERT INTO products
                (name_chinese, name_russian, name_internal, package_weight,
                 units_per_box, box_weight, price_per_box, unit)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
            """, name_chinese, name_russian, name_internal, package_weight,
                units_per_box, box_weight, price_per_box, unit)
            return result

    async def get_all_products(self) -> List[Dict]:
        """Получить все товары"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM products ORDER BY name_internal")
            return [dict(row) for row in rows]

    async def get_product_by_name(self, name_internal: str) -> Optional[Dict]:
        """Получить товар по внутреннему названию"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE name_internal = $1", name_internal
            )
            return dict(row) if row else None

    async def add_stock(self, product_id: int, date, quantity: float, weight: float):
        """Добавить/обновить остаток на дату (date может быть str или date)"""
        # Конвертируем строку в date объект если нужно
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO stock (product_id, date, quantity, weight)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT(product_id, date)
                DO UPDATE SET quantity=EXCLUDED.quantity, weight=EXCLUDED.weight
            """, product_id, date, quantity, weight)

    async def add_supply(self, product_id: int, date, boxes: int,
                        weight: float, cost: float):
        """Добавить поставку (date может быть str или date)"""
        # Конвертируем строку в date объект если нужно
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO supplies (product_id, date, boxes, weight, cost)
                VALUES ($1, $2, $3, $4, $5)
            """, product_id, date, boxes, weight, cost)

    async def get_stock_by_date(self, date) -> List[Dict]:
        """Получить остатки на дату (date может быть str или date)"""
        # Конвертируем строку в date объект если нужно
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.*, p.name_internal, p.name_russian, p.package_weight,
                       p.units_per_box, p.box_weight, p.price_per_box
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = $1
                ORDER BY p.name_internal
            """, date)
            return [dict(row) for row in rows]

    async def get_latest_stock(self) -> List[Dict]:
        """Получить последние остатки по всем товарам"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.*, p.name_internal, p.name_russian, p.package_weight,
                       p.units_per_box, p.box_weight, p.price_per_box, p.unit
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = (
                    SELECT MAX(date) FROM stock WHERE product_id = s.product_id
                )
                ORDER BY p.name_internal
            """)
            return [dict(row) for row in rows]

    async def has_stock_for_date(self, date) -> bool:
        """Проверить наличие остатков за конкретную дату"""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM stock WHERE date = $1
            """, date)
            return count > 0

    async def get_stock_history(self, product_id: int, days: int = 7) -> List[Dict]:
        """Получить историю остатков товара за последние N дней"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM stock
                WHERE product_id = $1
                ORDER BY date DESC
                LIMIT $2
            """, product_id, days)
            return [dict(row) for row in rows]

    async def calculate_consumption(self, start_date, end_date) -> List[Dict]:
        """Расчет расхода между двумя датами (даты могут быть str или date)"""
        # Конвертируем строки в date объекты для PostgreSQL если нужно
        from datetime import datetime, date

        if isinstance(start_date, str):
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        elif isinstance(start_date, date):
            start_date_obj = start_date
        else:
            raise ValueError(f"start_date должен быть str или date, получен {type(start_date)}")

        if isinstance(end_date, str):
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        elif isinstance(end_date, date):
            end_date_obj = end_date
        else:
            raise ValueError(f"end_date должен быть str или date, получен {type(end_date)}")

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    p.id,
                    p.name_internal,
                    p.name_russian,
                    p.price_per_box,
                    p.box_weight,
                    s1.weight as weight_start,
                    s2.weight as weight_end,
                    (s1.weight - s2.weight) as consumed_weight,
                    ((s1.weight - s2.weight) / p.box_weight * p.price_per_box) as cost
                FROM products p
                LEFT JOIN stock s1 ON p.id = s1.product_id AND s1.date = $1
                LEFT JOIN stock s2 ON p.id = s2.product_id AND s2.date = $2
                WHERE s1.weight IS NOT NULL AND s2.weight IS NOT NULL
                ORDER BY cost DESC
            """, start_date_obj, end_date_obj)
            return [dict(row) for row in rows]

    async def calculate_consumption_period(self, start_date, end_date) -> List[Dict]:
        """
        Расчет расхода за период (работает даже с пропущенными датами)
        Использует самую раннюю и самую позднюю дату с данными в периоде
        """
        from datetime import datetime, date

        # Конвертируем в date объекты
        if isinstance(start_date, str):
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        elif isinstance(start_date, date):
            start_date_obj = start_date
        else:
            raise ValueError(f"start_date должен быть str или date")

        if isinstance(end_date, str):
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        elif isinstance(end_date, date):
            end_date_obj = end_date
        else:
            raise ValueError(f"end_date должен быть str или date")

        # Находим самую раннюю и самую позднюю дату с данными в периоде
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow("""
                SELECT
                    MIN(date) as earliest_date,
                    MAX(date) as latest_date
                FROM stock
                WHERE date >= $1 AND date <= $2
            """, start_date_obj, end_date_obj)

            if not result or not result['earliest_date'] or not result['latest_date']:
                return []

            earliest = result['earliest_date']
            latest = result['latest_date']

            # Если одна и та же дата - нет расхода
            if earliest == latest:
                return []

            # Рассчитываем расход между earliest и latest
            rows = await conn.fetch("""
                SELECT
                    p.id,
                    p.name_internal,
                    p.name_russian,
                    p.price_per_box,
                    p.box_weight,
                    p.unit,
                    s1.weight as weight_start,
                    s2.weight as weight_end,
                    (s1.weight - s2.weight) as consumed_weight,
                    ((s1.weight - s2.weight) / p.box_weight * p.price_per_box) as cost
                FROM products p
                LEFT JOIN stock s1 ON p.id = s1.product_id AND s1.date = $1
                LEFT JOIN stock s2 ON p.id = s2.product_id AND s2.date = $2
                WHERE s1.weight IS NOT NULL AND s2.weight IS NOT NULL
                  AND p.unit != 'шт'
                ORDER BY cost DESC
            """, earliest, latest)

            return [dict(row) for row in rows]

    async def get_stock_dates_summary(self) -> List[Dict]:
        """Получить сводку по датам с остатками"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    date,
                    COUNT(*) as product_count,
                    SUM(CASE WHEN p.unit != 'шт' THEN s.weight ELSE 0 END) as total_weight
                FROM stock s
                JOIN products p ON s.product_id = p.id
                GROUP BY date
                ORDER BY date DESC
            """)
            return [dict(row) for row in rows]

    async def get_latest_stock_date(self):
        """Получить дату последних остатков"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MAX(date) FROM stock")

    async def get_total_stock_records(self) -> int:
        """Получить общее количество записей об остатках"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM stock")

    async def get_supply_history(self, product_id: int, days: int = 14) -> List[Dict]:
        """Получить историю поставок товара за последние N дней"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM supplies
                WHERE product_id = $1
                  AND date >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY date DESC
            """ % days, product_id)
            return [dict(row) for row in rows]
