import asyncio
import asyncpg
import os

async def migrate():
    pool = await asyncpg.create_pool('postgres://postgres:1234@postgres.railway.internal:5432/railway', min_size=1, max_size=1, ssl='require')
    async with pool.acquire() as conn:
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

if __name__ == '__main__':
    asyncio.run(migrate())
