import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import gspread

from config import GOOGLE_CREDENTIALS_PATH, PAYROLL_GOOGLE_SHEET_ID
from payroll_config import PAYROLL_EMPLOYEES, PAYROLL_KPI, normalize_username


EMPLOYEES_SHEET = "Сотрудники"
REPORTS_SHEET = "Ежедневные отчеты"
EXPENSES_SHEET = "Расходы"
PENALTIES_SHEET = "Штрафы"
KPI_SHEET = "KPI"
PERIODS_SHEET = "Расчетные периоды"

EMPLOYEE_HEADERS = [
    "employee_id",
    "ФИО",
    "telegram_user_id",
    "telegram_username",
    "role",
    "hourly_rate",
    "fixed_salary",
    "include_in_common_fund",
    "is_active",
]

REPORT_HEADERS = [
    "report_id",
    "Дата",
    "employee_id",
    "ФИО",
    "telegram_user_id",
    "Рабочий промежуток",
    "Отработано часов",
    "Задачи",
    "KPI данные",
    "KPI сумма",
    "telegram_chat_id",
    "telegram_thread_id",
    "telegram_message_id",
    "Создано",
    "Обновлено",
]

EXPENSE_HEADERS = [
    "expense_id",
    "Дата",
    "employee_id",
    "ФИО",
    "Комментарий",
    "Сумма",
    "Создал",
    "Создано",
]

PENALTY_HEADERS = [
    "penalty_id",
    "Дата",
    "employee_id",
    "ФИО",
    "Комментарий",
    "Сумма",
    "Назначил",
    "Создано",
]

KPI_HEADERS = [
    "kpi_id",
    "Название",
    "Ставка",
    "Активно",
]

PERIOD_HEADERS = [
    "period_id",
    "Название",
    "Дата начала",
    "Дата конца",
    "Статус",
    "Создал",
    "Создано",
    "Обновлено",
]


def now_str():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def date_today_str():
    return datetime.now().strftime("%d.%m.%Y")


def parse_date(value):
    value = str(value).strip()
    return datetime.strptime(value, "%d.%m.%Y")


def validate_date(value):
    try:
        parse_date(value)
        return True
    except ValueError:
        return False


def date_in_range(value, start_date, end_date):
    try:
        current = parse_date(value)
        start = parse_date(start_date)
        end = parse_date(end_date)
        return start <= current <= end
    except ValueError:
        return False


def safe_float(value):
    try:
        if value is None or value == "":
            return 0.0
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return 0.0


def safe_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "да", "истина"}


def money(value):
    value = float(value or 0)
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def generate_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def payroll_is_configured():
    return bool(PAYROLL_GOOGLE_SHEET_ID and Path(GOOGLE_CREDENTIALS_PATH).exists())


def get_payroll_spreadsheet():
    if not PAYROLL_GOOGLE_SHEET_ID:
        raise RuntimeError("PAYROLL_GOOGLE_SHEET_ID не указан в .env")
    if not Path(GOOGLE_CREDENTIALS_PATH).exists():
        raise FileNotFoundError(f"Файл {GOOGLE_CREDENTIALS_PATH} не найден")

    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS_PATH)
    return gc.open_by_key(PAYROLL_GOOGLE_SHEET_ID)


def get_worksheet(title, rows=1000, cols=30):
    spreadsheet = get_payroll_spreadsheet()
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def ensure_headers(worksheet, headers):
    first_row = worksheet.row_values(1)
    if first_row != headers:
        end_col = chr(ord("A") + len(headers) - 1)
        worksheet.update(f"A1:{end_col}1", [headers])


def records_from_worksheet(worksheet):
    return worksheet.get_all_records()


