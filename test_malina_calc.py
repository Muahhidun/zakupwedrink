import asyncio
import os
import sys

sys.path.append(os.path.abspath("."))
from dotenv import load_dotenv
from database_pg import DatabasePG
load_dotenv()

async def run():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    from datetime import date, timedelta
    print("Running calculate_consumption directly on ID 4, 6, 7")
    today = date.today()
    res_30 = await db.calculate_consumption(1, today - timedelta(days=30), today)
    
    for pid in [4, 6, 7]:
        data = next((item for item in res_30 if item['product_id'] == pid), None)
        print(f"Product ID: {pid}")
        if data:
            print(f"  Start: {data['start_quantity']}, End: {data['end_quantity']}, Supplied: {data['supplied_quantity']}")
            print(f"  Consumed qty: {data['consumed_quantity']}")
            print(f"  Actual valid days: {data['actual_days']}")
        else:
            print(f"  No data returned.")
            
    await db.close()

if __name__ == '__main__':
    asyncio.run(run())
