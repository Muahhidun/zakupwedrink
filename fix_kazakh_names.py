import asyncio
import os
import sqlite3
import asyncpg
from dotenv import load_dotenv

async def fix_names():
    load_dotenv()
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("No DATABASE_URL found.")
        return

    # 1. Get correct names from SQLite
    conn_sqlite = sqlite3.connect('wedrink.db')
    c = conn_sqlite.cursor()
    c.execute('SELECT name_internal, name_russian FROM products')
    correct_names = {row[0]: row[1] for row in c.fetchall()}
    conn_sqlite.close()

    print(f"Loaded {len(correct_names)} correct names from SQLite.")

    # 2. Update PostgreSQL
    print("Connecting to Postgres...")
    conn_pg = await asyncpg.connect(database_url)
    
    updated = 0
    for name_internal, correct_russian in correct_names.items():
        if correct_russian:
            res = await conn_pg.execute(
                "UPDATE products SET name_russian = $1 WHERE name_internal = $2 AND name_russian != $1",
                correct_russian, name_internal
            )
            # count updates
            if res != "UPDATE 0":
                print(f"Updated '{name_internal}' -> '{correct_russian}'")
                updated += 1

    print(f"Finished. Updated {updated} products.")
    await conn_pg.close()

if __name__ == '__main__':
    asyncio.run(fix_names())
