"""
База данных PostgreSQL для учета складских остатков WeDrink (Multi-Tenant SaaS)
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
        """Инициализация пула соединений и создание таблиц (Multi-Tenant)"""
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=1,
            max_size=10,
            ssl='require'
        )

        async with self.pool.acquire() as conn:
            # 1. Companies Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    subscription_status TEXT DEFAULT 'trial' CHECK (subscription_status IN ('trial', 'active', 'expired', 'cancelled')),
                    subscription_ends_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Users Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Products Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    name_chinese TEXT,
                    name_russian TEXT,
                    name_internal TEXT NOT NULL,
                    package_weight REAL NOT NULL,
                    units_per_box INTEGER NOT NULL,
                    box_weight REAL NOT NULL,
                    price_per_box REAL NOT NULL,
                    unit TEXT DEFAULT 'кг',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company_id, name_internal)
                )
            """)

            # 4. Stock Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company_id, product_id, date)
                )
            """)

            # 5. Supplies Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS supplies (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    boxes INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    cost REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. Pending Orders Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_orders (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
                    total_cost REAL NOT NULL,
                    notes TEXT
                )
            """)

            # 7. Pending Order Items
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES pending_orders(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    boxes_ordered INTEGER NOT NULL,
                    weight_ordered REAL NOT NULL,
                    cost REAL NOT NULL
                )
            """)

            # 8. Pending Stock Submissions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_submissions (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    submitted_by BIGINT NOT NULL REFERENCES users(id),
                    submission_date DATE NOT NULL,
                    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by BIGINT REFERENCES users(id),
                    rejection_reason TEXT
                )
            """)

            # 9. Pending Stock Items
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_items (
                    id SERIAL PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES pending_stock_submissions(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    edited_quantity REAL,
                    edited_weight REAL
                )
            """)

        print("✅ PostgreSQL SaaS база данных инициализирована")

    async def close(self):
        """Закрыть пул соединений"""
        if self.pool:
            await self.pool.close()

    async def add_product(self, company_id: int, name_chinese: str, name_russian: str, name_internal: str,
                         package_weight: float, units_per_box: int, price_per_box: float,
                         unit: str = "кг") -> int:
        """Добавить товар компании"""
        box_weight = package_weight * units_per_box
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                INSERT INTO products
                (company_id, name_chinese, name_russian, name_internal, package_weight,
                 units_per_box, box_weight, price_per_box, unit)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, company_id, name_chinese, name_russian, name_internal, package_weight,
                units_per_box, box_weight, price_per_box, unit)
            return result

    async def get_all_products(self, company_id: int) -> List[Dict]:
        """Получить все товары компании"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM products WHERE company_id = $1 ORDER BY name_internal", company_id)
            return [dict(row) for row in rows]

    async def get_product_by_name(self, company_id: int, name_internal: str) -> Optional[Dict]:
        """Получить товар по внутреннему названию для конкретной компании"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM products WHERE company_id = $1 AND name_internal = $2", 
                company_id, name_internal
            )
            return dict(row) if row else None

    async def add_stock(self, company_id: int, product_id: int, date, quantity: float, weight: float):
        """Добавить/обновить остаток на дату"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO stock (company_id, product_id, date, quantity, weight)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT(company_id, product_id, date)
                DO UPDATE SET quantity=EXCLUDED.quantity, weight=EXCLUDED.weight
            """, company_id, product_id, date, quantity, weight)

    async def add_supply(self, company_id: int, product_id: int, date, boxes: int,
                        weight: float, cost: float):
        """Добавить поставку"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO supplies (company_id, product_id, date, boxes, weight, cost)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, company_id, product_id, date, boxes, weight, cost)

    async def get_supply_total(self, company_id: int, date) -> float:
        """Получить общую сумму поставок за день"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT SUM(cost) FROM supplies WHERE company_id = $1 AND date = $2", company_id, date)
            return float(total) if total else 0.0

    async def get_supply_total_period(self, company_id: int, start_date, end_date) -> float:
        """Получить общую сумму поставок за период"""
        from datetime import datetime
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT SUM(cost) FROM supplies WHERE company_id = $1 AND date BETWEEN $2 AND $3", company_id, start_date, end_date)
            return float(total) if total else 0.0

    async def get_latest_date_before(self, company_id: int, date_val) -> Optional[datetime]:
        """Получить последнюю дату с остатками до указанной даты"""
        if isinstance(date_val, str):
            from datetime import datetime
            date_val = datetime.strptime(date_val, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MAX(date) FROM stock WHERE company_id = $1 AND date < $2", company_id, date_val)

    async def get_supplies_between(self, company_id: int, start_date, end_date) -> List[Dict]:
        """Получить детальные поставки между датами"""
        from datetime import datetime
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
                WHERE s.company_id = $1 AND s.date > $2 AND s.date <= $3
            """, company_id, start_date, end_date)
            return [dict(row) for row in rows]

    async def get_stock_by_date(self, company_id: int, date) -> List[Dict]:
        """Получить остатки на дату"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.product_id, s.date, s.quantity, s.weight,
                       p.name_chinese, p.name_russian, p.name_internal,
                       p.package_weight, p.units_per_box
                FROM stock s
                JOIN products p ON s.product_id = p.id
                WHERE s.company_id = $1 AND s.date = $2
                ORDER BY p.name_internal
            """, company_id, date)
            return [dict(row) for row in rows]

    async def get_latest_stock(self, company_id: int) -> List[Dict]:
        """Получить самые свежие остатки по каждому товару"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                WITH RankedStock AS (
                    SELECT product_id, quantity, weight, date,
                           ROW_NUMBER() OVER(PARTITION BY product_id ORDER BY date DESC) as rn
                    FROM stock
                    WHERE company_id = $1
                )
                SELECT rs.product_id, rs.quantity, rs.weight, rs.date,
                       p.name_chinese, p.name_russian, p.name_internal,
                       p.package_weight, p.units_per_box
                FROM RankedStock rs
                JOIN products p ON rs.product_id = p.id
                WHERE rs.rn = 1
                ORDER BY p.name_internal
            """, company_id)
            return [dict(row) for row in rows]

    async def has_stock_for_date(self, company_id: int, date) -> bool:
        """Проверка наличия остатков на дату"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT 1 FROM stock WHERE company_id = $1 AND date = $2 LIMIT 1", 
                company_id, date
            )
            return bool(val)

    async def get_stock_history(self, company_id: int, product_id: int, days: int = 7) -> List[Dict]:
        """История остатков товара"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT date, quantity, weight
                FROM stock
                WHERE company_id = $1 AND product_id = $2
                ORDER BY date DESC
                LIMIT $3
            """, company_id, product_id, days)
            return [dict(row) for row in rows]

    async def calculate_consumption(self, company_id: int, start_date, end_date) -> List[Dict]:
        """Рассчитать расход между двумя датами (расход = остаток_вчера + поставки - остаток_сегодня)"""
        from datetime import datetime
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                WITH start_stock AS (
                    SELECT product_id, quantity, weight FROM stock 
                    WHERE company_id = $1 AND date = $2
                ),
                end_stock AS (
                    SELECT product_id, quantity, weight FROM stock 
                    WHERE company_id = $1 AND date = $3
                ),
                period_supplies AS (
                    SELECT product_id, SUM(boxes) as total_boxes, SUM(weight) as total_weight
                    FROM supplies
                    WHERE company_id = $1 AND date > $2 AND date <= $3
                    GROUP BY product_id
                )
                SELECT p.id as product_id,
                       p.name_internal,
                       COALESCE(s_start.quantity, 0) as start_quantity,
                       COALESCE(s_end.quantity, 0) as end_quantity,
                       COALESCE(ps.total_boxes, 0) as supplied_quantity,
                       (COALESCE(s_start.quantity, 0) + COALESCE(ps.total_boxes, 0) - COALESCE(s_end.quantity, 0)) as consumed_quantity,
                       (COALESCE(s_start.weight, 0) + COALESCE(ps.total_weight, 0) - COALESCE(s_end.weight, 0)) as consumed_weight
                FROM products p
                LEFT JOIN start_stock s_start ON p.id = s_start.product_id
                LEFT JOIN end_stock s_end ON p.id = s_end.product_id
                LEFT JOIN period_supplies ps ON p.id = ps.product_id
                WHERE p.company_id = $1 AND (s_start.quantity IS NOT NULL OR s_end.quantity IS NOT NULL OR ps.total_boxes IS NOT NULL)
            """, company_id, start_date, end_date)
            return [dict(row) for row in rows]

    async def get_stock_with_consumption(self, company_id: int, lookback_days: int = 14) -> List[Dict]:
        """Получить текущие остатки и средний расход"""
        from datetime import timedelta
        latest_stock = await self.get_latest_stock(company_id)
        if not latest_stock:
            return []
            
        latest_date = latest_stock[0]['date']
        start_date = latest_date - timedelta(days=lookback_days)
        real_start_date = await self.get_latest_date_before(company_id, start_date + timedelta(days=1))
        
        if not real_start_date:
            real_start_date = latest_date - timedelta(days=lookback_days)
            
        actual_days = (latest_date - real_start_date).days
        if actual_days <= 0:
            actual_days = 1
            
        consumption = await self.calculate_consumption(company_id, real_start_date, latest_date)
        consumption_map = {item['product_id']: item for item in consumption}

        for item in latest_stock:
            pid = item['product_id']
            cons = consumption_map.get(pid)
            
            pending_boxes = await self.get_pending_weight_for_product(company_id, pid) / item['package_weight'] if item['package_weight'] else 0
            
            if cons and cons['consumed_quantity'] > 0:
                avg_daily_qty = cons['consumed_quantity'] / actual_days
                avg_daily_weight = cons['consumed_weight'] / actual_days
                item['avg_daily_consumption_qty'] = round(avg_daily_qty, 2)
                item['avg_daily_consumption_weight'] = round(avg_daily_weight, 2)
                total_available = item['quantity'] + pending_boxes
                item['days_remaining'] = round(total_available / avg_daily_qty, 1) if avg_daily_qty > 0 else 999
            else:
                item['avg_daily_consumption_qty'] = 0
                item['avg_daily_consumption_weight'] = 0
                item['days_remaining'] = 999
                
            item['pending_boxes'] = pending_boxes

        return latest_stock

    async def get_stock_dates_summary(self, company_id: int) -> List[Dict]:
        """Сводка по доступным датам остатков"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT date, COUNT(product_id) as items_count
                FROM stock
                WHERE company_id = $1
                GROUP BY date
                ORDER BY date DESC
                LIMIT 30
            """, company_id)
            return [dict(row) for row in rows]

    async def get_latest_stock_date(self, company_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MAX(date) FROM stock WHERE company_id = $1", company_id)

    async def get_total_stock_records(self, company_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM stock WHERE company_id = $1", company_id)

    async def get_supply_history(self, company_id: int, product_id: int, days: int = 14) -> List[Dict]:
        """История поставок товара"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT date, boxes, weight, cost
                FROM supplies
                WHERE company_id = $1 AND product_id = $2
                ORDER BY date DESC
                LIMIT $3
            """, company_id, product_id, days)
            return [dict(row) for row in rows]

    async def add_or_update_user(self, user_id: int, username: str = None, 
                               first_name: str = None, last_name: str = None, company_id: Optional[int] = None):
        """Добавить пользователя или обновить его данные"""
        async with self.pool.acquire() as conn:
            # Сначала проверяем, есть ли уже пользователь (чтобы не затереть его company_id)
            existing = await conn.fetchrow("SELECT company_id FROM users WHERE id = $1", user_id)
            
            final_company_id = company_id
            if existing and company_id is None:
                final_company_id = existing['company_id']

            await conn.execute("""
                INSERT INTO users (id, username, first_name, last_name, company_id, last_seen)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    company_id = COALESCE($5, users.company_id),
                    last_seen = CURRENT_TIMESTAMP
            """, user_id, username, first_name, last_name, final_company_id)

    async def get_users_by_company(self, company_id: int) -> List[Dict]:
        """Получить список всех сотрудников франшизы"""
        async with self.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT id, username, first_name, last_name, role, is_active, created_at, last_seen
                FROM users 
                WHERE company_id = $1
                ORDER BY created_at DESC
            """, company_id)
            return [dict(r) for r in records]

    async def get_user_role(self, user_id: int) -> str:
        """Получить роль пользователя"""
        async with self.pool.acquire() as conn:
            role = await conn.fetchval("SELECT role FROM users WHERE id = $1", user_id)
            return role if role else 'user'

    async def update_user_role(self, user_id: int, new_role: str):
        """Обновление роли пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET role = $1 WHERE id = $2", new_role, user_id)

    async def set_user_role(self, user_id: int, role: str):
        """Установить роль пользователю"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET role = $2 WHERE id = $1", user_id, role)

    async def list_users_with_roles(self, company_id: int) -> List[Dict]:
        """Список всех пользователей компании"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, first_name, last_name, username, role, last_seen 
                FROM users 
                WHERE company_id = $1
                ORDER BY 
                    CASE WHEN role='admin' THEN 1 WHEN role='manager' THEN 2 ELSE 3 END,
                    last_seen DESC
            """, company_id)
            return [dict(row) for row in rows]

    async def get_admin_ids(self, company_id: int) -> List[int]:
        """Получить ID всех админов компании"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users WHERE company_id = $1 AND role = 'admin'", company_id)
            return [row['id'] for row in rows]

    async def get_user_info(self, user_id: int) -> Dict:
        """Получить информацию о пользователе"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT u.id, u.first_name, u.last_name, u.username, u.role, u.company_id, c.name as company_name
                FROM users u
                LEFT JOIN companies c ON u.company_id = c.id
                WHERE u.id = $1
            """, user_id)
            return dict(row) if row else {}

    async def create_stock_submission(self, company_id: int, user_id: int, date, items: List[Dict]) -> int:
        """Создать заявку на ввод остатков"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                sub_id = await conn.fetchval("""
                    INSERT INTO pending_stock_submissions (company_id, submitted_by, submission_date)
                    VALUES ($1, $2, $3)
                    RETURNING id
                """, company_id, user_id, date)

                for item in items:
                    await conn.execute("""
                        INSERT INTO pending_stock_items (submission_id, product_id, quantity, weight)
                        VALUES ($1, $2, $3, $4)
                    """, sub_id, item['product_id'], item['quantity'], item['weight'])

                return sub_id

    async def get_pending_submissions(self, company_id: int) -> List[Dict]:
        """Получить все заявки компании"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.submission_date, s.status, s.created_at, 
                       u.first_name, u.last_name
                FROM pending_stock_submissions s
                JOIN users u ON s.submitted_by = u.id
                WHERE s.company_id = $1
                ORDER BY s.created_at DESC
            """, company_id)
            return [dict(row) for row in rows]

    async def get_submission_by_id(self, company_id: int, submission_id: int) -> Dict:
        """Получить заявку"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT s.*, u.first_name, u.last_name 
                FROM pending_stock_submissions s
                JOIN users u ON s.submitted_by = u.id
                WHERE s.id = $1 AND s.company_id = $2
            """, submission_id, company_id)
            return dict(row) if row else None

    async def get_submission_items(self, submission_id: int) -> List[Dict]:
        """Получить товары в заявке"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT i.*, p.name_internal, p.name_russian 
                FROM pending_stock_items i
                JOIN products p ON i.product_id = p.id
                WHERE i.submission_id = $1
            """, submission_id)
            return [dict(row) for row in rows]

    async def approve_submission(self, submission_id: int, admin_id: int):
        """Одобрить заявку: копирует данные в stock"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                sub = await conn.fetchrow("SELECT submission_date, company_id FROM pending_stock_submissions WHERE id = $1", submission_id)
                if not sub:
                    raise Exception("Submission not found")
                
                date = sub['submission_date']
                company_id = sub['company_id']
                
                items = await conn.fetch("SELECT * FROM pending_stock_items WHERE submission_id = $1", submission_id)
                
                for item in items:
                    qty = item['edited_quantity'] if item['edited_quantity'] is not None else item['quantity']
                    wgt = item['edited_weight'] if item['edited_weight'] is not None else item['weight']
                    
                    await conn.execute("""
                        INSERT INTO stock (company_id, product_id, date, quantity, weight)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT(company_id, product_id, date) DO UPDATE 
                        SET quantity=EXCLUDED.quantity, weight=EXCLUDED.weight
                    """, company_id, item['product_id'], date, qty, wgt)
                
                await conn.execute("""
                    UPDATE pending_stock_submissions 
                    SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = $2
                    WHERE id = $1
                """, submission_id, admin_id)

    async def reject_submission(self, submission_id: int, admin_id: int, reason: str = None):
        """Отклонить заявку"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE pending_stock_submissions 
                SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, 
                    reviewed_by = $2, rejection_reason = $3
                WHERE id = $1
            """, submission_id, admin_id, reason)

    async def update_submission_item(self, submission_id: int, product_id: int, 
                                     edited_quantity: float, edited_weight: float):
        """Правка остатка админом перед аппрувом"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE pending_stock_items
                SET edited_quantity = $3, edited_weight = $4
                WHERE submission_id = $1 AND product_id = $2
            """, submission_id, product_id, edited_quantity, edited_weight)

    async def get_user_submissions(self, company_id: int, user_id: int, limit: int = 20) -> List[Dict]:
        """История заявок пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, submission_date, status, created_at, rejection_reason
                FROM pending_stock_submissions
                WHERE company_id = $1 AND submitted_by = $2
                ORDER BY created_at DESC
                LIMIT $3
            """, company_id, user_id, limit)
            return [dict(row) for row in rows]

    async def create_pending_order(self, company_id: int, total_cost: float, notes: str = None) -> int:
        """Создать заявку на заказ"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO pending_orders (company_id, total_cost, notes)
                VALUES ($1, $2, $3)
                RETURNING id
            """, company_id, total_cost, notes)

    async def add_item_to_order(self, order_id: int, product_id: int, 
                                boxes_ordered: int, weight_ordered: float, cost: float):
        """Добавить товар к заказу"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO pending_order_items 
                (order_id, product_id, boxes_ordered, weight_ordered, cost)
                VALUES ($1, $2, $3, $4, $5)
            """, order_id, product_id, boxes_ordered, weight_ordered, cost)

    async def get_pending_orders(self, company_id: int) -> List[Dict]:
        """Получить все неисполненные заказы"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM pending_orders 
                WHERE company_id = $1 AND status = 'pending' 
                ORDER BY created_at ASC
            """, company_id)
            return [dict(row) for row in rows]

    async def get_pending_order_items(self, order_id: int) -> List[Dict]:
        """Детали заказа"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT i.*, p.name_internal, p.package_weight
                FROM pending_order_items i
                JOIN products p ON i.product_id = p.id
                WHERE i.order_id = $1
            """, order_id)
            return [dict(row) for row in rows]

    async def complete_order(self, order_id: int):
        """Заказ прибыл - переводим в статус completed, добавляем supplies"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                order = await conn.fetchrow("SELECT status, company_id FROM pending_orders WHERE id = $1", order_id)
                if not order or order['status'] != 'pending':
                    return
                
                company_id = order['company_id']
                from datetime import date
                today = date.today()

                items = await conn.fetch("SELECT * FROM pending_order_items WHERE order_id = $1", order_id)
                for item in items:
                    await conn.execute("""
                        INSERT INTO supplies (company_id, product_id, date, boxes, weight, cost)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, company_id, item['product_id'], today, item['boxes_ordered'], item['weight_ordered'], item['cost'])

                await conn.execute("UPDATE pending_orders SET status = 'completed' WHERE id = $1", order_id)

    async def cancel_order(self, order_id: int):
        """Отменить заказ"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE pending_orders SET status = 'cancelled' WHERE id = $1", order_id)

    async def get_pending_weight_for_product(self, company_id: int, product_id: int) -> float:
        """Сколько кг сейчас в пути (в pending orders)"""
        async with self.pool.acquire() as conn:
            val = await conn.fetchval("""
                SELECT SUM(i.weight_ordered) 
                FROM pending_order_items i
                JOIN pending_orders o ON i.order_id = o.id
                WHERE o.company_id = $1 AND o.status = 'pending' AND i.product_id = $2
            """, company_id, product_id)
            return float(val) if val else 0.0

    async def get_all_companies(self) -> list:
        """Получить список всех компаний (для Super-Admin)"""
        async with self.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT 
                    c.id, 
                    c.name, 
                    c.subscription_status, 
                    c.subscription_ends_at,
                    c.created_at,
                    (SELECT count(*) FROM users u WHERE u.company_id = c.id) as user_count,
                    (SELECT u.username FROM users u WHERE u.company_id = c.id AND u.role = 'admin' LIMIT 1) as owner_username
                FROM companies c
                ORDER BY c.id ASC
            """)
            return [dict(r) for r in records]
            
    async def create_company(self, name: str, trial_days: int = 14) -> dict:
        """Создать новую компанию (для Super-Admin)"""
        async with self.pool.acquire() as conn:
            # Создаем новую компанию
            record = await conn.fetchrow("""
                INSERT INTO companies (name, subscription_status, subscription_ends_at)
                VALUES ($1, 'trial', CURRENT_TIMESTAMP + interval '1 day' * $2)
                RETURNING id, name, subscription_status, subscription_ends_at
            """, name, trial_days)
            
            return dict(record) if record else None
            
    async def copy_global_products_to_company(self, target_company_id: int):
        """Скопировать все товары из системной компании (id=1) в новую компанию"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO products 
                (company_id, name_chinese, name_russian, name_internal, package_weight, units_per_box, box_weight, price_per_box, unit)
                SELECT 
                    $1, name_chinese, name_russian, name_internal, package_weight, units_per_box, box_weight, price_per_box, unit
                FROM products 
                WHERE company_id = 1
            """, target_company_id)

    async def update_company_subscription(self, company_id: int, status: str, days_to_add: int = None):
        """Обновить статус подписки и/или добавить дни"""
        async with self.pool.acquire() as conn:
            if days_to_add is not None:
                await conn.execute("""
                    UPDATE companies 
                    SET subscription_status = $1, 
                        subscription_ends_at = CURRENT_TIMESTAMP + interval '1 day' * $2
                    WHERE id = $3
                """, status, days_to_add, company_id)
            else:
                await conn.execute("""
                    UPDATE companies 
                    SET subscription_status = $1
                    WHERE id = $2
                """, status, company_id)

    async def delete_company(self, company_id: int):
        """Удалить компанию и все связанные данные"""
        if company_id == 1:
            raise ValueError("Нельзя удалить системную компанию (id=1)")
            
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Удаляем связанные данные (каскад)
                await conn.execute("DELETE FROM stock WHERE company_id = $1", company_id)
                await conn.execute("DELETE FROM supplies WHERE company_id = $1", company_id)
                await conn.execute("DELETE FROM orders_data WHERE company_id = $1", company_id)
                await conn.execute("DELETE FROM order_history WHERE company_id = $1", company_id)
                
                # Черновики инвентаризаций
                await conn.execute("""
                    DELETE FROM pending_stock_submission_items 
                    WHERE submission_id IN (SELECT id FROM pending_stock_submissions WHERE company_id = $1)
                """, company_id)
                await conn.execute("DELETE FROM pending_stock_submissions WHERE company_id = $1", company_id)
                
                # Черновики заказов
                await conn.execute("""
                    DELETE FROM pending_order_items 
                    WHERE order_id IN (SELECT id FROM pending_orders WHERE company_id = $1)
                """, company_id)
                await conn.execute("DELETE FROM pending_orders WHERE company_id = $1", company_id)
                
                # Базовые сущности
                await conn.execute("DELETE FROM products WHERE company_id = $1", company_id)
                await conn.execute("DELETE FROM users WHERE company_id = $1", company_id)
                
                # Сама компания
                await conn.execute("DELETE FROM companies WHERE id = $1", company_id)
            
