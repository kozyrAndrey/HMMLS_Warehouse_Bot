from modules.schedule.config import date_to_str
from modules.tasks.config import TASK_STATUS_CANCELLED, TASK_STATUS_DONE, TASK_TYPE_GENERAL, TASK_TYPE_WAREHOUSE


def employee_mention(employee):
    username = str(employee.get("telegram_username", "")).strip().lstrip("@")
    return f"@{username}" if username else employee.get("full_name", "")


def task_checkbox(status):
    if status == TASK_STATUS_DONE:
        return "✅"
    if status == TASK_STATUS_CANCELLED:
        return "🚫"
    return "⬜"


def format_assignees(record):
    return str(record.get("Исполнители", "")).strip() or "не назначены"


def format_task_line(index, record, include_assignees=True):
    status = str(record.get("Статус", "")).strip()
    description = str(record.get("Описание", "")).strip()
    deadline = str(record.get("Дедлайн", "")).strip()

    lines = [f"{task_checkbox(status)} {index}. {description}"]
    if include_assignees:
        lines.append(f"Исполнители: {format_assignees(record)}")
    if deadline:
        lines.append(f"Дедлайн: {deadline}")
    return "\n".join(lines)


def filter_active_export_tasks(tasks, task_type):
    return [
        task for task in tasks
        if str(task.get("Тип задачи", "")).strip() == task_type
        and str(task.get("Статус", "")).strip() != TASK_STATUS_CANCELLED
    ]


def format_warehouse_tasks_message(day, tasks):
    warehouse_tasks = filter_active_export_tasks(tasks, TASK_TYPE_WAREHOUSE)
    if not warehouse_tasks:
        return f"📋 Складские задачи на {date_to_str(day)}\n\nЗадач пока нет"

    lines = [f"📋 Складские задачи на {date_to_str(day)}", ""]
    for index, task in enumerate(warehouse_tasks, start=1):
        lines.append(format_task_line(index, task, include_assignees=True))
        lines.append("")
    return "\n".join(lines).strip()


def format_general_tasks_message(day, tasks):
    general_tasks = filter_active_export_tasks(tasks, TASK_TYPE_GENERAL)
    if not general_tasks:
        return f"📋 Нескладские задачи на {date_to_str(day)}\n\nЗадач пока нет"

    lines = [f"📋 Нескладские задачи на {date_to_str(day)}", ""]
    for index, task in enumerate(general_tasks, start=1):
        lines.append(format_task_line(index, task, include_assignees=False))
        lines.append("")
    return "\n".join(lines).strip()


def format_all_tasks_for_private_view(day, tasks):
    warehouse_tasks = [task for task in tasks if str(task.get("Тип задачи", "")).strip() == TASK_TYPE_WAREHOUSE]
    general_tasks = [task for task in tasks if str(task.get("Тип задачи", "")).strip() == TASK_TYPE_GENERAL]

    lines = [f"📋 Задачи на {date_to_str(day)}", "", "Складские:"]
    if warehouse_tasks:
        for index, task in enumerate(warehouse_tasks, start=1):
            lines.append(format_task_line(index, task, include_assignees=True))
            lines.append("")
    else:
        lines.append("Задач пока нет")
        lines.append("")

    lines.append("Нескладские:")
    if general_tasks:
        for index, task in enumerate(general_tasks, start=1):
            lines.append(format_task_line(index, task, include_assignees=False))
            lines.append("")
    else:
        lines.append("Задач пока нет")

    return "\n".join(lines).strip()


def format_daily_staff_message(day, employees, schedule, duty_by_date):
    date_str = date_to_str(day)
    rows = []

    for employee in employees:
        employee_id = employee["employee_id"]
        shift_time = str(schedule.get(employee_id, {}).get(date_str, "")).strip()
        if not shift_time:
            continue
        suffix = ", дежурный" if duty_by_date.get(date_str) == employee_id else ""
        rows.append((shift_time, f"к {shift_time} {employee_mention(employee)}{suffix}"))

    if not rows:
        return "👋 утро доброе\n\nсегодня в танке никого нет"

    rows.sort(key=lambda item: item[0])
    return "👋 утро доброе\n\nсегодня в танке 🇷🇺\n\n" + "\n".join(row[1] for row in rows)