def init_payroll_sheet():
    if not payroll_is_configured():
        logging.warning("Payroll Google Sheet не настроен")
        return False

    employees_ws = get_worksheet(EMPLOYEES_SHEET, rows=200, cols=12)
    reports_ws = get_worksheet(REPORTS_SHEET, rows=3000, cols=20)
    expenses_ws = get_worksheet(EXPENSES_SHEET, rows=1000, cols=12)
    penalties_ws = get_worksheet(PENALTIES_SHEET, rows=1000, cols=12)
    kpi_ws = get_worksheet(KPI_SHEET, rows=100, cols=6)
    periods_ws = get_worksheet(PERIODS_SHEET, rows=200, cols=10)

    ensure_headers(employees_ws, EMPLOYEE_HEADERS)
    ensure_headers(reports_ws, REPORT_HEADERS)
    ensure_headers(expenses_ws, EXPENSE_HEADERS)
    ensure_headers(penalties_ws, PENALTY_HEADERS)
    ensure_headers(kpi_ws, KPI_HEADERS)
    ensure_headers(periods_ws, PERIOD_HEADERS)

    if len(employees_ws.get_all_values()) <= 1:
        rows = []
        for employee in PAYROLL_EMPLOYEES:
            rows.append([
                employee["employee_id"],
                employee["full_name"],
                employee.get("telegram_user_id", ""),
                employee.get("telegram_username", ""),
                employee["role"],
                employee["hourly_rate"],
                employee["fixed_salary"],
                str(employee["include_in_common_fund"]).upper(),
                str(employee["is_active"]).upper(),
            ])
        employees_ws.append_rows(rows)

    if len(kpi_ws.get_all_values()) <= 1:
        rows = []
        for item in PAYROLL_KPI:
            rows.append([
                item["kpi_id"],
                item["name"],
                item["rate"],
                str(item["is_active"]).upper(),
            ])
        kpi_ws.append_rows(rows)

    return True


def get_employees(include_inactive=False):
    ws = get_worksheet(EMPLOYEES_SHEET)
    records = records_from_worksheet(ws)
    employees = []
    for record in records:
        if not record.get("employee_id"):
            continue
        employee = {
            "employee_id": str(record.get("employee_id", "")).strip(),
            "full_name": str(record.get("ФИО", "")).strip(),
            "telegram_user_id": str(record.get("telegram_user_id", "")).strip(),
            "telegram_username": normalize_username(record.get("telegram_username", "")),
            "role": str(record.get("role", "warehouse_employee")).strip(),
            "hourly_rate": safe_float(record.get("hourly_rate")),
            "fixed_salary": safe_float(record.get("fixed_salary")),
            "include_in_common_fund": safe_bool(record.get("include_in_common_fund")),
            "is_active": safe_bool(record.get("is_active")),
        }
        if include_inactive or employee["is_active"]:
            employees.append(employee)
    return employees


def get_employee_by_id(employee_id):
    for employee in get_employees(include_inactive=True):
        if employee["employee_id"] == str(employee_id):
            return employee
    return None


def find_employee_for_telegram_user(user):
    telegram_user_id = str(user.id)
    username = normalize_username(user.username)

    for employee in get_employees(include_inactive=True):
        if employee["telegram_user_id"] and employee["telegram_user_id"] == telegram_user_id:
            return employee

    # Временный fallback, пока telegram_user_id не заполнены.
    if username:
        for employee in get_employees(include_inactive=True):
            if employee["telegram_username"] == username:
                return employee

    return None


def is_manager(employee):
    return bool(employee and employee.get("role") in {"warehouse_manager", "admin"})


def get_kpi_items(active_only=True):
    ws = get_worksheet(KPI_SHEET)
    records = records_from_worksheet(ws)
    items = []
    for record in records:
        if not record.get("kpi_id"):
            continue
        item = {
            "kpi_id": str(record.get("kpi_id", "")).strip(),
            "name": str(record.get("Название", "")).strip(),
            "rate": safe_float(record.get("Ставка")),
            "is_active": safe_bool(record.get("Активно")),
        }
        if active_only and not item["is_active"]:
            continue
        items.append(item)
    return items


def find_report_row(employee_id, report_date):
    ws = get_worksheet(REPORTS_SHEET)
    values = ws.get_all_values()
    if len(values) <= 1:
        return None, None

    headers = values[0]
    for index, row in enumerate(values[1:], start=2):
        row_data = dict(zip(headers, row))
        if row_data.get("employee_id") == employee_id and row_data.get("Дата") == report_date:
            return index, row_data
    return None, None


def report_exists(employee_id, report_date):
    row_index, _ = find_report_row(employee_id, report_date)
    return row_index is not None


def kpi_to_json(kpi_items):
    return json.dumps(kpi_items or [], ensure_ascii=False)


def kpi_from_json(value):
    try:
        if not value:
            return []
        return json.loads(value)
    except Exception:
        return []


