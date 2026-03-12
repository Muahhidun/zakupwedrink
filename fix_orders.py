import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def fix_pending_orders():
    from database_pg import DatabasePG
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    async with db.pool.acquire() as conn:
        print("Fetching pending order items with bad weights...")
        rows = await conn.fetch("""
            SELECT i.id, i.product_id, i.boxes_ordered, i.weight_ordered, 
                   p.box_weight, p.name_russian
            FROM pending_order_items i
            JOIN products p ON i.product_id = p.id
            JOIN pending_orders o ON i.order_id = o.id
            WHERE o.status = 'pending'
        """)
        
        updates = 0
        for r in rows:
            expected_weight = r["boxes_ordered"] * r["box_weight"]
            
            # Simple float comparison with tolerance
            if abs(r["weight_ordered"] - expected_weight) > 0.01:
                print(f"Fixing {r['name_russian']}: ordered={r['weight_ordered']}, expected={expected_weight}")
                await conn.execute("""
                    UPDATE pending_order_items 
                    SET weight_ordered = $1 
                    WHERE id = $2
                """, expected_weight, r["id"])
                updates += 1
                
        print(f"Fixed {updates} pending order items.")
        
    await db.close()

if __name__ == "__main__":
    asyncio.run(fix_pending_orders())
