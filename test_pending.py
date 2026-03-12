import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv('DATABASE_URL'))
    await db.init_db()
    company_id = 1
    
    # Check if order 4 has items now? No, we need to create a new one.
    order_id = await db.create_pending_order(company_id, 15000, "Test WebApp Flow")
    
    # Add a mock item (1 box of product 1 = weight 3.0)
    await db.add_item_to_order(order_id, 1, 1, 3.0, 15000)
    
    pending_weights = await db.get_all_pending_weights(company_id)
    print("Pending weights after insert:", pending_weights)
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
