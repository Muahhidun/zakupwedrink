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

            # Таблица пользователей
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица заявок на ввод остатков
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submitted_by INTEGER NOT NULL,
                    submission_date DATE NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by INTEGER,
                    rejection_reason TEXT,
                    FOREIGN KEY (submitted_by) REFERENCES users(id)
                )
            """)

            # Позиции заявки
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    edited_quantity REAL,
                    edited_weight REAL,
                    FOREIGN KEY (submission_id) REFERENCES pending_stock_submissions(id),
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

    async def get_supply_total(self, date: str) -> float:
        """Получить общую сумму поставок за день"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT SUM(cost) FROM supplies WHERE date = ?", (date,)) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0.0

    async def get_supply_total_period(self, start_date: str, end_date: str) -> float:
        """Получить общую сумму поставок за период"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT SUM(cost) FROM supplies WHERE date BETWEEN ? AND ?", (start_date, end_date)) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0.0

    async def get_latest_date_before(self, date_str: str) -> Optional[str]:
        """Получить последнюю дату с остатками до указанной даты"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT MAX(date) FROM stock WHERE date < ?", (date_str,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_supplies_between(self, start_date: str, end_date: str) -> List[Dict]:
        """Получить детальные поставки между датами"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT s.product_id, s.boxes, s.date,
                       p.units_per_box, p.package_weight, p.name_internal
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE s.date > ? AND s.date <= ?
            """, (start_date, end_date)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

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

    # ============ USERS ============

    async def get_user_role(self, user_id: int) -> Optional[str]:
        """Получить роль пользователя из БД. По умолчанию 'user'."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT role FROM users WHERE id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 'user'

    async def add_or_update_user(self, user_id: int, username: str = None,
                                 first_name: str = None, last_name: str = None):
        """Добавить или обновить пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (id, username, first_name, last_name, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, username, first_name, last_name))
            await db.commit()

    async def set_user_role(self, user_id: int, role: str):
        """Установить роль пользователя (admin / manager / user)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
            )
            await db.commit()

    async def get_admin_ids(self) -> List[int]:
        """Получить список id всех администраторов."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id FROM users WHERE role IN ('admin', 'manager')"
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def get_user_info(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о пользователе."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # ============ STOCK SUBMISSIONS (модерация) ============

    async def create_stock_submission(self, user_id: int, date, items: List[Dict]) -> int:
        """Создать заявку на ввод остатков (статус pending)."""
        async with aiosqlite.connect(self.db_path) as db:
            # Проверяем — нет ли уже pending заявки на эту дату от этого пользователя
            async with db.execute("""
                SELECT id FROM pending_stock_submissions
                WHERE submitted_by = ? AND submission_date = ? AND status = 'pending'
            """, (user_id, str(date))) as cursor:
                existing = await cursor.fetchone()
            if existing:
                raise ValueError(f"Уже есть ожидающая заявка #{existing[0]} за {date}")

            cursor = await db.execute("""
                INSERT INTO pending_stock_submissions (submitted_by, submission_date, status)
                VALUES (?, ?, 'pending')
            """, (user_id, str(date)))
            submission_id = cursor.lastrowid

            for item in items:
                await db.execute("""
                    INSERT INTO pending_stock_items
                    (submission_id, product_id, quantity, weight)
                    VALUES (?, ?, ?, ?)
                """, (submission_id, item['product_id'], item['quantity'], item['weight']))

            await db.commit()
            return submission_id

    async def get_submission_by_id(self, submission_id: int) -> Optional[Dict]:
        """Получить заявку по id."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT ps.*, u.username, u.first_name, u.last_name
                FROM pending_stock_submissions ps
                JOIN users u ON ps.submitted_by = u.id
                WHERE ps.id = ?
            """, (submission_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_submission_items(self, submission_id: int) -> List[Dict]:
        """Получить позиции заявки."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT psi.*, p.name_internal, p.name_russian, p.package_weight, p.unit
                FROM pending_stock_items psi
                JOIN products p ON psi.product_id = p.id
                WHERE psi.submission_id = ?
                ORDER BY p.name_internal
            """, (submission_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def approve_submission(self, submission_id: int, reviewer_id: int):
        """Одобрить заявку — перенести позиции в таблицу stock."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Получаем саму заявку
            async with db.execute("SELECT * FROM pending_stock_submissions WHERE id = ?", (submission_id,)) as cursor:
                sub = await cursor.fetchone()
            if not sub:
                raise ValueError(f"Заявка #{submission_id} не найдена")

            # Получаем товары с учетом правок админа
            async with db.execute("""
                SELECT product_id, 
                       COALESCE(edited_quantity, quantity) as q, 
                       COALESCE(edited_weight, weight) as w
                FROM pending_stock_items WHERE submission_id = ?
            """, (submission_id,)) as cursor:
                items = await cursor.fetchall()

            for item in items:
                await db.execute("""
                    INSERT INTO stock (product_id, date, quantity, weight)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(product_id, date)
                    DO UPDATE SET quantity=excluded.quantity, weight=excluded.weight
                """, (item['product_id'], sub['submission_date'], item['q'], item['w']))

            await db.execute("""
                UPDATE pending_stock_submissions
                SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
                WHERE id = ?
            """, (reviewer_id, submission_id))
            await db.commit()

    async def reject_submission(self, submission_id: int, reviewer_id: int):
        """Отклонить заявку."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE pending_stock_submissions
                SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
                WHERE id = ?
            """, (reviewer_id, submission_id))
            await db.commit()

    async def update_submission_item(self, submission_id: int, product_id: int, quantity: float, weight: float):
        """Изменить позицию заявки перед одобрением."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE pending_stock_items
                SET edited_quantity = ?, edited_weight = ?
                WHERE submission_id = ? AND product_id = ?
            """, (quantity, weight, submission_id, product_id))
            await db.commit()

    # ============ PENDING ORDERS (заглушки для SQLite) ============

    async def get_pending_weight_for_product(self, product_id: int) -> float:
        return 0.0

    async def create_pending_order(self, total_cost: float, notes: str = None) -> int:
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def get_pending_orders(self) -> List[Dict]:
        return []

    async def get_pending_order_items(self, order_id: int) -> List[Dict]:
        return []

    async def add_item_to_order(self, order_id: int, product_id: int,
                                boxes: int, weight: float, cost: float):
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def complete_order(self, order_id: int):
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def cancel_order(self, order_id: int):
        raise NotImplementedError("Pending orders доступны только с PostgreSQL")

    async def get_stock_with_consumption(self, lookback_days: int = 14) -> List[Dict]:
        """Остатки с расчётом потребления с учетом поставок (SQLite)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                WITH latest_dates AS (
                    SELECT product_id, MAX(date) as max_date
                    FROM stock
                    GROUP BY product_id
                ),
                first_dates AS (
                    SELECT product_id, MIN(date) as min_date
                    FROM stock
                    WHERE date >= DATE('now', '-' || ? || ' days')
                    GROUP BY product_id
                )
                SELECT
                    p.id AS product_id, p.name_internal, p.name_russian,
                    p.package_weight, p.units_per_box, p.box_weight, p.price_per_box, p.unit,
                    s_last.quantity  AS quantity,
                    s_last.weight    AS weight,
                    s_last.date      AS last_date,
                    s_first.weight   AS first_weight,
                    s_first.date     AS first_date,
                    (SELECT COALESCE(SUM(weight), 0) FROM supplies 
                     WHERE product_id = p.id 
                       AND date > fd.min_date AND date <= ld.max_date) as supply_weight
                FROM products p
                JOIN latest_dates ld ON p.id = ld.product_id
                JOIN stock s_last ON ld.product_id = s_last.product_id AND ld.max_date = s_last.date
                LEFT JOIN first_dates fd ON p.id = fd.product_id
                LEFT JOIN stock s_first ON fd.product_id = s_first.product_id AND fd.min_date = s_first.date
                ORDER BY p.name_internal
            """, (lookback_days,)) as cursor:
                rows = await cursor.fetchall()
                result = []
                from datetime import datetime
                for r in rows:
                    d = dict(r)
                    fw = d.pop('first_weight', None)
                    fd_str = d.pop('first_date', None)
                    ld_str = d.get('last_date')
                    sw = d.pop('supply_weight', 0)
                    
                    actual_days = 0
                    if fd_str and ld_str:
                        try:
                            fd_dt = datetime.strptime(fd_str, '%Y-%m-%d')
                            ld_dt = datetime.strptime(ld_str, '%Y-%m-%d')
                            actual_days = (ld_dt - fd_dt).days
                        except:
                            actual_days = 0
                    
                    if fw is not None and d.get('weight') is not None and actual_days > 0:
                        # Расчет потребления: (начальный вес + поставки - конечный вес) / количество дней
                        fw_val = float(fw) if fw is not None else 0.0
                        sw_val = float(sw) if sw is not None else 0.0
                        curr_weight = float(d['weight']) if d['weight'] is not None else 0.0
                        consumed = fw_val + sw_val - curr_weight
                        d['avg_daily_consumption'] = max(0.0, consumed / actual_days)
                    else:
                        d['avg_daily_consumption'] = 0.0
                        
                    d['days_remaining'] = (
                        round(float(d['weight']) / d['avg_daily_consumption'])
                        if d.get('avg_daily_consumption', 0) > 0 and d.get('weight') is not None else 999
                    )
                    result.append(d)
                return result

    async def has_stock_for_date(self, date) -> bool:
        stock = await self.get_stock_by_date(str(date))
        return len(stock) > 0
