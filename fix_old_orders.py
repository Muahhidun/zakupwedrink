import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()
    
    # Optional: If you want to delete the invalid old orders 
    # so they don't clog up "Ожидаемые поставки" with 0 items:
    async with db.pool.acquire() as conn:
        # Find orders with 0 items
        rows = await conn.fetch("""
            SELECT o.id, COUNT(i.id) as item_count 
            FROM pending_orders o
            LEFT JOIN pending_order_items i ON o.id = i.order_id
            WHERE o.status = 'pending'
            GROUP BY o.id
            HAVING COUNT(i.id) = 0
        """)
        
        for row in rows:
            print(f"Deleting empty pending order {row['id']}")
            await conn.execute("DELETE FROM pending_orders WHERE id = $1", row['id'])
            
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
