from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from modules.payroll.config import MANAGER_ROLES
from modules.payroll.google_sheets import get_employees

MSK_TZ = ZoneInfo("Europe/Moscow")

SCHEDULE_SHEET = "Расписание"
SCHEDULE_ARCHIVE_SHEET = "Архив расписаний"
SCHEDULE_DUTIES_SHEET = "Дежурства"
SCHEDULE_EXPORTS_SHEET = "Выгрузки расписания"

SHIFT_TIMES = ["11:00", "12:00", "13:00", "14:00", "15:00"]
WEEKDAY_SHORT = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]

# Руководитель бренда имеет руководительский функционал, но не участвует в расписании.
SCHEDULE_EXCLUDED_ROLES = {"brand_manager"}


def today_msk():
    return datetime.now(MSK_TZ).date()


def parse_date(value):
    return datetime.strptime(str(value).strip(), "%d.%m.%Y").date()


def date_to_str(value):
    if isinstance(value, str):
        return value
    return value.strftime("%d.%m.%Y")


def day_label(value):
    if isinstance(value, str):
        value = parse_date(value)
    return f"{WEEKDAY_SHORT[value.weekday()]} {value.strftime('%d.%m')}"


def next_week_start(base_date=None):
    current = base_date or today_msk()
    days_until_next_monday = 7 - current.weekday()
    if days_until_next_monday <= 0:
        days_until_next_monday = 7
    return current + timedelta(days=days_until_next_monday)


def week_dates(week_start):
    if isinstance(week_start, str):
        week_start = parse_date(week_start)
    return [week_start + timedelta(days=i) for i in range(7)]


def week_end(week_start):
    return week_dates(week_start)[-1]


def format_week_range(week_start):
    if isinstance(week_start, str):
        week_start = parse_date(week_start)
    end = week_end(week_start)
    return f"{week_start.strftime('%d.%m.%y')}-{end.strftime('%d.%m.%y')}"


def format_week_range_full(week_start):
    if isinstance(week_start, str):
        week_start = parse_date(week_start)
    end = week_end(week_start)
    return f"{week_start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"


def is_schedule_manager(employee):
    return bool(employee and employee.get("role") in MANAGER_ROLES)


def can_employee_submit_schedule(employee):
    return bool(
        employee
        and employee.get("is_active")
        and employee.get("role") not in SCHEDULE_EXCLUDED_ROLES
    )


def get_schedule_employees():
    employees = []
    for employee in get_employees(include_inactive=False):
        if can_employee_submit_schedule(employee):
            employees.append(employee)
    return employees


def get_schedule_employee_by_id(employee_id):
    for employee in get_schedule_employees():
        if employee["employee_id"] == str(employee_id):
            return employee
    return None


def get_reminder_mentions():
    mentions = []
    for employee in get_schedule_employees():
        username = str(employee.get("telegram_username", "")).strip().lstrip("@")
        if username:
            mentions.append(f"@{username}")
    return mentions
