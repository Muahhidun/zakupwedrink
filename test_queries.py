import asyncio
from database_pg import DatabasePG
import os
from dotenv import load_dotenv
from datetime import timedelta

async def run_db():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    db = DatabasePG(db_url)
    await db.init_db()
    try:
        company_id = 1
        print("1. get_latest_stock...")
        latest_stock = await db.get_latest_stock(company_id)
        latest_date = latest_stock[0]['date']
        print(f"Latest Date: {latest_date}")

        async def fetch_consumption_for_period(days: int):
            print(f"fetch_consumption_for_period({days}) start")
            start_date = latest_date - timedelta(days=days)
            print("calling get_latest_date_before...")
            real_start_date = await db.get_latest_date_before(company_id, start_date + timedelta(days=1))
            print(f"real_start_date: {real_start_date}")
            if not real_start_date:
                real_start_date = latest_date - timedelta(days=days)
            actual_days = (latest_date - real_start_date).days
            if actual_days <= 0:
                actual_days = 1
            print(f"actual_days: {actual_days}, calling calculate_consumption({company_id}, {real_start_date}, {latest_date})")
            cons_list = await db.calculate_consumption(company_id, real_start_date, latest_date)
            print("calculate_consumption done, returning")
            return actual_days, {item['product_id']: item for item in cons_list}

        print("2. fetch 30...")
        days_30, cons_30 = await fetch_consumption_for_period(30)
        print("3. fetch 60...")
        days_60, cons_60 = await fetch_consumption_for_period(60)
        print("4. fetch 90...")
        days_90, cons_90 = await fetch_consumption_for_period(90)

        print("5. loop over items...")
        for i, item in enumerate(latest_stock):
            pid = item['product_id']
            if i % 10 == 0:
                print(f"Item {i}/{len(latest_stock)}, PID {pid}")
            pending_boxes = await db.get_pending_weight_for_product(company_id, pid) / item['package_weight'] if item['package_weight'] else 0
        
        print("DONE")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(run_db())