def calculate_kpi_sum(kpi_items):
    total = 0.0
    for item in kpi_items or []:
        qty = safe_float(item.get("qty"))
        rate = safe_float(item.get("rate"))
        total += qty * rate
    return total


def append_daily_report(employee, report_date, interval, hours, tasks, kpi_items, telegram_data=None):
    telegram_data = telegram_data or {}
    ws = get_worksheet(REPORTS_SHEET)
    report_id = generate_id("report")
    created_at = now_str()
    kpi_sum = calculate_kpi_sum(kpi_items)

    row = [
        report_id,
        report_date,
        employee["employee_id"],
        employee["full_name"],
        employee.get("telegram_user_id", ""),
        interval,
        hours,
        tasks,
        kpi_to_json(kpi_items),
        kpi_sum,
        telegram_data.get("chat_id", ""),
        telegram_data.get("thread_id", ""),
        telegram_data.get("message_id", ""),
        created_at,
        created_at,
    ]
    ws.append_row(row)
    return report_id


def update_daily_report(row_index, report_data):
    ws = get_worksheet(REPORTS_SHEET)
    values = [[report_data.get(header, "") for header in REPORT_HEADERS]]
    ws.update(f"A{row_index}:O{row_index}", values)


def update_report_message_ids(row_index, chat_id, thread_id, message_id):
    _, report_data = find_report_by_row(row_index)
    if not report_data:
        return
    report_data["telegram_chat_id"] = str(chat_id or "")
    report_data["telegram_thread_id"] = str(thread_id or "")
    report_data["telegram_message_id"] = str(message_id or "")
    report_data["Обновлено"] = now_str()
    update_daily_report(row_index, report_data)


def find_report_by_row(row_index):
    ws = get_worksheet(REPORTS_SHEET)
    values = ws.get_all_values()
    if row_index < 2 or row_index > len(values):
        return None, None
    headers = values[0]
    row_data = dict(zip(headers, values[row_index - 1]))
    return row_index, row_data


def report_data_to_model(report_data):
    employee = get_employee_by_id(report_data.get("employee_id")) or {
        "employee_id": report_data.get("employee_id", ""),
        "full_name": report_data.get("ФИО", ""),
        "telegram_user_id": report_data.get("telegram_user_id", ""),
    }
    return {
        "report_id": report_data.get("report_id", ""),
        "date": report_data.get("Дата", ""),
        "employee": employee,
        "interval": report_data.get("Рабочий промежуток", ""),
        "hours": safe_float(report_data.get("Отработано часов")),
        "tasks": report_data.get("Задачи", ""),
        "kpi_items": kpi_from_json(report_data.get("KPI данные", "")),
        "kpi_sum": safe_float(report_data.get("KPI сумма")),
        "telegram_chat_id": report_data.get("telegram_chat_id", ""),
        "telegram_thread_id": report_data.get("telegram_thread_id", ""),
        "telegram_message_id": report_data.get("telegram_message_id", ""),
        "created_at": report_data.get("Создано", ""),
        "updated_at": report_data.get("Обновлено", ""),
    }


def append_expense(employee, expense_date, comment, amount, created_by):
    ws = get_worksheet(EXPENSES_SHEET)
    ws.append_row([
        generate_id("expense"),
        expense_date,
        employee["employee_id"],
        employee["full_name"],
        comment,
        safe_float(amount),
        created_by,
        now_str(),
    ])


def append_penalty(employee, penalty_date, comment, amount, created_by):
    ws = get_worksheet(PENALTIES_SHEET)
    ws.append_row([
        generate_id("penalty"),
        penalty_date,
        employee["employee_id"],
        employee["full_name"],
        comment,
        safe_float(amount),
        created_by,
        now_str(),
    ])


def get_reports_in_period(start_date, end_date):
    ws = get_worksheet(REPORTS_SHEET)
    reports = []
    for record in records_from_worksheet(ws):
        if date_in_range(record.get("Дата", ""), start_date, end_date):
            reports.append(report_data_to_model(record))
    return reports


def get_expenses_in_period(start_date, end_date):
    ws = get_worksheet(EXPENSES_SHEET)
    expenses = []
    for record in records_from_worksheet(ws):
        if date_in_range(record.get("Дата", ""), start_date, end_date):
            expenses.append({
                "employee_id": str(record.get("employee_id", "")),
                "amount": safe_float(record.get("Сумма")),
                "comment": str(record.get("Комментарий", "")),
                "date": str(record.get("Дата", "")),
            })
    return expenses


