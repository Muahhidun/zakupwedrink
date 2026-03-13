import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    async with db.pool.acquire() as conn:
        print('Modifying constraint...')
        try:
            # Drop the old global constraint
            await conn.execute('ALTER TABLE products DROP CONSTRAINT IF EXISTS products_name_internal_key CASCADE;')
            print('Old constraint dropped.')
        except Exception as e:
            print(f'Warning dropping constraint: {e}')
        
        try:
            # Add the correct composite unique constraint
            await conn.execute('ALTER TABLE products ADD CONSTRAINT products_company_id_name_internal_key UNIQUE (company_id, name_internal);')
            print('New composite constraint added.')
        except Exception as e:
            print(f'Warning adding constraint: {e}')
            
asyncio.run(main())
