import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    
    row = await conn.fetchrow("SELECT * FROM pending_stock_submissions WHERE id = 76")
    print("SUBMISSION:", dict(row) if row else None)
    
    if row:
        user_id = row['submitted_by']
        user_row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        print("USER:", dict(user_row) if user_row else None)
        
    join_row = await conn.fetchrow("""
        SELECT s.*, u.first_name, u.last_name 
        FROM pending_stock_submissions s
        JOIN users u ON s.submitted_by = u.id
        WHERE s.id = 76 AND s.company_id = 1
    """)
    print("JOIN RESULT:", dict(join_row) if join_row else None)
    
    await conn.close()

asyncio.run(main())
