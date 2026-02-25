import asyncio
import os
from dotenv import load_dotenv
import asyncpg

async def diagnose_db():
    load_dotenv()
    url = os.getenv('DATABASE_URL')
    print(f"Connecting to: {url}")
    conn = await asyncpg.connect(url, ssl='require')
    
    try:
        # Список всех таблиц
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        print("\n--- Таблицы в базе ---")
        for t in tables:
            print(f"- {t['table_name']}")
            
        # Количество записей в основных таблицах
        for table in ['products', 'stock', 'supplies', 'users']:
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                print(f"Table {table}: {count} records")
                
                if table == 'stock' and count > 0:
                    dates = await conn.fetch("SELECT DISTINCT date FROM stock ORDER BY date DESC LIMIT 5")
                    print(f"  Recent dates in stock: {[d['date'] for d in dates]}")
            except Exception as e:
                print(f"Table {table}: Error {e}")

        # Проверка на наличие других таблиц, которые могли использоваться ботом
        # (например, с другими именами)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(diagnose_db())
