"""
Миграция: добавление ролей и системы модерации остатков
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from database_pg import DatabasePG

load_dotenv()


async def migrate():
    """Выполнить миграцию БД"""
    DATABASE_URL = os.getenv('DATABASE_URL')

    if not DATABASE_URL:
        print("❌ DATABASE_URL не найден в .env")
        sys.exit(1)

    db = DatabasePG(DATABASE_URL)
    await db.init_db()

    print("🔄 Начало миграции...")

    async with db.pool.acquire() as conn:
        # ==== Проверяем и добавляем колонку role ====
        role_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name='users' AND column_name='role'
            )
        """)

        if not role_exists:
            print("📝 Добавляем колонку role в таблицу users...")
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN role TEXT DEFAULT 'employee'
                CHECK (role IN ('employee', 'admin'))
            """)
            print("   ✅ Колонка role добавлена")
        else:
            print("   ⏭️  Колонка role уже существует")

        # ==== Проверяем и добавляем колонку added_by ====
        added_by_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name='users' AND column_name='added_by'
            )
        """)

        if not added_by_exists:
            print("📝 Добавляем колонку added_by в таблицу users...")
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN added_by BIGINT REFERENCES users(id)
            """)
            print("   ✅ Колонка added_by добавлена")
        else:
            print("   ⏭️  Колонка added_by уже существует")

        # ==== Проверяем и добавляем колонку added_at ====
        added_at_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_name='users' AND column_name='added_at'
            )
        """)

        if not added_at_exists:
            print("📝 Добавляем колонку added_at в таблицу users...")
            await conn.execute("""
                ALTER TABLE users
                ADD COLUMN added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)
            print("   ✅ Колонка added_at добавлена")
        else:
            print("   ⏭️  Колонка added_at уже существует")

        # ==== Создаем таблицу pending_stock_submissions ====
        print("\n📝 Создаем таблицу pending_stock_submissions...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_stock_submissions (
                id SERIAL PRIMARY KEY,
                submitted_by BIGINT NOT NULL REFERENCES users(id),
                submission_date DATE NOT NULL,
                status TEXT DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by BIGINT REFERENCES users(id),
                reviewed_at TIMESTAMP,
                rejection_reason TEXT
            )
        """)
        print("   ✅ Таблица pending_stock_submissions создана")

        # ==== Создаем уникальный индекс для pending заявок ====
        print("📝 Создаем уникальный индекс для pending заявок...")
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique
                ON pending_stock_submissions(submitted_by, submission_date)
                WHERE status = 'pending'
            """)
            print("   ✅ Индекс idx_pending_unique создан")
        except Exception as e:
            print(f"   ⚠️  Индекс уже существует или ошибка: {e}")

        # ==== Создаем индекс для status и даты ====
        print("📝 Создаем индекс для status...")
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pending_status
                ON pending_stock_submissions(status, created_at)
            """)
            print("   ✅ Индекс idx_pending_status создан")
        except Exception as e:
            print(f"   ⚠️  Индекс уже существует или ошибка: {e}")

        # ==== Создаем таблицу pending_stock_items ====
        print("\n📝 Создаем таблицу pending_stock_items...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_stock_items (
                id SERIAL PRIMARY KEY,
                submission_id INTEGER NOT NULL
                    REFERENCES pending_stock_submissions(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity REAL NOT NULL,
                weight REAL NOT NULL,
                edited_quantity REAL,
                edited_weight REAL,
                UNIQUE(submission_id, product_id)
            )
        """)
        print("   ✅ Таблица pending_stock_items создана")

        # ==== Создаем индекс для submission_id ====
        print("📝 Создаем индекс для submission_id...")
        try:
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_submission_items
                ON pending_stock_items(submission_id)
            """)
            print("   ✅ Индекс idx_submission_items создан")
        except Exception as e:
            print(f"   ⚠️  Индекс уже существует или ошибка: {e}")

        # ==== Назначаем админов из .env ====
        print("\n📝 Назначаем администраторов из ADMIN_IDS...")
        admin_ids_str = os.getenv('ADMIN_IDS', '')

        if admin_ids_str:
            admin_ids = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]

            for admin_id in admin_ids:
                await conn.execute("""
                    INSERT INTO users (id, role, added_at)
                    VALUES ($1, 'admin', CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET role = 'admin'
                """, admin_id)
                print(f"   ✅ Назначен админ: {admin_id}")
        else:
            print("   ⚠️  ADMIN_IDS не указан в .env")

        print("\n✅ Миграция завершена успешно!")
        print("\n📋 Создано:")
        print("   • Колонка users.role")
        print("   • Колонка users.added_by")
        print("   • Колонка users.added_at")
        print("   • Таблица pending_stock_submissions")
        print("   • Таблица pending_stock_items")
        print("   • Индексы для оптимизации")

        if admin_ids_str:
            print(f"   • Админы: {admin_ids_str}")

    await db.close()


if __name__ == '__main__':
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        print("\n❌ Миграция прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка миграции: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
