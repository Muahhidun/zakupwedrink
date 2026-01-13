"""
Middleware для проверки ролей и прав доступа
"""
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
import os


# Получаем список админов из .env
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = set()

if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = set(int(x.strip()) for x in ADMIN_IDS_STR.split(',') if x.strip())
    except ValueError:
        print("⚠️ Ошибка парсинга ADMIN_IDS. Проверьте формат в .env")


class RoleMiddleware(BaseMiddleware):
    """Middleware для добавления роли пользователя в data"""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        """Проверяет роль пользователя и добавляет в data"""
        user = event.from_user
        db = data.get('db')

        if not user:
            # Нет пользователя (системное событие?)
            return await handler(event, data)

        # Проверяем роль в ADMIN_IDS или в БД
        if user.id in ADMIN_IDS:
            user_role = 'admin'
        else:
            # Получаем роль из БД
            try:
                user_role = await db.get_user_role(user.id)
            except Exception as e:
                print(f"⚠️ Ошибка получения роли для {user.id}: {e}")
                user_role = 'employee'  # По умолчанию

        data['user_role'] = user_role
        data['is_admin'] = (user_role == 'admin')

        return await handler(event, data)


def admin_only(handler):
    """Декоратор для ограничения доступа только админам"""

    async def wrapper(event, **kwargs):
        is_admin = kwargs.get('is_admin', False)

        if not is_admin:
            # Проверяем тип события для правильного ответа
            if hasattr(event, 'answer'):  # Message
                await event.answer("⛔ Эта команда доступна только администраторам")
            elif hasattr(event, 'message'):  # CallbackQuery
                await event.answer("⛔ Недостаточно прав", show_alert=True)
            return

        return await handler(event, **kwargs)

    return wrapper
