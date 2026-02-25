import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

async def test_conn():
    load_dotenv()
    url = os.getenv('DATABASE_URL')
    print(f"Connecting to: {url}")
    db = DatabasePG(url)
    try:
        await db.init_db()
        print("✅ Connection successful!")
        products = await db.get_all_products()
        print(f"Found {len(products)} products")
        if products:
            print(f"Sample product: {products[0]['name_russian']}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(test_conn())
