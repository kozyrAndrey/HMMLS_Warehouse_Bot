import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()



BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DATABASE_URL = os.getenv("DATABASE_URL", "")

GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    str(BASE_DIR / "google_credentials.json"),
)

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

GOOGLE_WORKSHEET_NAME = os.getenv(
    "GOOGLE_WORKSHEET_NAME",
    "Оприходование",
)

GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "")

RETURNS_TOPIC_ID = os.getenv("RETURNS_TOPIC_ID", "")

RECEIVING_REPORT_TOPIC_ID = os.getenv("RECEIVING_REPORT_TOPIC_ID", "")
SPECIAL_RECEIVING_REPORT_TOPIC_ID = os.getenv("SPECIAL_RECEIVING_REPORT_TOPIC_ID", "")
# ============================================================
# НАСТРОЙКИ МОДУЛЯ ЗП
# ============================================================

PAYROLL_GOOGLE_SHEET_ID = os.getenv("PAYROLL_GOOGLE_SHEET_ID", "")
PAYROLL_REPORT_TOPIC_ID = os.getenv("PAYROLL_REPORT_TOPIC_ID", "")


# ============================================================
# НАСТРОЙКИ МОДУЛЯ РАСХОДНИКОВ
# ============================================================

CONSUMABLES_TOPIC_ID = os.getenv("CONSUMABLES_TOPIC_ID", "103")


# ============================================================
# НАСТРОЙКИ МОДУЛЯ РЕЗЮМЕ
# ============================================================

RECRUITMENT_TOPIC_ID = os.getenv("RECRUITMENT_TOPIC_ID", "")


# ============================================================
# НАСТРОЙКИ ОПЕРАЦИОННОЙ ТАБЛИЦЫ
# ============================================================
# Здесь хранятся расписание, дежурства и будущий модуль задач.

OPERATIONS_GOOGLE_SHEET_ID = os.getenv("OPERATIONS_GOOGLE_SHEET_ID", "")


# ============================================================
# НАСТРОЙКИ МОДУЛЯ РАСПИСАНИЯ
# ============================================================
# SCHEDULE_EXPORT_TOPIC_ID — тема, куда бот выгружает Excel-файл расписания.
# SCHEDULE_REMINDER_TOPIC_ID — тема, куда бот отправляет пятничное напоминание.
#
# Для обратной совместимости можно оставить старый SCHEDULE_TOPIC_ID:
# если новые переменные не заданы, бот возьмет его как fallback.

SCHEDULE_TOPIC_ID = os.getenv("SCHEDULE_TOPIC_ID", "")
SCHEDULE_EXPORT_TOPIC_ID = os.getenv("SCHEDULE_EXPORT_TOPIC_ID", SCHEDULE_TOPIC_ID)
SCHEDULE_REMINDER_TOPIC_ID = os.getenv("SCHEDULE_REMINDER_TOPIC_ID", SCHEDULE_TOPIC_ID)


# ============================================================
# НАСТРОЙКИ ОТПРАВКИ ФОТО ЧЕСТНОГО ЗНАКА ПО ВОЗВРАТАМ
# ============================================================

RETURN_CHZ_CHAT_ID = os.getenv("RETURN_CHZ_CHAT_ID", "-1002637764298")
RETURN_CHZ_TOPIC_ID = os.getenv("RETURN_CHZ_TOPIC_ID", "740")
