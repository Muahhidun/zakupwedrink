import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def run():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    result = await conn.execute("""
        UPDATE products p
        SET is_global = TRUE
        FROM products p1
        WHERE p1.company_id = 1
          AND p1.name_internal = p.name_internal
          AND p.company_id != 1;
    """)
    print(f"Updated: {result}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
