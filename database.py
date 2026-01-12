"""
База данных для учета складских остатков WeDrink
"""
import aiosqlite
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple


class Database:
    def __init__(self, db_path: str = "wedrink.db"):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация базы данных"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица товаров
            await db.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS stock (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(id),
                    UNIQUE(product_id, date)
                )
            """)

            # Таблица поставок
            await db.execute("""
                CREATE TABLE IF NOT EXISTS supplies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    boxes INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    cost REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)

            await db.commit()
            print("✅ База данных инициализирована")

    async def add_product(self, name_chinese: str, name_russian: str, name_internal: str,
                         package_weight: float, units_per_box: int, price_per_box: float,
                         unit: str = "кг") -> int:
        """Добавить товар"""
        box_weight = package_weight * units_per_box
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO products
                (name_chinese, name_russian, name_internal, package_weight,
                 units_per_box, box_weight, price_per_box, unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name_chinese, name_russian, name_internal, package_weight,
                  units_per_box, box_weight, price_per_box, unit))
            await db.commit()
            return cursor.lastrowid

    async def get_all_products(self) -> List[Dict]:
        """Получить все товары"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM products ORDER BY name_internal") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_product_by_name(self, name_internal: str) -> Optional[Dict]:
        """Получить товар по внутреннему названию"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM products WHERE name_internal = ?", (name_internal,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def add_stock(self, product_id: int, date: str, quantity: float, weight: float):
        """Добавить/обновить остаток на дату"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO stock (product_id, date, quantity, weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(product_id, date)
                DO UPDATE SET quantity=excluded.quantity, weight=excluded.weight
            """, (product_id, date, quantity, weight))
            await db.commit()

    async def add_supply(self, product_id: int, date: str, boxes: int,
                        weight: float, cost: float):
        """Добавить поставку"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO supplies (product_id, date, boxes, weight, cost)
                VALUES (?, ?, ?, ?, ?)
            """, (product_id, date, boxes, weight, cost))
            await db.commit()

    async def get_stock_by_date(self, date: str) -> List[Dict]:
        """Получить остатки на дату"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT s.*, p.name_internal, p.name_russian, p.package_weight,
                       p.units_per_box, p.box_weight, p.price_per_box
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = ?
                ORDER BY p.name_internal
            """, (date,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_latest_stock(self) -> List[Dict]:
        """Получить последние остатки по всем товарам"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT s.*, p.name_internal, p.name_russian, p.package_weight,
                       p.units_per_box, p.box_weight, p.price_per_box
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.date = (
                    SELECT MAX(date) FROM stock WHERE product_id = s.product_id
                )
                ORDER BY p.name_internal
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_stock_history(self, product_id: int, days: int = 7) -> List[Dict]:
        """Получить историю остатков товара за последние N дней"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM stock
                WHERE product_id = ?
                ORDER BY date DESC
                LIMIT ?
            """, (product_id, days)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def calculate_consumption(self, start_date: str, end_date: str) -> List[Dict]:
        """Расчет расхода между двумя датами"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
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
                LEFT JOIN stock s1 ON p.id = s1.product_id AND s1.date = ?
                LEFT JOIN stock s2 ON p.id = s2.product_id AND s2.date = ?
                WHERE s1.weight IS NOT NULL AND s2.weight IS NOT NULL
                ORDER BY cost DESC
            """, (start_date, end_date)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_stock_dates_summary(self) -> List[Dict]:
        """Получить сводку по датам с остатками"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT
                    date,
                    COUNT(*) as product_count,
                    SUM(weight) as total_weight
                FROM stock
                GROUP BY date
                ORDER BY date DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_total_stock_records(self) -> int:
        """Получить общее количество записей об остатках"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM stock") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    # ============ PENDING ORDERS (Заглушки для SQLite) ============
    # Примечание: полная функциональность реализована только в database_pg.py

    async def get_pending_weight_for_product(self, product_id: int) -> float:
        """Получить вес товара в активных заказах (заглушка для SQLite)"""
        return 0.0

    async def create_pending_order(self, total_cost: float, notes: str = None) -> int:
        """Создать заказ (заглушка для SQLite)"""
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def get_pending_orders(self) -> List[Dict]:
        """Получить активные заказы (заглушка для SQLite)"""
        return []

    async def get_pending_order_items(self, order_id: int) -> List[Dict]:
        """Получить товары заказа (заглушка для SQLite)"""
        return []

    async def add_item_to_order(self, order_id: int, product_id: int,
                                boxes: int, weight: float, cost: float):
        """Добавить товар в заказ (заглушка для SQLite)"""
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def complete_order(self, order_id: int):
        """Закрыть заказ (заглушка для SQLite)"""
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def cancel_order(self, order_id: int):
        """Отменить заказ (заглушка для SQLite)"""
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")
