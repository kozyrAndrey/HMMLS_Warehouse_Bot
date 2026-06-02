import uuid
from datetime import timedelta

from modules.payroll.google_sheets import column_letter, get_employees, now_str
from modules.schedule.config import date_to_str, parse_date
from modules.schedule.google_sheets import ensure_headers, get_schedule_matrix, get_schedule_worksheet
from modules.tasks.config import (
    ASSIGNEE_MODE_NONE,
    ASSIGNEE_MODE_SPECIFIC,
    ASSIGNEE_MODE_WORKING_TODAY,
    DEFAULT_WEEKLY_TASK_TEMPLATES,
    TASKS_SHEET,
    TASK_EXPORTS_SHEET,
    TASK_SOURCE_MANUAL,
    TASK_SOURCE_TEMPLATE,
    TASK_STATUS_ACTIVE,
    TASK_STATUS_DONE,
    TASK_TEMPLATES_SHEET,
    TASK_TYPE_WAREHOUSE,
    WAREHOUSE_MANAGER_ROLE,
    WEEKDAY_NAMES,
    get_week_start_for_date,
)

TASK_HEADERS = [
    "task_id", "Дата", "Тип задачи", "Описание", "Исполнители ID", "Исполнители",
    "Дедлайн", "Статус", "Источник", "template_id", "Создал", "Создано", "Обновлено",
    "Выполнил ID", "Выполнил", "Выполнено",
]

TASK_TEMPLATE_HEADERS = [
    "template_id", "День недели", "weekday", "Тип задачи", "Описание", "Тип исполнителей",
    "Исполнители ID", "Исполнители", "Дедлайн", "Активно", "Создано", "Обновлено",
]

TASK_EXPORT_HEADERS = [
    "Дата", "Тип выгрузки", "chat_id", "thread_id", "message_id", "Версия", "Создано", "Обновлено",
]


def generate_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def get_tasks_worksheet(title, rows=1000, cols=30):
    return get_schedule_worksheet(title, rows=rows, cols=cols)


def task_records(ws):
    return ws.get_all_records(numericise_ignore=["all"])


def init_tasks_sheet():
    tasks_ws = get_tasks_worksheet(TASKS_SHEET, rows=3000, cols=30)
    templates_ws = get_tasks_worksheet(TASK_TEMPLATES_SHEET, rows=1000, cols=20)
    exports_ws = get_tasks_worksheet(TASK_EXPORTS_SHEET, rows=500, cols=12)

    ensure_headers(tasks_ws, TASK_HEADERS)
    ensure_headers(templates_ws, TASK_TEMPLATE_HEADERS)
    ensure_headers(exports_ws, TASK_EXPORT_HEADERS)

    seed_default_task_templates_if_empty()
    return True


def seed_default_task_templates_if_empty():
    ws = get_tasks_worksheet(TASK_TEMPLATES_SHEET)
    if task_records(ws):
        return

    rows = []
    for item in DEFAULT_WEEKLY_TASK_TEMPLATES:
        weekday = int(item["weekday"])
        rows.append(
            [
                generate_id("tpl"), WEEKDAY_NAMES[weekday], weekday, item["task_type"], item["description"],
                item.get("assignee_mode", ASSIGNEE_MODE_NONE), "", "", item.get("deadline", ""),
                "TRUE", now_str(), now_str(),
            ]
        )
    if rows:
        ws.append_rows(rows)


def get_task_by_id(task_id):
    ws = get_tasks_worksheet(TASKS_SHEET)
    for index, record in enumerate(task_records(ws), start=2):
        if str(record.get("task_id", "")).strip() == str(task_id):
            return index, record
    return None, None


def get_tasks_by_date(day, include_cancelled=True):
    date_str = date_to_str(day)
    ws = get_tasks_worksheet(TASKS_SHEET)
    result = []
    for record in task_records(ws):
        if str(record.get("Дата", "")).strip() != date_str:
            continue
        if not include_cancelled and str(record.get("Статус", "")).strip() == "cancelled":
            continue
        result.append(record)
    return result


def normalize_employee_list(employees):
    ids = []
    names = []
    for employee in employees or []:
        employee_id = str(employee.get("employee_id", "")).strip()
        if not employee_id:
            continue
        ids.append(employee_id)
        username = str(employee.get("telegram_username", "")).strip().lstrip("@")
        names.append(f"@{username}" if username else employee.get("full_name", employee_id))
    return ",".join(ids), ", ".join(names)


