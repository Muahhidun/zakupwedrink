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

    async def add_stock(self, product_id: int, date: str, quantity: float, weight: float):
        """Добавить/обновить остаток на дату"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO stock (product_id, date, quantity, weight)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT(product_id, date)
                DO UPDATE SET quantity=EXCLUDED.quantity, weight=EXCLUDED.weight
            """, product_id, date, quantity, weight)

    async def add_supply(self, product_id: int, date: str, boxes: int,
                        weight: float, cost: float):
        """Добавить поставку"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO supplies (product_id, date, boxes, weight, cost)
                VALUES ($1, $2, $3, $4, $5)
            """, product_id, date, boxes, weight, cost)

    async def get_stock_by_date(self, date: str) -> List[Dict]:
        """Получить остатки на дату"""
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
                       p.units_per_box, p.box_weight, p.price_per_box
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = (
                    SELECT MAX(date) FROM stock WHERE product_id = s.product_id
                )
                ORDER BY p.name_internal
            """)
            return [dict(row) for row in rows]

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

    async def calculate_consumption(self, start_date: str, end_date: str) -> List[Dict]:
        """Расчет расхода между двумя датами"""
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
            """, start_date, end_date)
            return [dict(row) for row in rows]