def get_penalties_in_period(start_date, end_date):
    ws = get_worksheet(PENALTIES_SHEET)
    penalties = []
    for record in records_from_worksheet(ws):
        if date_in_range(record.get("Дата", ""), start_date, end_date):
            penalties.append({
                "employee_id": str(record.get("employee_id", "")),
                "amount": safe_float(record.get("Сумма")),
                "comment": str(record.get("Комментарий", "")),
                "date": str(record.get("Дата", "")),
            })
    return penalties


def get_periods():
    ws = get_worksheet(PERIODS_SHEET)
    periods = []
    for record in records_from_worksheet(ws):
        if not record.get("period_id"):
            continue
        periods.append({
            "period_id": str(record.get("period_id", "")),
            "name": str(record.get("Название", "")),
            "start_date": str(record.get("Дата начала", "")),
            "end_date": str(record.get("Дата конца", "")),
            "status": str(record.get("Статус", "")),
            "created_by": str(record.get("Создал", "")),
            "created_at": str(record.get("Создано", "")),
            "updated_at": str(record.get("Обновлено", "")),
        })
    return periods


def find_active_period_row():
    ws = get_worksheet(PERIODS_SHEET)
    values = ws.get_all_values()
    if len(values) <= 1:
        return None, None
    headers = values[0]
    for index, row in enumerate(values[1:], start=2):
        data = dict(zip(headers, row))
        if str(data.get("Статус", "")).lower() == "active":
            return index, data
    return None, None


def get_active_period():
    _, data = find_active_period_row()
    if not data:
        return None
    return {
        "period_id": data.get("period_id", ""),
        "name": data.get("Название", ""),
        "start_date": data.get("Дата начала", ""),
        "end_date": data.get("Дата конца", ""),
        "status": data.get("Статус", ""),
        "created_by": data.get("Создал", ""),
        "created_at": data.get("Создано", ""),
        "updated_at": data.get("Обновлено", ""),
    }


def close_active_periods():
    ws = get_worksheet(PERIODS_SHEET)
    values = ws.get_all_values()
    if len(values) <= 1:
        return
    headers = values[0]
    for index, row in enumerate(values[1:], start=2):
        data = dict(zip(headers, row))
        if str(data.get("Статус", "")).lower() == "active":
            data["Статус"] = "closed"
            data["Обновлено"] = now_str()
            ws.update(f"A{index}:H{index}", [[data.get(header, "") for header in PERIOD_HEADERS]])


def create_active_period(name, start_date, end_date, created_by):
    close_active_periods()
    ws = get_worksheet(PERIODS_SHEET)
    created_at = now_str()
    period_id = generate_id("period")
    ws.append_row([
        period_id,
        name,
        start_date,
        end_date,
        "active",
        created_by,
        created_at,
        created_at,
    ])
    return period_id


def update_active_period(name=None, start_date=None, end_date=None):
    ws = get_worksheet(PERIODS_SHEET)
    row_index, data = find_active_period_row()
    if not data:
        return False
    if name is not None:
        data["Название"] = name
    if start_date is not None:
        data["Дата начала"] = start_date
    if end_date is not None:
        data["Дата конца"] = end_date
    data["Обновлено"] = now_str()
    ws.update(f"A{row_index}:H{row_index}", [[data.get(header, "") for header in PERIOD_HEADERS]])
    return True


def cleanup_old_operational_data(days=365):
    cutoff = datetime.now() - timedelta(days=days)
    result = {}

    for title, date_header in [
        (REPORTS_SHEET, "Дата"),
        (EXPENSES_SHEET, "Дата"),
        (PENALTIES_SHEET, "Дата"),
    ]:
        ws = get_worksheet(title)
        values = ws.get_all_values()
        if len(values) <= 1:
            result[title] = 0
            continue

        headers = values[0]
        rows_to_delete = []
        for index, row in enumerate(values[1:], start=2):
            data = dict(zip(headers, row))
            try:
                row_date = parse_date(data.get(date_header, ""))
            except ValueError:
                continue
            if row_date < cutoff:
                rows_to_delete.append(index)

        # Удаляем снизу вверх, чтобы индексы не съезжали.
        for row_index in reversed(rows_to_delete):
            ws.delete_rows(row_index)

        result[title] = len(rows_to_delete)

    return result
