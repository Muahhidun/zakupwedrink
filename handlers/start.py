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
                    await message.answer("❌ Вы были удалены из этой базы и не можете присоединиться снова.")
                    return

                # Регистрируем пользователя сразу в нужной компании с нужной ролью
                await db.add_or_update_user(
                    user_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    company_id=target_company_id
                )
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
        # Стандартная регистрация (если нет инвайта, компания не меняется)
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

📝 <b>Ввести остатки</b> - внести данные через форму
📦 <b>Мои заявки</b> - просмотр истории

После отправки данные будут проверены администратором.
Вы получите уведомление о результате.
"""
        else:
            welcome_text = """
👋 <b>Привет! Я бот учета WeDrink</b>

Вы авторизованы как <b>Администратор</b>

📝 <b>Ввести остатки</b> - внести данные
📋 <b>Модерация</b> - проверить заявки сотрудников
📦 <b>Текущие остатки</b> - состояние склада
🛒 <b>Список закупа</b> - что заказать
💰 <b>Отчеты</b> - расходы в тенге
📊 <b>Аналитика</b> - топ товаров
👥 <b>Управление</b> - добавить сотрудников
"""
    else:
        welcome_text = """
👋 <b>WeDrink бот запущен в группе!</b>

📝 Доступны команды:
• Текущие остатки
• Отчеты и аналитика
• Список закупа

💡 Ввод остатков доступен только в личных сообщениях.
    """

    await message.answer(welcome_text, reply_markup=get_main_menu(is_private, user_role), parse_mode="HTML")


# Обработчики кнопок главного меню
@router.message(F.text == "🛒 Список закупа")
async def btn_order(message: Message):
    """Кнопка: Список закупа"""
    await message.answer(
        "Выберите на сколько дней формировать заказ:",
        reply_markup=get_order_menu()
    )


@router.message(F.text == "💰 Отчеты")
async def btn_reports(message: Message):
    """Кнопка: Отчеты"""
    await message.answer(
        "Выберите период для отчета:",
        reply_markup=get_reports_menu()
    )


@router.message(F.text == "ℹ️ Помощь")
async def btn_help_menu(message: Message):
    """Кнопка: Помощь"""
    await cmd_help(message)


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


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """Показать Chat ID текущего чата"""
    chat_id = message.chat.id
    chat_type = message.chat.type

    if chat_type == "private":
        response = (
            f"🔑 <b>Chat ID этого чата:</b> <code>{chat_id}</code>\n\n"
            f"⚠️ Это приватный чат. Для напоминаний нужен ID <b>группы</b>.\n"
            f"Используйте команду /chatid в вашей группе 'WeDrink закуп бот'."
        )
    else:
        chat_title = message.chat.title or "Неизвестная группа"
        response = (
            f"🔑 <b>Chat ID этой группы:</b> <code>{chat_id}</code>\n\n"
            f"📱 Название: {chat_title}\n"
            f"👥 Тип: {chat_type}\n\n"
            f"✅ Скопируйте этот ID и добавьте в переменную окружения <code>REMINDER_CHAT_ID</code> на Railway.\n\n"
            f"💡 Чтобы скопировать - нажмите на ID выше."
        )

    await message.answer(response, parse_mode="HTML")
