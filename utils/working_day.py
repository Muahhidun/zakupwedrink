"""
Утилиты для работы с "рабочим днём"
Рабочий день длится до 03:00 следующих суток
"""
from datetime import datetime, timedelta
import pytz


def get_working_date(dt: datetime = None) -> str:
    """
    Получить дату рабочего дня в формате YYYY-MM-DD

    Рабочий день длится с 03:00 текущего дня до 02:59 следующего дня.
    Например:
    - 01.12.2024 23:00 → рабочий день 01.12.2024
    - 02.12.2024 02:30 → рабочий день 01.12.2024 (ещё не закончился)
    - 02.12.2024 03:00 → рабочий день 02.12.2024 (новый день)
    """
    if dt is None:
        # Текущее время в Астане
        astana_tz = pytz.timezone('Asia/Almaty')
        dt = datetime.now(astana_tz)

    # Если время до 03:00 - это предыдущий рабочий день
    if dt.hour < 3:
        dt = dt - timedelta(days=1)

    return dt.strftime('%Y-%m-%d')


def get_working_datetime(date_str: str) -> datetime:
    """
    Получить datetime начала рабочего дня (03:00 по Астане)
    """
    astana_tz = pytz.timezone('Asia/Almaty')
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')

    # Устанавливаем время 03:00 по Астане
    working_dt = astana_tz.localize(datetime(date_obj.year, date_obj.month, date_obj.day, 3, 0, 0))

    return working_dt
