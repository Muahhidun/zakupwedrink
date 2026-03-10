import asyncio
import asyncpg
import json

async def run():
    # Use the public proxy URL from earlier context for testing
    conn = await asyncpg.connect("postgresql://postgres:pnqmXzGSWnQVgSsdMUxQKmEcffPBmyLB@tramway.proxy.rlwy.net:34608/railway")
    rows = await conn.fetch("SELECT id, name_russian, is_active FROM products WHERE company_id = 1")
    print(f"Total products: {len(rows)}")
    active = [r['name_russian'] for r in rows if r['is_active']]
    inactive = [r['name_russian'] for r in rows if not r['is_active']]
    print(f"Active count: {len(active)}")
    print(f"Inactive count: {len(inactive)}")
    print(f"Inactive products: {inactive[:10]}")
    
    rows2 = await conn.fetch("SELECT count(*) FROM stock WHERE company_id = 1")
    print(f"Total stock records: {rows2[0]['count']}")
    
    # Get latest stock
    rows3 = await conn.fetch("""
        WITH RankedStock AS (
            SELECT product_id, quantity, weight, date,
                   ROW_NUMBER() OVER(PARTITION BY product_id ORDER BY date DESC) as rn
            FROM stock
            WHERE company_id = 1
        )
        SELECT p.name_russian, rs.quantity, rs.weight, rs.date 
        FROM RankedStock rs
        JOIN products p ON rs.product_id = p.id
        WHERE rs.rn = 1 AND p.is_active = TRUE
    """)
    print(f"\nLatest active stock items: {len(rows3)}")
    for r in rows3[:5]:
        print(r['name_russian'], r['quantity'], r['date'])
        
    await conn.close()

asyncio.run(run())
