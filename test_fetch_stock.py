import asyncio
from database_pg import DatabasePG
import os
from dotenv import load_dotenv

async def run_db():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Set DATABASE_URL")
        return
    print("Init db...")
    db = DatabasePG(db_url)
    await db.init_db()
    print("Init done.")
    try:
        # Assuming company_id 1
        print("Calling get_stock_with_consumption(1)...")
        res = await asyncio.wait_for(db.get_stock_with_consumption(1), timeout=10)
        print("Success:", len(res))
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        print("Closing db...")
        await db.close()
        print("Closed.")

async def main():
    try:
        await asyncio.wait_for(run_db(), timeout=15)
    except Exception as e:
        print("MAIN TIMEOUT/ERROR", e)

if __name__ == '__main__':
    asyncio.run(main())
