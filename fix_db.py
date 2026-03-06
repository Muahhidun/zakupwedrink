import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    db_url = os.getenv("DATABASE_URL")
    print(f"Connecting to {db_url}")
    conn = await asyncpg.connect(db_url, ssl='require')
    
    print("Fixing companies table...")
    try:
        await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_start TIME")
        print("companies.default_shift_start added successfully.")
    except Exception as e:
        print(f"Error (might exist already): {e}")

    try:
        await conn.execute("ALTER TABLE companies ADD COLUMN default_shift_end TIME")
        print("companies.default_shift_end added successfully.")
    except Exception as e:
        print(f"Error: {e}")

    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