def get_employees_by_ids(employee_ids):
    wanted = {item.strip() for item in str(employee_ids or "").split(",") if item.strip()}
    if not wanted:
        return []
    return [
        employee for employee in get_employees(include_inactive=False)
        if str(employee.get("employee_id", "")).strip() in wanted
    ]


def get_working_employees_for_date(day):
    if isinstance(day, str):
        day = parse_date(day)

    week_start = get_week_start_for_date(day)
    date_str = date_to_str(day)
    employees, dates, schedule, duty_by_date = get_schedule_matrix(week_start)

    working = []
    for employee in employees:
        shift_time = str(schedule.get(employee["employee_id"], {}).get(date_str, "")).strip()
        if shift_time:
            item = dict(employee)
            item["shift_time"] = shift_time
            working.append(item)
    return working


def create_task(day, task_type, description, assignee_employees=None, deadline="", source=TASK_SOURCE_MANUAL, template_id="", created_by="bot"):
    ws = get_tasks_worksheet(TASKS_SHEET)
    employee_ids, employee_names = normalize_employee_list(assignee_employees)

    row = [
        generate_id("task"), date_to_str(day), task_type, str(description).strip(),
        employee_ids, employee_names, deadline or "", TASK_STATUS_ACTIVE, source, template_id or "",
        created_by, now_str(), now_str(), "", "", "",
    ]
    ws.append_row(row)
    return row[0]


def update_task_row(row_index, record):
    ws = get_tasks_worksheet(TASKS_SHEET)
    row = [record.get(header, "") for header in TASK_HEADERS]
    end_col = column_letter(len(TASK_HEADERS))
    ws.update(f"A{row_index}:{end_col}{row_index}", [row])


def update_task_fields(task_id, **fields):
    row_index, record = get_task_by_id(task_id)
    if not record:
        return False
    for key, value in fields.items():
        record[key] = value
    record["Обновлено"] = now_str()
    update_task_row(row_index, record)
    return True


def set_task_assignees(task_id, employees):
    employee_ids, employee_names = normalize_employee_list(employees)
    return update_task_fields(task_id, **{"Исполнители ID": employee_ids, "Исполнители": employee_names})


def mark_task_done(task_id, employee, done=True):
    return update_task_fields(
        task_id,
        **{
            "Статус": TASK_STATUS_DONE if done else TASK_STATUS_ACTIVE,
            "Выполнил ID": str(employee.get("telegram_user_id", "")).strip() if done and employee else "",
            "Выполнил": employee.get("full_name", "") if done and employee else "",
            "Выполнено": now_str() if done else "",
        },
    )


def get_task_templates(active_only=True):
    ws = get_tasks_worksheet(TASK_TEMPLATES_SHEET)
    result = []
    for record in task_records(ws):
        if active_only and str(record.get("Активно", "")).strip().lower() not in {"true", "1", "yes", "да", "истина"}:
            continue
        result.append(record)
    return result


def template_task_exists(day, template_id):
    for record in get_tasks_by_date(day):
        if (
            str(record.get("Источник", "")).strip() == TASK_SOURCE_TEMPLATE
            and str(record.get("template_id", "")).strip() == str(template_id)
        ):
            return True
    return False


def resolve_template_assignees(template, day):
    mode = str(template.get("Тип исполнителей", "")).strip() or ASSIGNEE_MODE_NONE
    if mode == ASSIGNEE_MODE_WORKING_TODAY:
        return get_working_employees_for_date(day)
    if mode == ASSIGNEE_MODE_SPECIFIC:
        return get_employees_by_ids(template.get("Исполнители ID", ""))
    return []


def materialize_templates_for_date(day):
    if isinstance(day, str):
        day = parse_date(day)

    created_count = 0
    for template in get_task_templates(active_only=True):
        try:
            weekday = int(str(template.get("weekday", "")).strip())
        except ValueError:
            continue
        if weekday != day.weekday():
            continue

        template_id = str(template.get("template_id", "")).strip()
        if not template_id or template_task_exists(day, template_id):
            continue

        create_task(
            day=day,
            task_type=str(template.get("Тип задачи", "")).strip(),
            description=str(template.get("Описание", "")).strip(),
            assignee_employees=resolve_template_assignees(template, day),
            deadline=str(template.get("Дедлайн", "")).strip(),
            source=TASK_SOURCE_TEMPLATE,
            template_id=template_id,
            created_by="template",
        )
        created_count += 1
    return created_count


