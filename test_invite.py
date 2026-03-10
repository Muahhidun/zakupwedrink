import asyncio
from database_pg import DatabasePG
import base64
import json
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    invite_token = 'eyJjIjogNCwgInIiOiAiYWRtaW4iLCAidCI6IDE3NzIxMzc5Mzh9'
    db_url = os.getenv("DATABASE_URL")
    db = DatabasePG(db_url)
    await db.init_db()
    
    try:
        padding_needed = (4 - len(invite_token) % 4) % 4
        padded_token = invite_token + '=' * padding_needed
        print(f"Padded token: {padded_token}")
        decoded_bytes = base64.urlsafe_b64decode(padded_token)
        invite_data = json.loads(decoded_bytes.decode())
        print(f"Invite data: {invite_data}")
        
        target_company_id = invite_data.get('c')
        target_role = invite_data.get('r', 'employee')
        
        print("Adding user...")
        await db.add_or_update_user(
            user_id=999999, # Dummy ID
            username="test_user",
            first_name="Test",
            last_name="User",
            company_id=target_company_id
        )
        print("Updating role...")
        await db.update_user_role(999999, target_role)
        
        if target_role == 'admin':
            print("Copying global products...")
            await db.copy_global_products_to_company(target_company_id)
            
        print("Success!")
        
    except Exception as e:
        print(f"Exception during processing: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        await db.close()

if __name__ == '__main__':
    asyncio.run(main())
