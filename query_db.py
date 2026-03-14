import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from database_pg import DatabasePG

async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()
    
    current_datetime = datetime.now(ZoneInfo("Asia/Almaty"))
    target_date = current_datetime.date()
    target_time = current_datetime.replace(second=0, microsecond=0).time()
    
    print(f"Current Almaty time: {current_datetime}")
    print(f"Target time: {target_time}")
    
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id, s.start_time, $2::time as param_time, 
                   $2::time + interval '59 minutes' as min_time,
                   $2::time + interval '61 minutes' as max_time
            FROM users u
            JOIN shifts s ON u.id = s.user_id
            WHERE u.is_active = TRUE AND s.date = $1
        """, target_date, target_time)
        
        print("\nAll shifts for today:")
        for r in rows:
            print(dict(r))
            
    await db.close()

if __name__ == '__main__':
    asyncio.run(main())
