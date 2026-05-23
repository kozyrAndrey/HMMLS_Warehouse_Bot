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
