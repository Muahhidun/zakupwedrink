import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def main():
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"), ssl='require')
    async with pool.acquire() as conn:
        try:
            await conn.execute('ALTER TABLE companies ADD COLUMN IF NOT EXISTS notes TEXT;')
            print("Successfully added notes column to companies.")
        except Exception as e:
            print(f"Error adding notes column: {e}")
    await pool.close()

if __name__ == '__main__':
    asyncio.run(main())
