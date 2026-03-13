"""
Обработчик команды /start и кнопок меню
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from keyboards import get_main_menu, get_reports_menu, get_order_menu

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db, user_role: str, is_admin: bool):
    """Приветствие и главное меню"""
    
    # Сначала проверяем, есть ли уже этот пользователь в базе
    user_info = await db.get_user_info(message.from_user.id)
    has_company = user_info and user_info.get('company_id') is not None

    # Обработчик инвайт-ссылок (Onboarding новых франшиз)
    # Формат: /start invite_bXlfc2VjcmV0X3Rva2Vu...
    command_args = message.text.split()
    if len(command_args) > 1 and command_args[1].startswith('invite_'):
        invite_token = command_args[1].replace('invite_', '')
        try:
            import base64
            import json
            # Декодируем инвайт (токен base64 без padding)
            padding_needed = (4 - len(invite_token) % 4) % 4
            padded_token = invite_token + '=' * padding_needed
            decoded_bytes = base64.urlsafe_b64decode(padded_token)
            invite_data = json.loads(decoded_bytes.decode())
            
            target_company_id = invite_data.get('c')
            target_role = invite_data.get('r', 'employee')
            
            if target_company_id:
                # Проверяем не был ли пользователь удален из этой компании
                user_info = await db.get_user_info(message.from_user.id)
                if user_info and user_info.get('company_id') == target_company_id and user_info.get('is_active') == False:
                    # Пользователь был удален, но перешел по новому инвайту. Восстанавливаем.
                    await db.restore_user(message.from_user.id, target_company_id)
                else:
                    # Регистрируем пользователя сразу в нужной компании
                    await db.add_or_update_user(
                        user_id=message.from_user.id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name,
                        last_name=message.from_user.last_name,
                        company_id=target_company_id
                    )
                
                # Обновляем роль согласно инвайту (также обновит роль восстановленному пользователю)
                await db.update_user_role(message.from_user.id, target_role)
                
                # Если это первый админ, копируем ему глобальные товары
                if target_role == 'admin':
                    await db.copy_global_products_to_company(target_company_id)
                
                await message.answer(
                    f"🎉 <b>Добро пожаловать в WeDrink!</b>\n\n"
                    f"Вы успешно присоединены к базе вашей франшизы.\n"
                    f"Ваша роль: <b>{target_role.upper()}</b>\n\n"
                    f"Теперь вы модете войти в Веб-Панель учета!",
                    parse_mode="HTML"
                )
                # Переопределяем user_role для отрисовки правильного меню ниже
                user_role = target_role
                is_admin = (user_role in ['admin', 'superadmin'])
                
        except Exception as e:
            print(f"Ошибка обработки инвайта: {e}")
            await message.answer("❌ Ссылка-приглашение недействительна или устарела.")
            
    else:
        # Стандартная регистрация (без инвайта)
        if not has_company:
            # Если это абсолютно новый пользователь без компании - создаем ему новую пробную компанию!
            company_name = f"Точка {message.from_user.first_name}"
            try:
                # 1. Создаем компанию
                new_company = await db.create_company(name=company_name, trial_days=14)
                new_company_id = new_company['id']
                
                # 2. Регистрируем пользователя как админа в этой компании
                await db.add_or_update_user(
                    user_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    company_id=new_company_id
                )
                await db.update_user_role(message.from_user.id, 'admin')
                
                # 3. Копируем системные товары
                await db.copy_global_products_to_company(new_company_id)
                
                # 4. Обновляем локальные переменные для меню
                user_role = 'admin'
                is_admin = True
                
                await message.answer(
                    f"🎉 <b>Добро пожаловать в WeDrink Закуп!</b>\n\n"
                    f"Мы автоматически создали для вас тестовую компанию: <b>{company_name}</b>\n"
                    f"Вам выдан бесплатный доступ на <b>14 дней</b>.\n\n"
                    f"Вы назначены <b>Администратором</b>. Мы уже загрузили список всех стандартных товаров WeDrink в ваш каталог!",
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Ошибка автосоздания компании: {e}")
                # Fallback, если что-то пошло не так
                await db.add_or_update_user(
                    user_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name
                )
        else:
            # Если у пользователя уже есть компания (повторный /start)
            await db.add_or_update_user(
                user_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )

    is_private = message.chat.type == 'private'

    if is_private:
        if user_role == 'employee':
            welcome_text = """
👋 <b>Привет! Я бот учета WeDrink</b>

Вы авторизованы как <b>Сотрудник</b>

Нажмите кнопку ниже, чтобы открыть карточку ввода остатков.
"""
        else:
            welcome_text = """
👋 <b>Привет! Я бот учета WeDrink</b>

Вы авторизованы как <b>Администратор / Владелец</b>

Нажмите кнопку ниже, чтобы открыть панель управления вашей точкой, где вы сможете видеть дашборд, расходы и одобрять заявки.
"""
    else:
        welcome_text = """
👋 <b>WeDrink бот запущен в группе!</b>

💡 Бот был оптимизирован для работы через Web-App. Пожалуйста, используйте его в личных сообщениях.
    """

    await message.answer(welcome_text, reply_markup=get_main_menu(is_private, user_role), parse_mode="HTML")


# Кнопка "Назад"
@router.message(F.text == "⬅️ Назад")
async def btn_back(message: Message, user_role: str):
    """Вернуться в главное меню"""
    is_private = message.chat.type == 'private'
    await message.answer("Главное меню:", reply_markup=get_main_menu(is_private, user_role))


@router.message(Command("help"))
async def cmd_help(message: Message, user_role: str = 'employee'):
    """Подробная справка"""
    is_private = message.chat.type == 'private'

    help_text = """
📖 <b>ПОДРОБНАЯ СПРАВКА</b>

<b>1. Ежедневный учет остатков</b>
📝 Ввод остатков - через удобную форму (Mini App)
Вводите количество упаковок, бот пересчитает в килограммы
💡 Доступно только в личных сообщениях

<b>2. Формирование заказа</b>
🛒 Список закупа - показывает что нужно заказать
Выберите период: 14, 20 или 30 дней
⚠️ Учитывается время доставки 3-5 дней!

<b>3. Отчеты</b>
💰 Отчеты → Вчера - расход за вчера в ₸
💰 Отчеты → Неделя - общий расход + топ товаров

<b>4. Аналитика</b>
📊 Аналитика - какие товары расходуются быстрее
Рекомендации по оптимальным запасам

<b>5. Текущие остатки</b>
📦 Текущие остатки - что сейчас на складе

💡 <b>Совет:</b> Используйте кнопки меню для быстрого доступа!
    """

    if not is_private:
        help_text += "\n\n⚠️ <b>Работа в группе:</b> Форма ввода остатков (Mini App) доступна только в личных сообщениях с ботом."

    await message.answer(help_text, reply_markup=get_main_menu(is_private, user_role), parse_mode="HTML")



