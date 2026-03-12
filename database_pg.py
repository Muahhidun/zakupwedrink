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
            ssl='require',
            statement_cache_size=0,
            max_cached_statement_lifetime=0
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
            
            # Migration: Add shift columns if they are missing
            await conn.execute("""
                ALTER TABLE companies
                ADD COLUMN IF NOT EXISTS default_shift_start TIME,
                ADD COLUMN IF NOT EXISTS default_shift_end TIME;
            """)

            # 2. Users Table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    real_name TEXT,
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
                    is_active BOOLEAN DEFAULT TRUE,
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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_stock_items (
                    id SERIAL PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES pending_stock_submissions(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    quantity REAL NOT NULL,
                    weight REAL NOT NULL,
                    edited_quantity REAL,
                    edited_quantity REAL,
                    edited_weight REAL
                )
            """)

            # 10. Shifts (Employee Schedule)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    start_time TIME,
                    end_time TIME,
                    status VARCHAR(50) DEFAULT 'assigned',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 10. Shifts (Employee Schedule)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    start_time TIME,
                    end_time TIME,
                    status VARCHAR(50) DEFAULT 'assigned',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 11. Supplier Debts (Missing items from deliveries)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS supplier_debts (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                    boxes REAL NOT NULL,
                    weight REAL NOT NULL,
                    cost REAL NOT NULL,
                    status VARCHAR(50) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP NULL
                )
            """)

        # Безопасное добавление новых колонок (миграция для существующих баз)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS notes TEXT")
        except Exception as e:
            print(f"Migration error for companies.notes: {e}")

        # Таблица для личных заметок по компании (отдельные карточки)
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS company_notes (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    async def get_all_products(self, company_id: int, active_only: bool = False) -> List[Dict]:
        """Получить все товары компании (либо только активные)"""
        async with self.pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch("SELECT * FROM products WHERE company_id = $1 AND is_active = TRUE ORDER BY name_internal", company_id)
            else:
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

    async def toggle_product_status(self, company_id: int, product_id: int, is_active: bool) -> bool:
        """Включить или отключить ингредиент"""
        async with self.pool.acquire() as conn:
            # Возвращает команду вроде "UPDATE 1", если успешно
            result = await conn.execute(
                "UPDATE products SET is_active = $1 WHERE company_id = $2 AND id = $3",
                is_active, company_id, product_id
            )
            return result == "UPDATE 1"

    async def add_stock(self, company_id: int, product_id: int, date, quantity: float, weight: float):
        """Добавить/обновить остаток на дату"""
        if isinstance(date, str):
            from datetime import datetime
            date = datetime.strptime(date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO stock (company_id, product_id, date, quantity, weight)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT(product_id, date)
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

    async def update_product_price(self, company_id: int, product_id: int, new_price: float):
        """Обновить стоимость за коробку/литр товара на основе новой поставки"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE products
                SET price_per_box = $1
                WHERE id = $2 AND company_id = $3
            """, new_price, product_id, company_id)

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
        """Получить самые свежие остатки по каждому товару. Если товар пропущен в последней ревизии, считаем его равным 0."""
        async with self.pool.acquire() as conn:
            # Получаем дату самой последней ревизии по всей компании
            global_latest = await conn.fetchval("SELECT MAX(date) FROM stock WHERE company_id = $1", company_id)
            if not global_latest:
                from datetime import date
                global_latest = date.today()

            rows = await conn.fetch("""
                WITH RankedStock AS (
                    SELECT product_id, quantity, weight, date,
                           ROW_NUMBER() OVER(PARTITION BY product_id ORDER BY date DESC) as rn
                    FROM stock
                    WHERE company_id = $1
                )
                SELECT p.id as product_id, 
                       CASE WHEN rs.date >= $2 THEN rs.quantity ELSE 0 END as quantity, 
                       CASE WHEN rs.date >= $2 THEN rs.weight ELSE 0 END as weight,
                       $2 as date,
                       p.name_chinese, p.name_russian, p.name_internal,
                       p.package_weight, p.units_per_box, p.box_weight, p.price_per_box, p.unit
                FROM products p
                LEFT JOIN RankedStock rs ON p.id = rs.product_id AND rs.rn = 1
                WHERE p.company_id = $1 AND p.is_active = TRUE
                ORDER BY p.name_internal
            """, company_id, global_latest)
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
        """Определяет средний расход товара за период с учетом пропусков и пустых полок"""
        from datetime import datetime, date
        from collections import defaultdict

        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        async with self.pool.acquire() as conn:
            # 1. Fetch all products to guarantee we return a row for each
            products_rows = await conn.fetch("""
                SELECT id, name_internal, name_russian, price_per_box, unit, box_weight, units_per_box
                FROM products WHERE company_id = $1 AND is_active = TRUE
            """, company_id)
            products = {r['id']: dict(r) for r in products_rows}

            # 2. Fetch all raw historical stock for the period
            stock_rows = await conn.fetch("""
                SELECT product_id, date, quantity, weight
                FROM stock
                WHERE company_id = $1 AND date >= $2 AND date <= $3
                ORDER BY product_id, date ASC
            """, company_id, start_date, end_date)

            # Organize stock history by product
            history_by_product = defaultdict(list)
            for r in stock_rows:
                history_by_product[r['product_id']].append(dict(r))

            # 3. Fetch all supplies for the period
            supply_rows = await conn.fetch("""
                SELECT product_id, date, boxes, weight
                FROM supplies
                WHERE company_id = $1 AND date > $2 AND date <= $3
            """, company_id, start_date, end_date)

            supplies_by_product = defaultdict(list)
            for r in supply_rows:
                supplies_by_product[r['product_id']].append(dict(r))

        results = []
        for pid, prod in products.items():
            history = history_by_product[pid]
            supplies = supplies_by_product[pid]

            # If there's 0 or 1 stock records, we can't calculate a delta
            if len(history) < 2:
                prod_copy = dict(prod)
                prod_copy['product_id'] = pid
                prod_copy['start_quantity'] = history[0]['quantity'] if history else 0.0
                prod_copy['end_quantity'] = history[-1]['quantity'] if history else 0.0
                prod_copy['supplied_quantity'] = sum(s['boxes'] for s in supplies)
                prod_copy['consumed_quantity'] = 0.0
                prod_copy['consumed_weight'] = 0.0
                prod_copy['actual_days'] = 1 # Prevent ZeroDivisionError downstream
                results.append(prod_copy)
                continue

            total_consumed_qty = 0.0
            total_consumed_weight = 0.0
            total_valid_days = 0

            # Step 4. Run the day-by-day smart consumption loop
            for i in range(len(history) - 1):
                cur_rec = history[i]
                nxt_rec = history[i+1]

                days_between = (nxt_rec['date'] - cur_rec['date']).days
                if days_between <= 0: continue

                # If BOTH the start and end of this specific gap is 0, we assume the product was 
                # completely out of stock during this time. We discard these days from the average.
                # Note: If a supply arrived during this gap, the end stock wouldn't be 0.
                if cur_rec['quantity'] <= 0 and nxt_rec['quantity'] <= 0:
                    continue

                # Find all supplies that arrived exactly within this gap
                gap_supplies_qty = sum(s['boxes'] for s in supplies if cur_rec['date'] < s['date'] <= nxt_rec['date'])
                gap_supplies_wgt = sum(s['weight'] for s in supplies if cur_rec['date'] < s['date'] <= nxt_rec['date'])

                consumed_qty = cur_rec['quantity'] + gap_supplies_qty - nxt_rec['quantity']
                consumed_wgt = cur_rec['weight'] + gap_supplies_wgt - nxt_rec['weight']
                
                # Anomaly Filtering:
                # If staff manually added stock without a supply, consumed_qty will be negative.
                # We skip this interval completely to prevent dragging the average down.
                if consumed_qty < 0:
                    continue

                total_valid_days += days_between
                total_consumed_qty += consumed_qty
                total_consumed_weight += consumed_wgt

            # Build result
            prod_copy = dict(prod)
            prod_copy['product_id'] = pid
            prod_copy['start_quantity'] = history[0]['quantity']
            prod_copy['end_quantity'] = history[-1]['quantity']
            prod_copy['supplied_quantity'] = sum(s['boxes'] for s in supplies)
            prod_copy['consumed_quantity'] = total_consumed_qty
            prod_copy['consumed_weight'] = total_consumed_weight
            prod_copy['actual_days'] = total_valid_days if total_valid_days > 0 else 1

            results.append(prod_copy)

        return results


    async def get_stock_with_consumption(self, company_id: int) -> List[Dict]:
        """Получить текущие остатки и средний (МАКСИМАЛЬНЫЙ из 30/60/90) умный расход"""
        from datetime import timedelta
        latest_stock = await self.get_latest_stock(company_id)
        if not latest_stock:
            return []
            
        latest_date = latest_stock[0]['date']
        
        # Helper to get consumption for a specific lookback period
        async def fetch_consumption_for_period(days: int):
            start_date = latest_date - timedelta(days=days)
            real_start_date = await self.get_latest_date_before(company_id, start_date + timedelta(days=1))
            
            if not real_start_date:
                # Если данных за этот период (e.g. 30 дней) еще нет (новая точка),
                # берем самую ПЕРВУЮ доступную дату ревизии.
                real_start_date = await self.get_earliest_stock_date(company_id)
                # Если истории нет совсем или первая точка совпадает с текущей
                if not real_start_date or real_start_date >= latest_date:
                    return 1, {}
            
            actual_days = (latest_date - real_start_date).days
            if actual_days <= 0:
                actual_days = 1
            cons_list = await self.calculate_consumption(company_id, real_start_date, latest_date)
            return actual_days, {item['product_id']: item for item in cons_list}

        # Fetch tiered consumption data
        days_30, cons_30 = await fetch_consumption_for_period(30)
        days_60, cons_60 = await fetch_consumption_for_period(60)
        days_90, cons_90 = await fetch_consumption_for_period(90)

        # Bulk fetch pending orders
        pending_weights = await self.get_all_pending_weights(company_id)

        for item in latest_stock:
            pid = item['product_id']
            # Get pending weight from map
            pending_w = pending_weights.get(pid, 0.0)
            pending_boxes = pending_w / item['package_weight'] if item['package_weight'] else 0
            total_available = item['quantity'] + pending_boxes

            # Evaluate consumption tiers for all 3 periods and take the MAXIMUM daily qty
            cons_30_data = cons_30.get(pid)
            cons_60_data = cons_60.get(pid)
            cons_90_data = cons_90.get(pid)
            
            avg_30 = (cons_30_data['consumed_quantity'] / cons_30_data['actual_days']) if cons_30_data and cons_30_data['consumed_quantity'] > 0 else 0
            avg_60 = (cons_60_data['consumed_quantity'] / cons_60_data['actual_days']) if cons_60_data and cons_60_data['consumed_quantity'] > 0 else 0
            avg_90 = (cons_90_data['consumed_quantity'] / cons_90_data['actual_days']) if cons_90_data and cons_90_data['consumed_quantity'] > 0 else 0
            
            avg_w_30 = (cons_30_data['consumed_weight'] / cons_30_data['actual_days']) if cons_30_data and cons_30_data['consumed_weight'] > 0 else 0
            avg_w_60 = (cons_60_data['consumed_weight'] / cons_60_data['actual_days']) if cons_60_data and cons_60_data['consumed_weight'] > 0 else 0
            avg_w_90 = (cons_90_data['consumed_weight'] / cons_90_data['actual_days']) if cons_90_data and cons_90_data['consumed_weight'] > 0 else 0

            max_avg_qty = max(avg_30, avg_60, avg_90)
            
            # We also need the weight corresponding to the max qty
            max_avg_w = 0
            if max_avg_qty > 0:
                if max_avg_qty == avg_30:
                    max_avg_w = avg_w_30
                elif max_avg_qty == avg_60:
                    max_avg_w = avg_w_60
                else:
                    max_avg_w = avg_w_90

            if max_avg_qty > 0:
                item['avg_daily_consumption_qty'] = round(max_avg_qty, 2)
                item['avg_daily_consumption_weight'] = round(max_avg_w, 2)
                item['days_remaining'] = round(item['quantity'] / max_avg_qty, 1)
                item['total_days_remaining'] = round(total_available / max_avg_qty, 1)
            else:
                item['avg_daily_consumption_qty'] = 0
                item['avg_daily_consumption_weight'] = 0
                item['days_remaining'] = 999
                item['total_days_remaining'] = 999
                
            item['pending_boxes'] = pending_boxes
            item['pending_weight'] = pending_w

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

    async def get_earliest_stock_date(self, company_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MIN(date) FROM stock WHERE company_id = $1", company_id)

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
        """Получить список всех сотрудников франшизы (только активных)"""
        async with self.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT id, username, first_name, last_name, real_name, role, is_active, created_at, last_seen
                FROM users 
                WHERE company_id = $1 AND is_active = TRUE
                ORDER BY created_at DESC
            """, company_id)
            return [dict(r) for r in records]

    async def get_archived_users_by_company(self, company_id: int) -> List[Dict]:
        """Получить список всех удаленных сотрудников (неактивных)"""
        async with self.pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT id, username, first_name, last_name, real_name, role, is_active, created_at, last_seen
                FROM users 
                WHERE company_id = $1 AND is_active = FALSE
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

    async def update_user_real_name(self, user_id: int, real_name: str):
        """Обновление реального ФИО пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET real_name = $1 WHERE id = $2", real_name, user_id)

    async def set_user_role(self, user_id: int, role: str):
        """Установить роль пользователю"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET role = $2 WHERE id = $1", user_id, role)

    async def list_users_with_roles(self, company_id: int) -> List[Dict]:
        """Список всех активных пользователей компании"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, first_name, last_name, username, role, last_seen 
                FROM users 
                WHERE company_id = $1 AND is_active = TRUE
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
        """Получить информацию о пользователе со статусом активности"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT u.id, u.first_name, u.last_name, u.username, u.role, u.company_id, u.is_active, c.name as company_name
                FROM users u
                LEFT JOIN companies c ON u.company_id = c.id
                WHERE u.id = $1
            """, user_id)
            return dict(row) if row else {}
            
    async def remove_user(self, user_id: int, company_id: int) -> bool:
        """Пометить пользователя как неактивного (удален) из компании"""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE users 
                SET is_active = FALSE, role = 'employee'
                WHERE id = $1 AND company_id = $2 AND role != 'superadmin'
            """, user_id, company_id)
            return result.endswith('1')

    async def restore_user(self, user_id: int, company_id: int) -> bool:
        """Восстановить пользователя обратно в штат (роль employee)"""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE users 
                SET is_active = TRUE, role = 'employee'
                WHERE id = $1 AND company_id = $2
            """, user_id, company_id)
            return result.endswith('1')

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
                    ON CONFLICT (submitted_by, submission_date) 
                    DO UPDATE SET status = 'pending', created_at = CURRENT_TIMESTAMP
                    RETURNING id
                """, company_id, user_id, date)

                # Удаляем предыдущие позиции (если это перезапись)
                await conn.execute("DELETE FROM pending_stock_items WHERE submission_id = $1", sub_id)

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

    async def get_all_submissions(self, company_id: int) -> List[Dict]:
        """Получить все заявки (для web-панели)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT ps.*, u.username, u.first_name, u.last_name, u.real_name,
                       COUNT(psi.id) as items_count
                FROM pending_stock_submissions ps
                JOIN users u ON ps.submitted_by = u.id
                LEFT JOIN pending_stock_items psi ON ps.id = psi.submission_id
                WHERE ps.company_id = $1
                GROUP BY ps.id, u.username, u.first_name, u.last_name, u.real_name
                ORDER BY ps.created_at DESC
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
                        ON CONFLICT(product_id, date) DO UPDATE 
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

    async def resolve_order_without_insert(self, order_id: int):
        """Отметить заказ как выполненный (например при ручной приемке) без автоматического добавления в supplies"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE pending_orders SET status = 'completed' WHERE id = $1", order_id)

    async def cancel_order(self, order_id: int):
        """Отменить заказ"""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE pending_orders SET status = 'cancelled' WHERE id = $1", order_id)

    async def add_supplier_debt(self, company_id: int, product_id: int, boxes: float, weight: float, cost: float) -> int:
        """Добавить недовезенный товар в долги поставщика"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("""
                INSERT INTO supplier_debts (company_id, product_id, boxes, weight, cost)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, company_id, product_id, boxes, weight, cost)
            return result

    async def get_active_debts(self, company_id: int) -> List[Dict]:
        """Получить все незакрытые долги поставщиков"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT d.*, p.name_internal, p.name_russian, p.package_weight, p.units_per_box
                FROM supplier_debts d
                JOIN products p ON d.product_id = p.id
                WHERE d.company_id = $1 AND d.status = 'active'
                ORDER BY d.created_at ASC
            """, company_id)
            return [dict(row) for row in rows]

    async def resolve_supplier_debt(self, debt_id: int):
        """Закрыть долг (товар был доставлен) - переносит в supplies и stock"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                debt = await conn.fetchrow("SELECT * FROM supplier_debts WHERE id = $1 AND status = 'active'", debt_id)
                if not debt:
                    return

                company_id = debt['company_id']
                from datetime import date
                today = date.today()

                # 1. Добавляем в приход (supplies)
                await conn.execute("""
                    INSERT INTO supplies (company_id, product_id, date, boxes, weight, cost)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, company_id, debt['product_id'], today, debt['boxes'], debt['weight'], debt['cost'])

                # 2. Обновляем статус долга
                await conn.execute("""
                    UPDATE supplier_debts 
                    SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP 
                    WHERE id = $1
                """, debt_id)

    async def get_all_pending_weights(self, company_id: int) -> Dict[int, float]:
        """Получить вес в пути (pending orders) для всех товаров компани"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT i.product_id, SUM(i.weight_ordered) as total_weight
                FROM pending_order_items i
                JOIN pending_orders o ON i.order_id = o.id
                WHERE o.company_id = $1 AND o.status = 'pending'
                GROUP BY i.product_id
            """, company_id)
            return {row['product_id']: float(row['total_weight']) for row in rows}

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

    async def get_company_details(self, company_id: int) -> Optional[Dict]:
        """Получить детальную информацию о компании, включая заметки (notes)"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, name, subscription_status, subscription_ends_at, notes, created_at,
                       default_shift_start, default_shift_end
                FROM companies
                WHERE id = $1
            """, company_id)
            return dict(row) if row else None

    async def update_company_details(self, company_id: int, name: str, default_shift_start: str = None, default_shift_end: str = None) -> bool:
        """Обновить название компании и стандартные часы смены"""
        from datetime import datetime
        start_time = None
        if isinstance(default_shift_start, str) and default_shift_start:
            default_shift_start = default_shift_start.replace('.', ':')
            start_time = datetime.strptime(default_shift_start, '%H:%M').time()
            
        end_time = None
        if isinstance(default_shift_end, str) and default_shift_end:
            default_shift_end = default_shift_end.replace('.', ':')
            end_time = datetime.strptime(default_shift_end, '%H:%M').time()
            
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE companies
                SET name = $1, default_shift_start = $2, default_shift_end = $3
                WHERE id = $4
            """, name, start_time, end_time, company_id)
            return result.startswith("UPDATE 1")

    async def update_company_notes(self, company_id: int, notes: str):
        """Обновить личные заметки администратора франшизы"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE companies
                SET notes = $1
                WHERE id = $2
            """, notes, company_id)

    # --- Новые методы для раздельных заметок на дашборде ---
    async def get_dashboard_notes(self, company_id: int) -> list[dict]:
        """Получить все заметки на дашборде"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, content, created_at
                FROM company_notes
                WHERE company_id = $1
                ORDER BY created_at DESC
            """, company_id)
            return [dict(row) for row in rows]
            
    async def add_dashboard_note(self, company_id: int, content: str) -> int:
        """Добавить новую заметку на дашборд"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO company_notes (company_id, content)
                VALUES ($1, $2)
                RETURNING id
            """, company_id, content)
            
    async def update_dashboard_note(self, note_id: int, company_id: int, content: str) -> bool:
        """Редактировать существующую заметку"""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE company_notes
                SET content = $1
                WHERE id = $2 AND company_id = $3
            """, content, note_id, company_id)
            return result == "UPDATE 1"
            
    async def delete_dashboard_note(self, note_id: int, company_id: int) -> bool:
        """Удалить заметку"""
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM company_notes
                WHERE id = $1 AND company_id = $2
            """, note_id, company_id)
            return result == "DELETE 1"

    async def get_recent_activity(self, company_id: int, limit: int = 5) -> List[Dict]:
        """Получить ленту последних событий (приемки, заявки, заказы)"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT 
                    'supply' as type,
                    'Приемка товаров' as title,
                    'Принято товаров на сумму ' || CAST(SUM(cost) AS text) || ' ₸' as description,
                    MAX(created_at) as created_at
                FROM supplies
                WHERE company_id = $1
                GROUP BY date

                UNION ALL

                SELECT 
                    'submission' as type,
                    'Заявка на остатки' as title,
                    'Статус: ' || status as description,
                    created_at
                FROM pending_stock_submissions
                WHERE company_id = $1

                UNION ALL

                SELECT 
                    'order' as type,
                    'Сформирован заказ' as title,
                    'Сумма заказа: ' || CAST(total_cost AS text) || ' ₸' as description,
                    created_at
                FROM pending_orders
                WHERE company_id = $1

                ORDER BY created_at DESC
                LIMIT $2
            """, company_id, limit)
            return [dict(row) for row in rows]

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

    # ==========================
    # Shift Schedule (Staff)
    # ==========================
    
    async def get_shifts(self, company_id: int, start_date: str, end_date: str) -> list:
        from datetime import datetime
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.id, s.user_id, s.date, s.start_time, s.end_time, s.company_id,
                       u.first_name, u.last_name, u.real_name, u.role
                FROM shifts s
                JOIN users u ON s.user_id = u.id
                WHERE s.company_id = $1 AND s.date >= $2 AND s.date <= $3
                ORDER BY s.date, s.start_time
            """, company_id, start_date, end_date)
            return [dict(r) for r in rows]

    async def assign_shift(self, company_id: int, user_id: int, date, start_time: str = None, end_time: str = None) -> int:
        from datetime import datetime
        if isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()
            
        parsed_start = None
        if isinstance(start_time, str) and start_time:
            start_time = start_time.replace('.', ':')
            parsed_start = datetime.strptime(start_time, '%H:%M').time()
            
        parsed_end = None
        if isinstance(end_time, str) and end_time:
            end_time = end_time.replace('.', ':')
            parsed_end = datetime.strptime(end_time, '%H:%M').time()
            
        async with self.pool.acquire() as conn:
            shift_id = await conn.fetchval("""
                INSERT INTO shifts (company_id, user_id, date, start_time, end_time)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (company_id, user_id, date) 
                DO UPDATE SET start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time
                RETURNING id
            """, company_id, user_id, date, parsed_start, parsed_end)
            return shift_id

    async def delete_shift(self, company_id: int, shift_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM shifts WHERE id = $1 AND company_id = $2", shift_id, company_id)
            return result.startswith("DELETE 1")

    async def get_all_active_users(self) -> list:
        """Fallback method for getting all active users if shift isn't used"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users WHERE is_active = TRUE")
            return [row['id'] for row in rows]

    async def get_active_users_for_reminder(self, company_id: int, date_str: str) -> list:
        """
        Возвращает список ID активных пользователей для напоминаний.
        Если на этот день есть смены, возвращает только тех, у кого смена.
        Если смен нет (расписание не ведется), возвращает всех активных сотрудников компании.
        """
        async with self.pool.acquire() as conn:
            shifts_today = await conn.fetchval("""
                SELECT COUNT(*) FROM shifts WHERE company_id = $1 AND date = $2
            """, company_id, date_str)
            
            if shifts_today > 0:
                rows = await conn.fetch("""
                    SELECT u.id 
                    FROM users u
                    JOIN shifts s ON u.id = s.user_id
                    WHERE u.is_active = TRUE AND s.company_id = $1 AND s.date = $2
                """, company_id, date_str)
            else:
                rows = await conn.fetch("""
                    SELECT id FROM users WHERE is_active = TRUE AND company_id = $1
                """, company_id)
                
            return [row['id'] for row in rows]

    async def get_users_with_shift_in_one_hour(self, current_datetime) -> list:
        """
        Возвращает список ID пользователей, у которых смена начинается ровно через 1 час.
        """
        target_date = current_datetime.date()
        target_time = current_datetime.replace(second=0, microsecond=0).time()
        
        # Мы ищем смены, где start_time равен target_time + 1 час.
        # Планировщик дергает эту функцию каждые 5 минут. Нам нужно "поймать" смену
        # ровно за 60 минут до начала (плюс/минус 1 минута на погрешность запуска).
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, s.start_time
                FROM users u
                JOIN shifts s ON u.id = s.user_id
                WHERE u.is_active = TRUE 
                  AND s.date = $1 
                  AND s.start_time >= $2::time + interval '59 minutes'
                  AND s.start_time <= $2::time + interval '61 minutes'
            """, target_date, target_time)
            
            return [dict(row) for row in rows]
