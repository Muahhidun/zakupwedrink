import asyncio
import os
import asyncpg
import re
from dotenv import load_dotenv

async def fix_names_regex():
    load_dotenv()
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("No DATABASE_URL found.")
        return

    print("Connecting to Postgres...")
    conn = await asyncpg.connect(database_url)
    
    rows = await conn.fetch("SELECT id, name_internal FROM products")
    updated = 0
    for r in rows:
        name_internal = r['name_internal']
        # Extract clean name
        clean_name = re.sub(r'\s*([\d\.,]+[кгшлт]+\*\d+[шт]+|\(\d+[шт]+/[кор]+\))$', '', name_internal)
        
        # Override special cases
        if name_internal == 'Мороженое (сливочное) 3кг*8шт':
            clean_name = 'Мороженое (сливочное)'
        elif name_internal == 'Мороженое (шоколадное) 3кг*8шт':
            clean_name = 'Мороженое (шоколадное)'
        elif name_internal == 'Толстые трубочки (4000шт/кор)':
            clean_name = 'Толстые трубочки'
        elif name_internal == 'Стакан большой 900мл (200шт/кор)':
            clean_name = 'Стакан большой 900мл'
        elif name_internal == 'Плёнка для запайки (12рул/кор)':
            clean_name = 'Плёнка для запайки'
        elif name_internal.startswith('Ложка'):
            clean_name = re.sub(r'\s*\(\d+[шт]+/[кор]+\)$', '', name_internal)

        print(f"Updating '{name_internal}' -> '{clean_name}'")
        res = await conn.execute("UPDATE products SET name_russian = $1 WHERE id = $2", clean_name, r['id'])
        if res != "UPDATE 0":
            updated += 1

    print(f"Finished. Updated {updated} products.")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(fix_names_regex())
