import asyncio
import asyncpg
import os

DB_URL = "postgresql://postgres:pnqmXzGSWnQVgSsdMUxQKmEcffPBmyLB@tramway.proxy.rlwy.net:34608/railway"

async def run():
    conn = await asyncpg.connect(DB_URL)
    rows = await conn.fetch("""
        SELECT conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'users' AND c.contype = 'c';
    """)
    print("Check constraints on 'users':")
    for r in rows:
        print(f" - {r[0]}: {r[1]}")
    await conn.close()

asyncio.run(run())
