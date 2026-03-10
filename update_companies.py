import asyncio
from database_pg import DatabasePG
import os

async def migrate():
    db = DatabasePG('postgres://postgres:1234@postgres.railway.internal:5432/railway')
    await db.init()
    async with db.pool.acquire() as conn:
        try:
            await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_start TIME")
        except Exception as e:
            print("Already exists default_shift_start", e)
        try:
            await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_end TIME")
        except Exception as e:
            print("Already exists default_shift_end", e)
    await db.close()

if __name__ == '__main__':
    asyncio.run(migrate())
