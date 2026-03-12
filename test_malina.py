import asyncio
import os
import sys

sys.path.append(os.path.abspath("."))
from dotenv import load_dotenv
from database_pg import DatabasePG
load_dotenv()

async def run():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    conn = await db.pool.acquire()
    
    for pid in [4, 6, 7]: # Малина, Клубничный, Черничный
        name = await conn.fetchval("SELECT name_russian FROM products WHERE id = $1", pid)
        print(f"--- History for {name} (ID: {pid}) ---")
        hist = await conn.fetch("SELECT date, quantity FROM stock WHERE product_id = $1 ORDER BY date DESC LIMIT 30", pid)
        for h in hist: print(f"  {h['date']}: {h['quantity']}")
        
    await conn.release(conn)
    await db.close()

if __name__ == '__main__':
    asyncio.run(run())
