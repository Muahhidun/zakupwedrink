import asyncio, json
from database_pg import DatabasePG
import logging

async def main():
    db = DatabasePG('postgres://postgres:1234@postgres.railway.internal:5432/railway')
    await db.connect()
    
    shifts = await db.get_shifts(1, '2026-03-01', '2026-03-31')
    
    def json_serializer(obj):
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return str(obj)
        
    try:
        j = json.dumps(shifts, default=json_serializer)
        print("SUCCESS")
    except Exception as e:
        print(f"FAILED TO SERIALIZE: {e}")
        for s in shifts:
            print(s)
            
    await db.close()

if __name__ == '__main__':
    asyncio.run(main())
