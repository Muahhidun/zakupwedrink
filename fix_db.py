import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    db_url = os.getenv("DATABASE_URL")
    conn = await asyncpg.connect(db_url, ssl='require')
    
    print("Fixing users table...")
    try:
        await conn.execute("ALTER TABLE users ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE")
        print("users.company_id added successfully.")
    except Exception as e:
        print(f"Error (might exist already): {e}")

    try:
        await conn.execute("ALTER TABLE products ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE")
        print("products.company_id added successfully.")
    except Exception as e:
        print(f"Error: {e}")

    try:
        await conn.execute("ALTER TABLE stock ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE")
        print("stock.company_id added successfully.")
    except Exception as e:
        print(f"Error: {e}")
        
    try:
        await conn.execute("ALTER TABLE supplies ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE")
        print("supplies.company_id added successfully.")
    except Exception as e:
        print(f"Error: {e}")

    try:
        await conn.execute("ALTER TABLE pending_orders ADD COLUMN company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE")
        print("pending_orders.company_id added successfully.")
    except Exception as e:
        print(f"Error: {e}")
        
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
