import asyncio
from database_pg import DatabasePG
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    db = DatabasePG()
    await db.connect()
    
    async with db.pool.acquire() as conn:
        users = await conn.fetch("SELECT id, username, role, company_id FROM users WHERE role='admin'")
        for u in users:
            print(f"User: {dict(u)}")
        
        # Update the first admin to have company_id = 1
        if len(users) > 0:
            await conn.execute("UPDATE users SET company_id = 1 WHERE id = $1", users[0]['id'])
            print(f"Updated company_id to 1 for user {users[0]['id']}")
            
    await db.close()

if __name__ == '__main__':
    asyncio.run(main())
