import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

TARGET_DB_URL = os.getenv('TARGET_DB_URL')

async def add_real_name_column():
    if not TARGET_DB_URL:
        print("❌ Ошибка: В .env не задана TARGET_DB_URL")
        return

    print("🔌 Подключение к базе данных...")
    pool = await asyncpg.create_pool(dsn=TARGET_DB_URL)
    
    async with pool.acquire() as conn:
        print("⚙️ Добавляем колонку real_name в таблицу users...")
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN real_name TEXT;")
            print("✅ Колонка real_name успешно добавлена!")
        except asyncpg.exceptions.DuplicateColumnError:
            print("⚠️ Колонка real_name уже существует, пропускаем.")
        except Exception as e:
            print(f"❌ Ошибка при добавлении колонки: {e}")

    await pool.close()

if __name__ == "__main__":
    asyncio.run(add_real_name_column())
