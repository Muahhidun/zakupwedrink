import asyncio
import asyncpg
import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

async def migrate():
    print(f"Connecting to {DATABASE_URL}...")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, ssl='require')
    async with pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE companies ADD COLUMN notes TEXT")
            print("Added notes")
        except Exception as e:
            print("Already exists notes", e)
        
        try:
            await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_start TIME")
            print("Added default_shift_start")
        except Exception as e:
            print("Already exists default_shift_start", e)
        
        try:
            await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_end TIME")
            print("Added default_shift_end")
        except Exception as e:
            print("Already exists default_shift_end", e)
            
    await pool.close()
    print("Migration complete.")

if __name__ == '__main__':
    asyncio.run(migrate())
