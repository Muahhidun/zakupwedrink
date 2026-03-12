import asyncio
import asyncpg
import os

async def main():
    db_url = os.getenv('DATABASE_URL', 'postgresql://zakupwedrink:zakupwedrink123@localhost:5432/zakupwedrink')
    db_url = db_url.replace("localhost", "127.0.0.1")
    try:
        conn = await asyncpg.connect(db_url)
        users = await conn.fetch("SELECT id, username, first_name, role FROM users LIMIT 10")
        for u in users:
            print(dict(u))
        await conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
