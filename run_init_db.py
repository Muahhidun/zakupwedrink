import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def run_init():
    DATABASE_URL = os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        print("DATABASE_URL not found!")
        return
    db = DatabasePG(DATABASE_URL)
    print("Running init_db...")
    await db.init_db()
    print("Done!")
    await db.close()

if __name__ == "__main__":
    asyncio.run(run_init())
