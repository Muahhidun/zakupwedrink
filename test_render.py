import asyncio
import os
import asyncpg
from dotenv import load_dotenv
import jinja2

load_dotenv()

async def main():
    conn = await asyncpg.connect("postgresql://postgres:IfdxbfvVzYJDioOgXLDyJVUsgyXbDCHf@yamabiko.proxy.rlwy.net:24013/railway")
    
    company_id = 1
    records = await conn.fetch("""
        SELECT id, username, first_name, last_name, real_name, role, is_active, created_at, last_seen
        FROM users 
        WHERE company_id = $1
        ORDER BY created_at DESC
    """, company_id)
    staff = [dict(r) for r in records]
    
    with open('webapp/templates/staff.html', 'r', encoding='utf-8') as f:
        template_str = f.read()

    env = jinja2.Environment()
    try:
        t = env.from_string(template_str)
        user = {'id': 167084307, 'role': 'admin', 'company_id': 1}
        rendered = t.render(staff=staff, user=user)
        print("Render OK. Length:", len(rendered))
    except Exception as e:
        print("Template Render Error:", e)
        
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
