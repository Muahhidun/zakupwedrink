import asyncio
import os
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()

async def main():
    db = DatabasePG(os.getenv("DATABASE_URL"))
    await db.init_db()
    
    user_id = 999999999  # Dummy user
    
    print("Trying to create company...")
    try:
        new_company = await db.create_company(name="Test Point", trial_days=14)
        new_company_id = new_company['id']
        print(f"Created company {new_company_id}")
        
        print("Registering user as admin...")
        await db.add_or_update_user(
            user_id=user_id,
            username="test_user",
            first_name="Test",
            last_name="User",
            company_id=new_company_id
        )
        print("Adding role...")
        await db.update_user_role(user_id, 'admin')
        
        print("Copying global products...")
        await db.copy_global_products_to_company(new_company_id)
        print("Success!")
    except Exception as e:
        print(f"Exception caught in full flow: {repr(e)}")
    finally:
        await db.close()

asyncio.run(main())
