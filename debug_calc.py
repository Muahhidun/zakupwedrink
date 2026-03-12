import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def get_test():
    from database_pg import DatabasePG
    from utils.calculations import calculate_order
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    products = await calculate_order(db, 1, 30)
    for p in products["items"]:
        if "Апельсиновый" in p["name"]:
            print(f"[{p['name']}] needed: {p['needed_quantity']}, boxes: {p['order_boxes']}, current: {p['current_stock']}")
            
        if "Фасоль" in p["name"]:
            print(f"[{p['name']}] needed: {p['needed_quantity']}, boxes: {p['order_boxes']}, current: {p['current_stock']}")

    await db.close()

if __name__ == "__main__":
    asyncio.run(get_test())
