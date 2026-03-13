import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    try:
        res = await db.create_company("Test Company", 14)
        print("Success:", res)
    except Exception as e:
        print("Error:", repr(e))
    finally:
        await db.close()

asyncio.run(main())
