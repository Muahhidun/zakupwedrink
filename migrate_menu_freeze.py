import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def run_migration():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    print("Adding is_global column...")
    await conn.execute("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS is_global BOOLEAN DEFAULT FALSE;
    """)
    print("Column added.")
    
    print("Setting is_global=TRUE for company_id 1 (Platform Admin)...")
    result = await conn.execute("""
        UPDATE products SET is_global = TRUE WHERE company_id = 1;
    """)
    print(f"Updated: {result}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
