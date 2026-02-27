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
        # Создаем пул соединений с поддержкой SSL для Railway
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=10,
            ssl='require'
        )

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

            # Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Таблица заказов (товары в пути)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
                    total_cost REAL NOT NULL,
                    notes TEXT
                )
            """)

            # Таблица товаров в заказах
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    boxes_ordered INTEGER NOT NULL,
                    weight_ordered REAL NOT NULL,
                    cost REAL NOT NULL
                )
            """)

            # Таблица заявок на ввод остатков
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_submissions (
                    id SERIAL PRIMARY KEY,
                    submitted_by BIGINT NOT NULL REFERENCES users(id),
                    submission_date DATE NOT NULL,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by BIGINT REFERENCES users(id),
                    rejection_reason TEXT
                )
            """)

            # Позиции заявки
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_items (
                    id SERIAL PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES pending_stock_submissions(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    edited_quantity REAL,
                    edited_weight REAL
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

    async def get_supply_total(self, date) -> float:
        """Получить общую сумму поставок за день"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT SUM(cost) FROM supplies WHERE date = $1", date)
            return float(total) if total else 0.0

    async def get_supply_total_period(self, start_date, end_date) -> float:
        """Получить общую сумму поставок за период"""
        from datetime import datetime, date
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT SUM(cost) FROM supplies WHERE date BETWEEN $1 AND $2", start_date, end_date)
            return float(total) if total else 0.0

    async def get_latest_date_before(self, date_val) -> Optional[datetime]:
        """Получить последнюю дату с остатками до указанной даты"""
        if isinstance(date_val, str):
            from datetime import datetime
            date_val = datetime.strptime(date_val, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MAX(date) FROM stock WHERE date < $1", date_val)

    async def get_supplies_between(self, start_date, end_date) -> List[Dict]:
        """Получить детальные поставки между датами"""
        from datetime import datetime, date
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.product_id, s.boxes, s.date,
                       p.units_per_box, p.package_weight, p.name_internal
                FROM supplies s
                JOIN products p ON s.product_id = p.id
                WHERE s.date > $1 AND s.date <= $2
            """, start_date, end_date)
            return [dict(row) for row in rows]

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
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM stock WHERE date = $1
            """, date)
            return count > 0

    async def get_stock_history(self, product_id: int, days: int = 7) -> List[Dict]:
        """Получить историю остатков товара за последние N дней (от самой последней записи)"""
        from datetime import timedelta
        async with self.pool.acquire() as conn:
            # Сначала находим последнюю дату для этого товара
            latest_date = await conn.fetchval("""
                SELECT MAX(date) FROM stock WHERE product_id = $1
            """, product_id)

            if not latest_date:
                return []

            # Вычисляем начальную дату в Python
            start_date = latest_date - timedelta(days=days)

            # Затем берём записи за период
            rows = await conn.fetch("""
                SELECT * FROM stock
                WHERE product_id = $1
                  AND date >= $2
                ORDER BY date DESC
            """, product_id, start_date)
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
            """, start_date_obj, end_date_obj)

            return [dict(row) for row in rows]

    async def get_stock_with_consumption(self, lookback_days: int = 14) -> List[Dict]:
        """Остатки с расчётом потребления с учетом поставок (PostgreSQL)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                WITH latest_dates AS (
                    SELECT product_id, MAX(date) as max_date
                    FROM stock
                    GROUP BY product_id
                ),
                first_dates AS (
                    SELECT product_id, MIN(date) as min_date
                    FROM stock
                    WHERE date >= CURRENT_DATE - ($1::integer * INTERVAL '1 day')
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
                       AND date > fd.min_date AND date <= ld.max_date) as supply_weight,
                    (SELECT COALESCE(SUM(poi.weight_ordered), 0) 
                     FROM pending_order_items poi 
                     JOIN pending_orders po ON poi.order_id = po.id 
                     WHERE poi.product_id = p.id AND po.status = 'pending') as pending_weight
                FROM products p
                JOIN latest_dates ld ON p.id = ld.product_id
                JOIN stock s_last ON ld.product_id = s_last.product_id AND ld.max_date = s_last.date
                LEFT JOIN first_dates fd ON p.id = fd.product_id
                LEFT JOIN stock s_first ON fd.product_id = s_first.product_id AND fd.min_date = s_first.date
                ORDER BY p.name_internal
            """, lookback_days)
            
            result = []
            for r in rows:
                d = dict(r)
                fw = d.pop('first_weight', None)
                fd_val = d.pop('first_date', None)
                ld_val = d.get('last_date')
                sw = d.pop('supply_weight', 0)
                pw = d.get('pending_weight', 0)
                
                # Считаем реальное количество дней между замерами
                actual_days = 0
                if fd_val and ld_val:
                    actual_days = (ld_val - fd_val).days
                
                if fw is not None and d.get('weight') is not None and actual_days > 0:
                    # Расчет потребления: (начальный вес + поставки - конечный вес) / количество дней
                    fw_val = float(fw) if fw is not None else 0.0
                    sw_val = float(sw) if sw is not None else 0.0
                    curr_weight = float(d['weight']) if d['weight'] is not None else 0.0
                    consumed = fw_val + sw_val - curr_weight
                    d['avg_daily_consumption'] = max(0.0, consumed / actual_days)
                else:
                    d['avg_daily_consumption'] = 0.0
                
                # Дни до обнуления считаем С УЧЕТОМ того, что УЖЕ заказано (pending_weight)
                current_weight = float(d['weight'] or 0)
                pending_weight = float(pw or 0)
                total_potential_weight = current_weight + pending_weight
                
                d['days_remaining'] = (
                    round(total_potential_weight / d['avg_daily_consumption'])
                    if d.get('avg_daily_consumption', 0) > 0 else 999
                )
                
                # Приводим типы к стандартным для JSON
                for key in ['quantity', 'weight', 'package_weight', 'box_weight', 'price_per_box']:
                    if d.get(key) is not None:
                        d[key] = float(d[key])
                if d.get('last_date'):
                    d['last_date'] = str(d['last_date'])
                
                result.append(d)
            return result

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
        """Получить историю поставок товара за последние N дней (от последней записи остатков)"""
        from datetime import timedelta
        async with self.pool.acquire() as conn:
            # Находим последнюю дату остатков для этого товара
            latest_stock_date = await conn.fetchval("""
                SELECT MAX(date) FROM stock WHERE product_id = $1
            """, product_id)

            if not latest_stock_date:
                return []

            # Вычисляем начальную дату в Python
            start_date = latest_stock_date - timedelta(days=days)

            # Берём поставки за период
            rows = await conn.fetch("""
                SELECT * FROM supplies
                WHERE product_id = $1
                  AND date >= $2
                ORDER BY date DESC
            """, product_id, start_date)
            return [dict(row) for row in rows]

    async def add_or_update_user(self, user_id: int, username: str = None,
                                  first_name: str = None, last_name: str = None):
        """Добавить или обновить пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_name, last_seen)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_seen = CURRENT_TIMESTAMP
            """, user_id, username, first_name, last_name)

    async def get_all_active_users(self) -> List[int]:
        """Получить всех активных пользователей для рассылки"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id FROM users WHERE is_active = TRUE
            """)
            return [row['id'] for row in rows]

    # ============ USER ROLES ============

    async def get_user_role(self, user_id: int) -> str:
        """Получить роль пользователя. По умолчанию 'user'."""
        async with self.pool.acquire() as conn:
            role = await conn.fetchval("SELECT role FROM users WHERE id = $1", user_id)
            return role or 'user'

    async def set_user_role(self, user_id: int, role: str):
        """Установить роль пользователя (admin / manager / user)."""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET role = $1 WHERE id = $2", role, user_id)

    async def list_users_with_roles(self) -> List[Dict]:
        """Список всех пользователей с ролями"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.username, u.first_name, u.last_name,
                       u.role, u.is_active, u.added_at, u.display_name,
                       a.username as added_by_username
                FROM users u
                LEFT JOIN users a ON u.added_by = a.id
                ORDER BY u.added_at DESC
            """)
            return [dict(row) for row in rows]

    async def get_admin_ids(self) -> List[int]:
        """Получить список ID всех админов"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users WHERE role = 'admin'")
            return [row['id'] for row in rows]

    async def get_user_info(self, user_id: int) -> Dict:
        """Получить информацию о пользователе"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, username, first_name, last_name, role, display_name
                FROM users WHERE id = $1
            """, user_id)
            return dict(row) if row else {}

    # ============ PENDING STOCK SUBMISSIONS ============

    async def create_stock_submission(self, user_id: int, date, items: List[Dict]) -> int:
        """Создать новую заявку на остатки"""
        from datetime import datetime
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            # Проверяем есть ли уже pending заявка на эту дату
            existing = await conn.fetchval("""
                SELECT id FROM pending_stock_submissions
                WHERE submitted_by = $1 AND submission_date = $2 AND status = 'pending'
            """, user_id, date)

            if existing:
                raise ValueError(f"У вас уже есть ожидающая модерации заявка на {date}")

            # Создаем submission
            submission_id = await conn.fetchval("""
                INSERT INTO pending_stock_submissions (submitted_by, submission_date)
                VALUES ($1, $2) RETURNING id
            """, user_id, date)

            # Добавляем items
            for item in items:
                await conn.execute("""
                    INSERT INTO pending_stock_items
                    (submission_id, product_id, quantity, weight)
                    VALUES ($1, $2, $3, $4)
                """, submission_id, item['product_id'], item['quantity'], item['weight'])

            return submission_id

    async def get_pending_submissions(self) -> List[Dict]:
        """Получить все pending заявки"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ps.*, u.username, u.first_name, u.last_name, u.display_name,
                       COUNT(psi.id) as items_count
                FROM pending_stock_submissions ps
                JOIN users u ON ps.submitted_by = u.id
                LEFT JOIN pending_stock_items psi ON ps.id = psi.submission_id
                WHERE ps.status = 'pending'
                GROUP BY ps.id, u.username, u.first_name, u.last_name, u.display_name
                ORDER BY ps.created_at ASC
            """)
            return [dict(row) for row in rows]

    async def get_all_submissions(self) -> List[Dict]:
        """Получить все заявки (для web-панели)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ps.*, u.username, u.first_name, u.last_name, u.display_name,
                       COUNT(psi.id) as items_count
                FROM pending_stock_submissions ps
                JOIN users u ON ps.submitted_by = u.id
                LEFT JOIN pending_stock_items psi ON ps.id = psi.submission_id
                GROUP BY ps.id, u.username, u.first_name, u.last_name, u.display_name
                ORDER BY ps.created_at DESC
            """)
            return [dict(row) for row in rows]

    async def get_submission_by_id(self, submission_id: int) -> Dict:
        """Получить submission по ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT ps.*, u.username, u.first_name, u.last_name, u.display_name
                FROM pending_stock_submissions ps
                JOIN users u ON ps.submitted_by = u.id
                WHERE ps.id = $1
            """, submission_id)
            return dict(row) if row else None

    async def get_submission_items(self, submission_id: int) -> List[Dict]:
        """Получить товары в заявке"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT psi.*, p.name_internal, p.name_russian,
                       p.package_weight, p.unit
                FROM pending_stock_items psi
                JOIN products p ON psi.product_id = p.id
                WHERE psi.submission_id = $1
                ORDER BY p.name_internal
            """, submission_id)
            return [dict(row) for row in rows]

    async def approve_submission(self, submission_id: int, admin_id: int):
        """Утвердить заявку и перенести данные в stock"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                submission = await conn.fetchrow("""
                    SELECT submitted_by, submission_date
                    FROM pending_stock_submissions
                    WHERE id = $1 AND status = 'pending'
                """, submission_id)

                if not submission:
                    raise ValueError(f"Pending submission {submission_id} not found")

                items = await conn.fetch("""
                    SELECT product_id,
                           COALESCE(edited_quantity, quantity) as quantity,
                           COALESCE(edited_weight, weight) as weight
                    FROM pending_stock_items WHERE submission_id = $1
                """, submission_id)

                # Переносим в stock
                for item in items:
                    await conn.execute("""
                        INSERT INTO stock (product_id, date, quantity, weight)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT(product_id, date)
                        DO UPDATE SET quantity=EXCLUDED.quantity, weight=EXCLUDED.weight
                    """, item['product_id'], submission['submission_date'],
                         item['quantity'], item['weight'])

                # Обновляем статус
                await conn.execute("""
                    UPDATE pending_stock_submissions
                    SET status = 'approved', reviewed_by = $1, reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                """, admin_id, submission_id)

                return submission['submitted_by']

    async def reject_submission(self, submission_id: int, admin_id: int, reason: str = None):
        """Отклонить заявку"""
        async with self.pool.acquire() as conn:
            submitted_by = await conn.fetchval("""
                UPDATE pending_stock_submissions
                SET status = 'rejected', reviewed_by = $1,
                    reviewed_at = CURRENT_TIMESTAMP, rejection_reason = $2
                WHERE id = $3 AND status = 'pending'
                RETURNING submitted_by
            """, admin_id, reason, submission_id)

            if not submitted_by:
                raise ValueError(f"Pending submission {submission_id} not found")

            return submitted_by

    async def update_submission_item(self, submission_id: int, product_id: int,
                                    quantity: float, weight: float):
        """Отредактировать товар в заявке"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE pending_stock_items
                SET edited_quantity = $1, edited_weight = $2
                WHERE submission_id = $3 AND product_id = $4
            """, quantity, weight, submission_id, product_id)

    async def get_user_submissions(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Получить заявки пользователя (все статусы)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ps.*, COUNT(psi.id) as items_count,
                       r.username as reviewed_by_username
                FROM pending_stock_submissions ps
                LEFT JOIN pending_stock_items psi ON ps.id = psi.submission_id
                LEFT JOIN users r ON ps.reviewed_by = r.id
                WHERE ps.submitted_by = $1
                GROUP BY ps.id, r.username
                ORDER BY ps.created_at DESC
                LIMIT $2
            """, user_id, limit)
            return [dict(row) for row in rows]

    # ============ PENDING ORDERS (Заказы в пути) ============

    async def create_pending_order(self, total_cost: float, notes: str = None) -> int:
        """Создать новый заказ. Возвращает order_id"""
        async with self.pool.acquire() as conn:
            order_id = await conn.fetchval("""
                INSERT INTO pending_orders (total_cost, notes)
                VALUES ($1, $2)
                RETURNING id
            """, total_cost, notes)
            return order_id

    async def add_item_to_order(self, order_id: int, product_id: int,
                                boxes: int, weight: float, cost: float):
        """Добавить товар в заказ"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO pending_order_items
                (order_id, product_id, boxes_ordered, weight_ordered, cost)
                VALUES ($1, $2, $3, $4, $5)
            """, order_id, product_id, boxes, weight, cost)

    async def get_pending_orders(self) -> List[Dict]:
        """Получить все активные заказы (в пути)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    po.id,
                    po.created_at,
                    po.total_cost,
                    po.notes,
                    COUNT(poi.id) as items_count,
                    SUM(poi.weight_ordered) as total_weight
                FROM pending_orders po
                LEFT JOIN pending_order_items poi ON po.id = poi.order_id
                WHERE po.status = 'pending'
                GROUP BY po.id, po.created_at, po.total_cost, po.notes
                ORDER BY po.created_at DESC
            """)
            return [dict(row) for row in rows]

    async def get_pending_order_items(self, order_id: int) -> List[Dict]:
        """Получить товары конкретного заказа"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    poi.*,
                    p.name_russian,
                    p.name_internal,
                    p.box_weight,
                    p.unit
                FROM pending_order_items poi
                JOIN products p ON poi.product_id = p.id
                WHERE poi.order_id = $1
                ORDER BY p.name_russian
            """, order_id)
            return [dict(row) for row in rows]

    async def complete_order(self, order_id: int):
        """Закрыть заказ (пометить как выполненный)"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE pending_orders
                SET status = 'completed'
                WHERE id = $1
            """, order_id)

    async def cancel_order(self, order_id: int):
        """Отменить заказ"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE pending_orders
                SET status = 'cancelled'
                WHERE id = $1
            """, order_id)

    async def get_pending_weight_for_product(self, product_id: int) -> float:
        """Получить общий вес товара в активных заказах (в пути)"""
        async with self.pool.acquire() as conn:
            weight = await conn.fetchval("""
                SELECT COALESCE(SUM(poi.weight_ordered), 0)
                FROM pending_order_items poi
                JOIN pending_orders po ON poi.order_id = po.id
                WHERE poi.product_id = $1 AND po.status = 'pending'
            """, product_id)
            return float(weight) if weight else 0.0
