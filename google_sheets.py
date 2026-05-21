from collections import defaultdict
from datetime import datetime
from pathlib import Path

import gspread

from config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_SHEET_ID,
    GOOGLE_WORKSHEET_NAME,
)
from products import CATEGORIES


HEADERS = [
    "Дата",
    "User ID",
    "Пользователь",
    "Группа",
    "Модель",
    "Размер",
    "Упаковано",
    "Брак",
    "Доработка",
]


def google_sheets_is_configured():
    if not GOOGLE_SHEET_ID:
        return False

    if GOOGLE_SHEET_ID == "ВСТАВЬ_ID_GOOGLE_ТАБЛИЦЫ":
        return False

    if not Path(GOOGLE_CREDENTIALS_PATH).exists():
        return False

    return True


def get_google_worksheet():
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(GOOGLE_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=GOOGLE_WORKSHEET_NAME,
            rows=1000,
            cols=12,
        )

    return worksheet


def init_google_sheet():
    if not google_sheets_is_configured():
        return False

    worksheet = get_google_worksheet()
    first_row = worksheet.row_values(1)

    if first_row != HEADERS:
        # Не очищаем таблицу, только обновляем заголовки.
        worksheet.update("A1:I1", [HEADERS])

    return True


def save_to_google_sheet(
    user_id,
    username,
    category_id,
    product_id,
    size,
    packed,
    defective,
    rework,
    record_date=None,
):
    if GOOGLE_SHEET_ID == "ВСТАВЬ_ID_GOOGLE_ТАБЛИЦЫ" or not GOOGLE_SHEET_ID.strip():
        raise RuntimeError("GOOGLE_SHEET_ID не указан.")

    if not Path(GOOGLE_CREDENTIALS_PATH).exists():
        raise FileNotFoundError(
            f"Файл {GOOGLE_CREDENTIALS_PATH} не найден. "
            "Положи google_credentials.json рядом с bot.py."
        )

    worksheet = get_google_worksheet()

    category_name = CATEGORIES[category_id]["name"]
    product_name = CATEGORIES[category_id]["products"][product_id]

    worksheet.append_row(
        [
            record_date or datetime.now().strftime("%d.%m.%Y"),
            user_id,
            username,
            category_name,
            product_name,
            size,
            packed,
            defective,
            rework,
        ]
    )

def append_google_status_test_row():
    worksheet = get_google_worksheet()

    worksheet.append_row(
        [
            datetime.now().strftime("%d.%m.%Y"),
            "TEST",
            "Проверка из команды /google_status",
            "",
            "",
            "",
            0,
            0,
            0,
        ]
    )


def normalize_sheet_date(value):
    value = str(value).strip()

    if not value:
        return ""

    # Новый формат: 19.05.2026
    try:
        return datetime.strptime(value, "%d.%m.%Y").strftime("%d.%m.%Y")
    except ValueError:
        pass

    # Старый формат: 2026-05-19 16:12:12
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")
    except ValueError:
        pass

    # Старый формат без времени: 2026-05-19
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        pass

    return value


def safe_int(value):
    try:
        if value is None or value == "":
            return 0

        return int(float(str(value).replace(",", ".").strip()))
    except Exception:
        return 0


def get_last_records_text_from_google(limit=10):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return "Пока нет записей в Google Таблице."

    rows = values[1:]
    product_rows = []

    for row in rows:
        if len(row) < 9:
            continue

        category_name = row[3].strip()
        product_name = row[4].strip()
        size = row[5].strip()

        if category_name and product_name and size:
            product_rows.append(row)

    if not product_rows:
        return "Пока нет товарных записей в Google Таблице."

    last_rows = product_rows[-limit:]
    last_rows.reverse()

    lines = [f"📋 Последние {min(limit, len(last_rows))} записей из Google Таблицы:"]

    for row in last_rows:
        created_at = normalize_sheet_date(row[0]) if len(row) > 0 else ""
        username = row[2] if len(row) > 2 else ""
        category_name = row[3] if len(row) > 3 else ""
        product_name = row[4] if len(row) > 4 else ""
        size = row[5] if len(row) > 5 else ""
        packed = row[6] if len(row) > 6 else "0"
        defective = row[7] if len(row) > 7 else "0"
        rework = row[8] if len(row) > 8 else "0"

        lines.append(
            f"\n{created_at}\n"
            f"Пользователь: {username}\n"
            f"Группа: {category_name}\n"
            f"Модель: {product_name}\n"
            f"Размер: {size}\n"
            f"Упаковано: {packed}\n"
            f"Брак: {defective}\n"
            f"Доработка: {rework}"
        )

    return "\n".join(lines)


def build_receiving_report_text(report_date):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return f"Дата: {report_date}\n\nНет записей за эту дату."

    rows = values[1:]

    # product_name -> size -> totals
    grouped = defaultdict(lambda: defaultdict(lambda: {
        "packed": 0,
        "defective": 0,
        "rework": 0,
    }))

    total_packed = 0
    total_defective = 0
    total_rework = 0

    for row in rows:
        if len(row) < 9:
            continue

        row_date = normalize_sheet_date(row[0])

        if row_date != report_date:
            continue

        product_name = row[4].strip()
        size = row[5].strip()

        if not product_name or not size:
            continue

        packed = safe_int(row[6])
        defective = safe_int(row[7])
        rework = safe_int(row[8])

        grouped[product_name][size]["packed"] += packed
        grouped[product_name][size]["defective"] += defective
        grouped[product_name][size]["rework"] += rework

        total_packed += packed
        total_defective += defective
        total_rework += rework

    if not grouped:
        return f"Дата: {report_date}\n\nНет записей за эту дату."

    lines = [
        f"Дата: {report_date}",
        "",
    ]

    for product_name in sorted(grouped.keys()):
        lines.append(product_name)

        for size in sorted(grouped[product_name].keys()):
            packed = grouped[product_name][size]["packed"]
            defective = grouped[product_name][size]["defective"]
            rework = grouped[product_name][size]["rework"]
            total = packed + defective + rework

            lines.append(
                f"{size}: упаковано - {packed}, "
                f"брак - {defective}, "
                f"доработка - {rework}, "
                f"общее - {total}"
            )

        lines.append("")

    grand_total = total_packed + total_defective + total_rework

    lines.extend(
        [
            f"Общее упаковано: {total_packed}",
            f"Общее брак: {total_defective}",
            f"Общее доработка: {total_rework}",
            f"Общее: {grand_total}",
        ]
    )

    return "\n".join(lines)
