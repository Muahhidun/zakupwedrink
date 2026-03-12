import asyncio
import os
import sys

# Добавляем путь к закупвединк
sys.path.append(os.path.abspath("."))

from dotenv import load_dotenv
from database_pg import DatabasePG
load_dotenv()

async def get_test():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    stock_data = await db.get_stock_with_consumption(1)
    
    for item in stock_data:
        if item['product_id'] in [4, 6, 7]:
            print(f"Product: {item['name_russian']} (ID: {item['product_id']})")
            print(f"  Current Qty: {item['quantity']}")
            print(f"  Pending boxes: {item['pending_boxes']} (Weight: {item['pending_weight']})")
            print(f"  Avg Daily Qty Consumption: {item['avg_daily_consumption_qty']}")
            print(f"  Days Remaining: {item['days_remaining']}")

    await db.close()

if __name__ == "__main__":
    asyncio.run(get_test())
