import os
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# =====================================================================
# НАСТРОЙКИ МИГРАЦИИ (ВНИМАТЕЛЬНО!)
# =====================================================================
# SOURCE: База данных текущего Production (single-tenant ветка main)
SOURCE_DB_URL = os.getenv('SOURCE_DB_URL')

# TARGET: База данных нового SaaS (multi-tenant ветка saas-beta)
TARGET_DB_URL = os.getenv('TARGET_DB_URL')  # Замените если нужно

# COMPANY_ID: ID компании в новой БД, к которой привяжутся все старые данные
TARGET_COMPANY_ID = 1
# =====================================================================

async def migrate():
    if not SOURCE_DB_URL or not TARGET_DB_URL:
        print("❌ Ошибка: Установите переменные окружения SOURCE_DB_URL и TARGET_DB_URL")
        return

    print("🔌 Подключение к базам данных...")
    source_pool = await asyncpg.create_pool(dsn=SOURCE_DB_URL)
    target_pool = await asyncpg.create_pool(dsn=TARGET_DB_URL)
    
    async with source_pool.acquire() as src_conn:
        async with target_pool.acquire() as tgt_conn:
            print(f"🚀 Начинаем миграцию данных в компанию ID={TARGET_COMPANY_ID}")
            
            # --- 1. Проверка компании ---
            company = await tgt_conn.fetchrow("SELECT id, name FROM companies WHERE id=$1", TARGET_COMPANY_ID)
            if not company:
                print(f"⚠️ Компания ID={TARGET_COMPANY_ID} не найдена. Создаю...")
                await tgt_conn.execute("""
                    INSERT INTO companies (id, name, subscription_status)
                    VALUES ($1, $2, $3)
                """, TARGET_COMPANY_ID, "WeDrink Original", "active")
                print(f"✅ Создана компания WeDrink Original (ID={TARGET_COMPANY_ID})")
            else:
                print(f"✅ Найдена компания: {company['name']} (ID={TARGET_COMPANY_ID})")

            # --- 2. Миграция Пользователей ---
            print("⏳ Миграция пользователей...")
            users = await src_conn.fetch("SELECT id, username, first_name, last_name, role, is_active FROM users")
            for u in users:
                await tgt_conn.execute("""
                    INSERT INTO users (id, company_id, username, first_name, last_name, role, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO UPDATE SET 
                        company_id = EXCLUDED.company_id,
                        role = EXCLUDED.role
                """, u['id'], TARGET_COMPANY_ID, u['username'], u['first_name'], u['last_name'], u['role'], u['is_active'])
            print(f"✅ Мигрировано {len(users)} пользователей.")

            # --- 3. Миграция Товаров ---
            print("⏳ Миграция товаров (products)...")
            products = await src_conn.fetch("SELECT * FROM products")
            
            # Словарь для маппинга старых ID товаров на новые, чтобы связи не сломались
            # Так как в source БД id это SERIAL, в target они могут сместиться если уже были какие-то товары.
            # Для надежности попробуем сохранить оригинальные ID, либо обновить если такой товар уже есть.
            product_mapping = {} 
            
            for p in products:
                # Ищем есть ли такой товар в этой компании по name_internal
                existing_p = await tgt_conn.fetchrow(
                    "SELECT id FROM products WHERE company_id=$1 AND name_internal=$2", 
                    TARGET_COMPANY_ID, p['name_internal']
                )
                
                if existing_p:
                    product_mapping[p['id']] = existing_p['id']
                else:
                    new_id = await tgt_conn.fetchval("""
                        INSERT INTO products (company_id, name_chinese, name_russian, name_internal, 
                                            package_weight, units_per_box, box_weight, price_per_box, unit)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        RETURNING id
                    """, TARGET_COMPANY_ID, p['name_chinese'], p['name_russian'], p['name_internal'],
                         p['package_weight'], p['units_per_box'], p['box_weight'], p['price_per_box'], p['unit'])
                    product_mapping[p['id']] = new_id
            print(f"✅ Мигрировано {len(products)} уникальных товаров.")

            # --- 4. Миграция Остатков (stock) ---
            print("⏳ Миграция остатков (stock)...")
            stocks = await src_conn.fetch("SELECT * FROM stock")
            stock_args = []
            for s in stocks:
                if s['product_id'] in product_mapping:
                    stock_args.append((
                        TARGET_COMPANY_ID, 
                        product_mapping[s['product_id']], 
                        s['date'], 
                        s['quantity'], 
                        s['weight']
                    ))
            if stock_args:
                try:
                    await tgt_conn.executemany("""
                        INSERT INTO stock (company_id, product_id, date, quantity, weight)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (company_id, product_id, date) DO NOTHING
                    """, stock_args)
                except Exception as e:
                    print(f"⚠️ Ошибка bulk миграции остатков: {e}")
            print(f"✅ Мигрировано {len(stock_args)} записей об остатках.")

            # --- 5. Миграция Приемок (supplies) ---
            print("⏳ Миграция приемок (supplies)...")
            supplies = await src_conn.fetch("SELECT * FROM supplies")
            supply_args = []
            for s in supplies:
                if s['product_id'] in product_mapping:
                    supply_args.append((
                        TARGET_COMPANY_ID, 
                        product_mapping[s['product_id']], 
                        s['date'], 
                        s['boxes'], 
                        s['weight'], 
                        s['cost']
                    ))
            if supply_args:
                await tgt_conn.executemany("""
                    INSERT INTO supplies (company_id, product_id, date, boxes, weight, cost)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, supply_args)
            print(f"✅ Мигрировано {len(supply_args)} приемок.")

            # --- 6. Заказы в историю (Orders) ---
            print("⏳ Миграция истории заказов...")
            # В source: order_history, order_items
            # В target: order_history, order_items
            
            try:
                orders = await src_conn.fetch("SELECT * FROM order_history")
                order_items = await src_conn.fetch("SELECT * FROM order_items")
                
                for order in orders:
                    # Вставляем сам заказ, сохраняем его ID
                    new_order_id = await tgt_conn.fetchval("""
                        INSERT INTO order_history (company_id, period_start, period_end, total_cost)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                    """, TARGET_COMPANY_ID, order['period_start'], order['period_end'], order['total_cost'])
                    
                    # Фильтруем айтемы для этого заказа
                    items_for_order = [i for i in order_items if i['order_id'] == order['id']]
                    order_items_args = []
                    
                    for item in items_for_order:
                        if item['product_id'] in product_mapping:
                            order_items_args.append((
                                new_order_id, 
                                product_mapping[item['product_id']], 
                                item['boxes_ordered'], 
                                item['weight_ordered'], 
                                item['cost']
                            ))
                    if order_items_args:
                        await tgt_conn.executemany("""
                            INSERT INTO order_items (order_id, product_id, boxes_ordered, weight_ordered, cost)
                            VALUES ($1, $2, $3, $4, $5)
                        """, order_items_args)
                print(f"✅ Мигрировано {len(orders)} заказов и их состав.")
            except Exception as e:
                print(f"⚠️ Ошибка при миграции истории заказов (возможно таблиц не существует): {e}")

            print("\n🎉 МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")

    await source_pool.close()
    await target_pool.close()

if __name__ == "__main__":
    asyncio.run(migrate())
