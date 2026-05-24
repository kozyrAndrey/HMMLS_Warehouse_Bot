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
    "Выгружено в отчет",
    "Дата выгрузки",
    "Кто выгрузил",
]

EXPORT_FLAG_INDEX = 9
EXPORT_DATE_INDEX = 10
EXPORT_USER_INDEX = 11


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
        # Старые строки останутся, новые колонки просто появятся справа.
        worksheet.update("A1:L1", [HEADERS])

    return True


def pad_row(row, length=len(HEADERS)):
    row = list(row)
    if len(row) < length:
        row.extend([""] * (length - len(row)))
    return row


def row_is_exported(row):
    row = pad_row(row)
    value = str(row[EXPORT_FLAG_INDEX]).strip().lower()
    return value in {"да", "yes", "true", "1", "выгружено", "exported"}


def make_record_from_row(row_number, row):
    row = pad_row(row)

    return {
        "row_number": row_number,
        "date": normalize_sheet_date(row[0]),
        "user_id": row[1],
        "username": row[2],
        "category_name": row[3],
        "product_name": row[4],
        "size": row[5],
        "packed": safe_int(row[6]),
        "defective": safe_int(row[7]),
        "rework": safe_int(row[8]),
        "exported": row_is_exported(row),
        "exported_at": row[EXPORT_DATE_INDEX],
        "exported_by": row[EXPORT_USER_INDEX],
    }


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
            "",
            "",
            "",
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
            "",
            "",
            "",
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
        row = pad_row(row)
        created_at = normalize_sheet_date(row[0])
        username = row[2]
        category_name = row[3]
        product_name = row[4]
        size = row[5]
        packed = row[6] or "0"
        defective = row[7] or "0"
        rework = row[8] or "0"
        exported_text = "Да" if row_is_exported(row) else "Нет"

        lines.append(
            f"\n{created_at}\n"
            f"Пользователь: {username}\n"
            f"Группа: {category_name}\n"
            f"Модель: {product_name}\n"
            f"Размер: {size}\n"
            f"Упаковано: {packed}\n"
            f"Брак: {defective}\n"
            f"Доработка: {rework}\n"
            f"Выгружено в отчет: {exported_text}"
        )

    return "\n".join(lines)


def get_unexported_receiving_records(limit=15):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return []

    records = []

    for row_number, row in enumerate(values[1:], start=2):
        if len(row) < 9:
            continue

        row = pad_row(row)

        category_name = row[3].strip()
        product_name = row[4].strip()
        size = row[5].strip()

        if not category_name or not product_name or not size:
            continue

        if row_is_exported(row):
            continue

        records.append(make_record_from_row(row_number, row))

    records.reverse()
    return records[:limit]


def get_receiving_record_by_row(row_number):
    worksheet = get_google_worksheet()
    row = worksheet.row_values(row_number)

    if not row:
        return None

    if len(row) < 9:
        return None

    return make_record_from_row(row_number, row)


def delete_unexported_receiving_record(row_number):
    worksheet = get_google_worksheet()
    record = get_receiving_record_by_row(row_number)

    if not record:
        raise RuntimeError("Запись не найдена.")

    if record["exported"]:
        raise RuntimeError("Эта запись уже выгружена в отчет, ее нельзя удалить.")

    worksheet.delete_rows(row_number)
    return record


def has_unexported_receiving_records_for_date(report_date):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return False

    for row in values[1:]:
        if len(row) < 9:
            continue

        row = pad_row(row)

        if normalize_sheet_date(row[0]) != report_date:
            continue

        if not row[4].strip() or not row[5].strip():
            continue

        if not row_is_exported(row):
            return True

    return False


def mark_receiving_rows_exported(report_date, exported_by):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    if len(values) <= 1:
        return 0

    now_text = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    updates = []
    marked_count = 0

    for row_number, row in enumerate(values[1:], start=2):
        if len(row) < 9:
            continue

        row = pad_row(row)

        if normalize_sheet_date(row[0]) != report_date:
            continue

        if not row[4].strip() or not row[5].strip():
            continue

        if row_is_exported(row):
            continue

        updates.append(
            {
                "range": f"J{row_number}:L{row_number}",
                "values": [["Да", now_text, exported_by]],
            }
        )
        marked_count += 1

    if updates:
        worksheet.batch_update(updates)

    return marked_count


def build_receiving_report_text(report_date, exported_by=None, only_unexported=True):
    worksheet = get_google_worksheet()
    values = worksheet.get_all_values()

    header_lines = [f"Дата: {report_date}"]

    if exported_by:
        header_lines.append(f"Выгрузил: {exported_by}")

    if len(values) <= 1:
        return "\n".join(header_lines) + "\n\nНет записей за эту дату."

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

        row = pad_row(row)
        row_date = normalize_sheet_date(row[0])

        if row_date != report_date:
            continue

        if only_unexported and row_is_exported(row):
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
        if only_unexported:
            return "\n".join(header_lines) + "\n\nНет невыгруженных записей за эту дату."

        return "\n".join(header_lines) + "\n\nНет записей за эту дату."

    lines = header_lines + [""]

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
