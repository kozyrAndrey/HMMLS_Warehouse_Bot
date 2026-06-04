import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()



BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DB_PATH = os.getenv(
    "DB_PATH",
    str(BASE_DIR / "warehouse.db"),
)

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
# ============================================================
# НАСТРОЙКИ МОДУЛЯ ЗП
# ============================================================

PAYROLL_GOOGLE_SHEET_ID = os.getenv("PAYROLL_GOOGLE_SHEET_ID", "")
PAYROLL_REPORT_TOPIC_ID = os.getenv("PAYROLL_REPORT_TOPIC_ID", "")


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


# ============================================================
# НАСТРОЙКИ МОДУЛЯ ЧЕКОВ
# ============================================================

MOYSKLAD_API_TOKEN = os.getenv("MOYSKLAD_API_TOKEN", "")
MOYSKLAD_CA_BUNDLE = os.getenv("MOYSKLAD_CA_BUNDLE", "")
MOYSKLAD_RECEIPT_LINK_ATTR_NAME = os.getenv(
    "MOYSKLAD_RECEIPT_LINK_ATTR_NAME",
    "Ссылка на чек HOMME+LESS",
)
RECEIPTS_ERROR_CHAT_ID = os.getenv("RECEIPTS_ERROR_CHAT_ID", GROUP_CHAT_ID)
RECEIPTS_ERROR_TOPIC_ID = os.getenv("RECEIPTS_ERROR_TOPIC_ID", "")

NIRGUNA_ATOL_BASE_URL = os.getenv(
    "NIRGUNA_ATOL_BASE_URL",
    "https://atolonline1.nirguna-app3.ru",
)
NIRGUNA_ATOL_ACCOUNT_ID = os.getenv("NIRGUNA_ATOL_ACCOUNT_ID", "")
NIRGUNA_ATOL_UID = os.getenv("NIRGUNA_ATOL_UID", "")
NIRGUNA_ATOL_TOKEN = os.getenv("NIRGUNA_ATOL_TOKEN", "")
NIRGUNA_ATOL_COOKIE = os.getenv("NIRGUNA_ATOL_COOKIE", "")
NIRGUNA_MARKING_BUTTON_ID = os.getenv("NIRGUNA_MARKING_BUTTON_ID", "211")
