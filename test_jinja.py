import asyncio
import os
import asyncpg
from dotenv import load_dotenv
import jinja2

load_dotenv()

async def main():
    conn = await asyncpg.connect("postgresql://postgres:IfdxbfvVzYJDioOgXLDyJVUsgyXbDCHf@yamabiko.proxy.rlwy.net:24013/railway")
    
    company_id = 1
    records = await conn.fetch("SELECT * FROM users WHERE company_id = 1 ORDER BY created_at DESC")
    staff = [dict(r) for r in records]
    
    with open('webapp/templates/staff.html', 'r', encoding='utf-8') as f:
        template_str = f.read()

    env = jinja2.Environment()
    # Mock base template to avoid loader error
    template_str = template_str.replace('{% extends "layout.html" %}', '')
    template_str = template_str.replace('{% block content %}', '').replace('{% endblock %}', '')
    template_str = template_str.replace('{% block title %}', '').replace('{% block page_title %}', '').replace('{% block header_actions %}', '').replace('{% block extra_js %}', '')
    try:
        t = env.from_string(template_str)
        user = {'id': 167084307, 'role': 'admin', 'company_id': 1}
        rendered = t.render(staff=staff, user=user)
        print("Render OK. Length:", len(rendered))
    except Exception as e:
        import traceback
        traceback.print_exc()
        
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