def materialize_templates_for_period(start_day, end_day):
    current = start_day
    total = 0
    while current <= end_day:
        total += materialize_templates_for_date(current)
        current += timedelta(days=1)
    return total


def materialize_next_week_templates(base_day):
    next_monday = base_day + timedelta(days=(7 - base_day.weekday()))
    return materialize_templates_for_period(next_monday, next_monday + timedelta(days=6))


def add_task_to_template(record, assignee_mode=None):
    ws = get_tasks_worksheet(TASK_TEMPLATES_SHEET)
    date_value = parse_date(record.get("Дата", ""))
    task_type = str(record.get("Тип задачи", "")).strip()

    if assignee_mode is None:
        if task_type == TASK_TYPE_WAREHOUSE and str(record.get("Исполнители ID", "")).strip():
            assignee_mode = ASSIGNEE_MODE_SPECIFIC
        elif task_type == TASK_TYPE_WAREHOUSE:
            assignee_mode = ASSIGNEE_MODE_WORKING_TODAY
        else:
            assignee_mode = ASSIGNEE_MODE_NONE

    row = [
        generate_id("tpl"), WEEKDAY_NAMES[date_value.weekday()], date_value.weekday(), task_type,
        str(record.get("Описание", "")).strip(), assignee_mode,
        str(record.get("Исполнители ID", "")).strip() if assignee_mode == ASSIGNEE_MODE_SPECIFIC else "",
        str(record.get("Исполнители", "")).strip() if assignee_mode == ASSIGNEE_MODE_SPECIFIC else "",
        str(record.get("Дедлайн", "")).strip(), "TRUE", now_str(), now_str(),
    ]
    ws.append_row(row)
    return row[0]


def get_export_row(day, export_type):
    date_str = date_to_str(day)
    ws = get_tasks_worksheet(TASK_EXPORTS_SHEET)
    for index, record in enumerate(task_records(ws), start=2):
        if str(record.get("Дата", "")).strip() == date_str and str(record.get("Тип выгрузки", "")).strip() == export_type:
            return index, record
    return None, None


def upsert_task_export(day, export_type, chat_id, thread_id, message_id):
    ws = get_tasks_worksheet(TASK_EXPORTS_SHEET)
    row_index, record = get_export_row(day, export_type)

    version = 1
    created_at = now_str()
    if record:
        created_at = str(record.get("Создано", "")).strip() or created_at
        try:
            version = int(str(record.get("Версия", "0")).strip() or 0) + 1
        except ValueError:
            version = 1

    row = [date_to_str(day), export_type, chat_id, thread_id, message_id, version, created_at, now_str()]
    end_col = column_letter(len(TASK_EXPORT_HEADERS))
    if row_index:
        ws.update(f"A{row_index}:{end_col}{row_index}", [row])
    else:
        ws.append_row(row)


def get_task_export(day, export_type):
    row_index, record = get_export_row(day, export_type)
    if not record:
        return None
    return {
        "chat_id": str(record.get("chat_id", "")).strip(),
        "thread_id": str(record.get("thread_id", "")).strip(),
        "message_id": str(record.get("message_id", "")).strip(),
    }


def get_warehouse_managers():
    return [
        employee for employee in get_employees(include_inactive=False)
        if employee.get("role") == WAREHOUSE_MANAGER_ROLE and str(employee.get("telegram_user_id", "")).strip()
    ]


def can_user_complete_task(user, task_record, employee):
    if not employee:
        return False
    if employee.get("role") in {"warehouse_manager", "brand_manager"}:
        return True
    if str(task_record.get("Тип задачи", "")).strip() != TASK_TYPE_WAREHOUSE:
        return False

    assignee_ids = {item.strip() for item in str(task_record.get("Исполнители ID", "")).split(",") if item.strip()}
    if not assignee_ids:
        return employee.get("role") == "warehouse_employee"
    return str(employee.get("employee_id", "")).strip() in assignee_ids
