import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def main():
    conn = await asyncpg.connect("postgresql://postgres:IfdxbfvVzYJDioOgXLDyJVUsgyXbDCHf@yamabiko.proxy.rlwy.net:24013/railway")
    result = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'users';")
    print([r['column_name'] for r in result])
    
    users = await conn.fetch("SELECT * FROM users LIMIT 2")
    print(users)
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
