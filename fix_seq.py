import asyncio
from database_pg import DatabasePG
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    db = DatabasePG()
    await db.connect()
    
    async with db.pool.acquire() as conn:
        # Check current max id
        max_id = await conn.fetchval("SELECT MAX(id) FROM companies")
        print(f"Max company ID: {max_id}")
        
        # Reset sequence
        if max_id:
            await conn.execute(f"SELECT setval('companies_id_seq', {max_id}, true)")
            print(f"Sequence set to {max_id}")
            
    await db.close()

if __name__ == '__main__':
    asyncio.run(main())
