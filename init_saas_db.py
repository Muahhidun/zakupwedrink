import asyncio
import asyncpg
import os
import sys

# The external URL provided by the user for Staging
DATABASE_URL = "postgresql://postgres:IfdxbfvVzYJDioOgXLDyJVUsgyXbDCHf@yamabiko.proxy.rlwy.net:24013/railway"

async def init_saas_db():
    print(f"Connecting to Staging Database...")
    try:
        # Connect to the new database
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Successfully connected to PostgreSQL.")

        # Drop existing tables if they exist (since it's a new staging DB, this is safe)
        print("Dropping old tables if they exist...")
        await conn.execute("""
            DROP TABLE IF EXISTS pending_stock_items CASCADE;
            DROP TABLE IF EXISTS pending_stock_submissions CASCADE;
            DROP TABLE IF EXISTS pending_order_items CASCADE;
            DROP TABLE IF EXISTS pending_orders CASCADE;
            DROP TABLE IF EXISTS users CASCADE;
            DROP TABLE IF EXISTS supplies CASCADE;
            DROP TABLE IF EXISTS stock CASCADE;
            DROP TABLE IF EXISTS products CASCADE;
            DROP TABLE IF EXISTS companies CASCADE;
        """)

        print("Creating tables for SaaS architecture...")

        # 1. Companies Table (Tenants)
        await conn.execute("""
            CREATE TABLE companies (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                subscription_status TEXT DEFAULT 'trial' CHECK (subscription_status IN ('trial', 'active', 'expired', 'cancelled')),
                subscription_ends_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Users Table (Linked to Company)
        await conn.execute("""
            CREATE TABLE users (
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

        # 3. Products Table (Each company has its own copy of products)
        await conn.execute("""
            CREATE TABLE products (
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
            CREATE TABLE stock (
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
            CREATE TABLE supplies (
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
            CREATE TABLE pending_orders (
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
            CREATE TABLE pending_order_items (
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
            CREATE TABLE pending_stock_submissions (
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
            CREATE TABLE pending_stock_items (
                id SERIAL PRIMARY KEY,
                submission_id INTEGER NOT NULL REFERENCES pending_stock_submissions(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                quantity REAL NOT NULL,
                weight REAL NOT NULL,
                edited_quantity REAL,
                edited_weight REAL
            )
        """)

        # Insert a default "Global Admin" system company (Optional, but good for SuperAdmin)
        await conn.execute("""
            INSERT INTO companies (id, name, subscription_status) 
            VALUES (1, 'WeDrink Super Admin', 'active')
            ON CONFLICT DO NOTHING;
        """)

        print("✅ Core Tables created successfully!")

        await conn.close()
        print("Database connection closed.")
        
    except Exception as e:
        print(f"❌ Error initializing SaaS database: {e}")

if __name__ == "__main__":
    asyncio.run(init_saas_db())
