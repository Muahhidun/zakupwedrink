import asyncio
import os
import asyncpg
from datetime import datetime, time
from dotenv import load_dotenv

load_dotenv()

async def main():
    pool = await asyncpg.create_pool(
        dsn=os.getenv('DATABASE_URL')
    )
    
    async with pool.acquire() as conn:
        for m in range(0, 60, 5):
            target_time = time(11, m)
            rows = await conn.fetch("""
                SELECT '12:00'::time >= $1::time + interval '59 minutes' 
                       AND '12:00'::time <= $1::time + interval '61 minutes' as matches
            """, target_time)
            print(f"Current time: 11:{m:02d}. matches 12:00 shift?", dict(rows[0])['matches'])
                    
    await pool.close()

if __name__ == '__main__':
    asyncio.run(main())
