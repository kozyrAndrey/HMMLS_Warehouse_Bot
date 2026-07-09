import logging
from datetime import time, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from config import GROUP_CHAT_ID, SCHEDULE_REMINDER_TOPIC_ID
from core.keyboards import build_main_menu_keyboard
from modules.payroll.google_sheets import find_employee_for_telegram_user, get_employees
from modules.schedule.config import MSK_TZ, date_to_str, day_label, parse_date, today_msk
from modules.schedule.google_sheets import get_schedule_matrix
from modules.tasks.config import (
    ASSIGNEE_MODE_NONE,
    ASSIGNEE_MODE_SPECIFIC,
    ASSIGNEE_MODE_WORKING_TODAY,
    NO_DEADLINE_TEXT,
    TASK_DEADLINES,
    TASK_SOURCE_MANUAL,
    TASK_STATUS_ACTIVE,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_DONE,
    TASK_TYPE_GENERAL,
    TASK_TYPE_WAREHOUSE,
    WEEKDAY_NAMES,
    is_tasks_manager,
)
from modules.tasks.formatting import (
    filter_active_export_tasks,
    format_all_tasks_for_private_view,
    format_daily_staff_message,
    format_general_tasks_message,
    format_regular_tasks_view,
    format_warehouse_tasks_message,
)
from modules.tasks.storage import (
    can_user_complete_task,
    create_task,
    create_task_template,
    delete_task_template,
    get_task_by_id,
    get_task_export,
    get_task_template_by_id,
    get_task_templates,
    get_tasks_by_date,
    get_warehouse_managers,
    get_working_employees_for_date,
    mark_task_done,
    materialize_next_week_templates,
    materialize_templates_for_date,
    set_task_assignees,
    set_task_template_assignees,
    update_task_fields,
    update_task_template_fields,
    upsert_task_export,
)


(
    TASK_ADD_TYPE,
    TASK_ADD_DATE,
    TASK_ADD_DESCRIPTION,
    TASK_ADD_ASSIGNEES,
    TASK_ADD_DEADLINE,
    TASK_VIEW_DATE,
    TASK_EXPORT_DATE,
    TASK_EDIT_DATE,
    TASK_EDIT_SELECT,
    TASK_EDIT_FIELD,
    TASK_EDIT_DESCRIPTION,
    TASK_EDIT_ASSIGNEES,
    TASK_EDIT_DEADLINE,
    TASK_DELETE_DATE,
    TASK_DELETE_SELECT,
    TASK_DELETE_CONFIRM,
    REG_ADD_WEEKDAY,
    REG_ADD_TYPE,
    REG_ADD_DESCRIPTION,
    REG_ADD_ASSIGNEE_MODE,
    REG_ADD_ASSIGNEES,
    REG_ADD_DEADLINE,
    REG_EDIT_DAY,
    REG_EDIT_SELECT,
    REG_EDIT_FIELD,
    REG_EDIT_DESCRIPTION,
    REG_EDIT_WEEKDAY,
    REG_EDIT_TYPE,
    REG_EDIT_ASSIGNEE_MODE,
    REG_EDIT_ASSIGNEES,
    REG_EDIT_DEADLINE,
    REG_DELETE_DAY,
    REG_DELETE_SELECT,
    REG_DELETE_CONFIRM,
) = range(1200, 1234)


def current_employee(update: Update):
    try:
        return find_employee_for_telegram_user(update.effective_user)
    except Exception:
        logging.exception("Не удалось определить сотрудника для задач")
        return None


def ensure_tasks_manager(update: Update):
    return is_tasks_manager(current_employee(update))


def tasks_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Задачи на день", callback_data="task:view")],
        [InlineKeyboardButton("➕ Добавить разовую задачу", callback_data="task:add")],
        [InlineKeyboardButton("✏️ Изменить задачу на день", callback_data="task:edit")],
        [InlineKeyboardButton("🚫 Отменить задачу на день", callback_data="task:delete")],
        [InlineKeyboardButton("📋 Шаблоны регулярных задач", callback_data="task:regular")],
        [InlineKeyboardButton("📤 Выгрузить задачи", callback_data="task:export")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")],
    ])


def regular_tasks_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить шаблон", callback_data="reg:add")],
        [InlineKeyboardButton("✏️ Изменить шаблон", callback_data="reg:edit")],
        [InlineKeyboardButton("🗑 Удалить шаблон", callback_data="reg:delete")],
        [InlineKeyboardButton("👀 Просмотр шаблонов", callback_data="reg:view")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="section:tasks")],
    ])


def task_type_keyboard(cancel_callback="task:cancel"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Складская", callback_data="tasktype:warehouse")],
        [InlineKeyboardButton("🧩 Нескладская", callback_data="tasktype:general")],
        [InlineKeyboardButton("❌ Отмена", callback_data=cancel_callback)],
    ])


def date_keyboard(prefix, days=14):
    rows = []
    current = today_msk()
    for offset in range(days):
        day = current + timedelta(days=offset)
        rows.append([InlineKeyboardButton(day_label(day), callback_data=f"{prefix}:{date_to_str(day)}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def weekday_keyboard(prefix):
    rows = []
    for index, name in enumerate(WEEKDAY_NAMES):
        rows.append([InlineKeyboardButton(name, callback_data=f"{prefix}:{index}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def deadline_keyboard():
    rows = []
    for index in range(0, len(TASK_DEADLINES), 3):
        rows.append([InlineKeyboardButton(value, callback_data=f"taskdeadline:{value}") for value in TASK_DEADLINES[index:index + 3]])
    rows.append([InlineKeyboardButton(NO_DEADLINE_TEXT, callback_data="taskdeadline:none")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def assignee_mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Все, кто работает в этот день", callback_data="regassigneemode:working_today")],
        [InlineKeyboardButton("Конкретные сотрудники", callback_data="regassigneemode:specific")],
        [InlineKeyboardButton("Без исполнителей", callback_data="regassigneemode:none")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


def employee_label(employee, selected_ids):
    mark = "✅" if employee["employee_id"] in selected_ids else "⬜️"
    username = str(employee.get("telegram_username", "")).strip().lstrip("@")
    return f"{mark} {employee['full_name']}" + (f" @{username}" if username else "")


def assignees_keyboard(working, selected_ids):
    selected_ids = set(selected_ids or [])
    rows = [
        [InlineKeyboardButton(employee_label(employee, selected_ids), callback_data=f"taskassignee:{employee['employee_id']}")]
        for employee in working
    ]
    rows.append([InlineKeyboardButton("✅ Завершить выбор", callback_data="taskassignee:done")])
    rows.append([InlineKeyboardButton("👤 Без исполнителей", callback_data="taskassignee:none")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def regular_assignees_keyboard(selected_ids):
    selected_ids = set(selected_ids or [])
    employees = get_employees(include_inactive=False)
    rows = [
        [InlineKeyboardButton(employee_label(employee, selected_ids), callback_data=f"regassignee:{employee['employee_id']}")]
        for employee in employees
    ]
    rows.append([InlineKeyboardButton("✅ Завершить выбор", callback_data="regassignee:done")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def task_select_keyboard(tasks, prefix):
    rows = []
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        status = str(task.get("Статус", "")).strip()
        icon = "✅" if status == TASK_STATUS_DONE else "🚫" if status == TASK_STATUS_CANCELLED else "⬜"
        description = str(task.get("Описание", "")).strip()
        if len(description) > 45:
            description = description[:42] + "..."
        rows.append([InlineKeyboardButton(f"{icon} {description}", callback_data=f"{prefix}:{task_id}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def regular_task_select_keyboard(templates, prefix):
    rows = []
    for template in templates:
        template_id = str(template.get("template_id", "")).strip()
        description = str(template.get("Описание", "")).strip()
        if len(description) > 45:
            description = description[:42] + "..."
        rows.append([InlineKeyboardButton(description, callback_data=f"{prefix}:{template_id}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def regular_templates_for_weekday(weekday):
    weekday = int(weekday)
    return [
        template for template in get_task_templates(active_only=True)
        if int(template.get("weekday", -1)) == weekday
    ]


def edit_field_keyboard(task):
    task_type = str(task.get("Тип задачи", "")).strip()
    rows = [[InlineKeyboardButton("📝 Описание", callback_data="taskeditfield:description")]]
    if task_type == TASK_TYPE_WAREHOUSE:
        rows.append([InlineKeyboardButton("👥 Исполнители", callback_data="taskeditfield:assignees")])
    rows.extend([
        [InlineKeyboardButton("⏰ Дедлайн", callback_data="taskeditfield:deadline")],
        [InlineKeyboardButton("✅ Статус", callback_data="taskeditfield:status")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


def regular_edit_field_keyboard(template):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Описание", callback_data="regeditfield:description")],
        [InlineKeyboardButton("📅 День недели", callback_data="regeditfield:weekday")],
        [InlineKeyboardButton("📦 Тип задачи", callback_data="regeditfield:type")],
        [InlineKeyboardButton("👥 Исполнители", callback_data="regeditfield:assignees")],
        [InlineKeyboardButton("⏰ Дедлайн", callback_data="regeditfield:deadline")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


def status_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬜ Невыполнено", callback_data="taskstatus:active")],
        [InlineKeyboardButton("✅ Выполнено", callback_data="taskstatus:done")],
        [InlineKeyboardButton("🚫 Отменено", callback_data="taskstatus:cancelled")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


def confirm_keyboard(prefix, item_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data=f"{prefix}:yes:{item_id}")],
        [InlineKeyboardButton("Отмена", callback_data="task:cancel")],
    ])


def warehouse_tasks_inline_keyboard(tasks):
    rows = []
    for task in filter_active_export_tasks(tasks, TASK_TYPE_WAREHOUSE):
        icon = "✅" if str(task.get("Статус", "")).strip() == TASK_STATUS_DONE else "⬜"
        description = str(task.get("Описание", "")).strip()
        if len(description) > 45:
            description = description[:42] + "..."
        rows.append([InlineKeyboardButton(f"{icon} {description}", callback_data=f"taskdone:{task.get('task_id')}")])
    return InlineKeyboardMarkup(rows) if rows else None


async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not ensure_tasks_manager(update):
        await query.edit_message_text("⛔️ Раздел задач доступен только руководителям.", reply_markup=build_main_menu_keyboard())
        return ConversationHandler.END
    context.user_data.clear()
    await query.edit_message_text("🧩 Задачи:", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("📋 Шаблоны регулярных задач:", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def irregular_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🧩 Задачи:", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def tasks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    section = context.user_data.get("task_section")
    context.user_data.clear()
    reply_markup = regular_tasks_menu_keyboard() if section == "regular" else tasks_menu_keyboard()
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Действие отменено.", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Действие отменено.", reply_markup=reply_markup)
    return ConversationHandler.END


async def irregular_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "daily"
    await query.edit_message_text("Выберите тип разовой задачи:", reply_markup=task_type_keyboard())
    return TASK_ADD_TYPE


async def task_add_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["task_type"] = query.data.replace("tasktype:", "")
    await query.edit_message_text("Выберите дату:", reply_markup=date_keyboard("taskdate"))
    return TASK_ADD_DATE


async def task_add_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["task_date"] = query.data.replace("taskdate:", "")
    await query.edit_message_text(f"Дата: {context.user_data['task_date']}\n\nВведите описание задачи:")
    return TASK_ADD_DESCRIPTION


async def task_add_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("Описание не должно быть пустым. Введите описание задачи:")
        return TASK_ADD_DESCRIPTION
    context.user_data["task_description"] = description

    if context.user_data.get("task_type") == TASK_TYPE_GENERAL:
        await update.message.reply_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return TASK_ADD_DEADLINE

    day = parse_date(context.user_data["task_date"])
    working = get_working_employees_for_date(day)
    context.user_data["selected_employee_ids"] = []
    if not working:
        await update.message.reply_text(
            "На эту дату пока нет сотрудников в расписании. Задачу можно создать без исполнителей.\n\nВыберите дедлайн:",
            reply_markup=deadline_keyboard(),
        )
        return TASK_ADD_DEADLINE

    await update.message.reply_text("Выберите исполнителей из тех, кто работает в выбранный день:", reply_markup=assignees_keyboard(working, []))
    return TASK_ADD_ASSIGNEES


async def task_assignee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.replace("taskassignee:", "")
    day = parse_date(context.user_data["task_date"] if "task_date" in context.user_data else context.user_data["edit_task_date"])
    working = get_working_employees_for_date(day)

    if value == "none":
        context.user_data["selected_employee_ids"] = []
        if "edit_task_id" in context.user_data:
            set_task_assignees(context.user_data["edit_task_id"], [])
            await refresh_existing_exports_for_date(context, day)
            context.user_data.clear()
            await query.edit_message_text("Исполнители очищены ✅", reply_markup=tasks_menu_keyboard())
            return ConversationHandler.END
        await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return TASK_ADD_DEADLINE

    if value == "done":
        selected_ids = set(context.user_data.get("selected_employee_ids", []))
        selected = [employee for employee in working if employee["employee_id"] in selected_ids]
        if "edit_task_id" in context.user_data:
            set_task_assignees(context.user_data["edit_task_id"], selected)
            await refresh_existing_exports_for_date(context, day)
            context.user_data.clear()
            await query.edit_message_text("Исполнители обновлены ✅", reply_markup=tasks_menu_keyboard())
            return ConversationHandler.END
        await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return TASK_ADD_DEADLINE

    selected = set(context.user_data.get("selected_employee_ids", []))
    selected.remove(value) if value in selected else selected.add(value)
    context.user_data["selected_employee_ids"] = list(selected)
    await query.edit_message_text("Выберите исполнителей:", reply_markup=assignees_keyboard(working, selected))
    return TASK_EDIT_ASSIGNEES if "edit_task_id" in context.user_data else TASK_ADD_ASSIGNEES


async def task_deadline_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.replace("taskdeadline:", "")
    deadline = "" if value == "none" else value

    if "edit_task_id" in context.user_data:
        update_task_fields(context.user_data["edit_task_id"], **{"Дедлайн": deadline})
        _, task = get_task_by_id(context.user_data["edit_task_id"])
        await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
        context.user_data.clear()
        await query.edit_message_text("Дедлайн обновлен ✅", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END

    if "edit_template_id" in context.user_data:
        update_task_template_fields(context.user_data["edit_template_id"], **{"Дедлайн": deadline})
        context.user_data.clear()
        await query.edit_message_text("Дедлайн шаблона обновлен ✅", reply_markup=regular_tasks_menu_keyboard())
        return ConversationHandler.END

    if context.user_data.get("task_section") == "regular":
        context.user_data["regular_deadline"] = deadline
        return await finish_regular_task_creation(update, context)

    day = parse_date(context.user_data["task_date"])
    selected_ids = set(context.user_data.get("selected_employee_ids", []))
    assignees = []
    if context.user_data.get("task_type") == TASK_TYPE_WAREHOUSE and selected_ids:
        assignees = [employee for employee in get_working_employees_for_date(day) if employee["employee_id"] in selected_ids]

    employee = current_employee(update)
    create_task(
        day=day,
        task_type=context.user_data["task_type"],
        description=context.user_data["task_description"],
        assignee_employees=assignees,
        deadline=deadline,
        source=TASK_SOURCE_MANUAL,
        created_by=employee["full_name"] if employee else "manager",
    )
    await refresh_existing_exports_for_date(context, day)
    context.user_data.clear()
    await query.edit_message_text("Разовая задача создана ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def irregular_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["view_mode"] = "all"
    await query.edit_message_text("Выберите дату для просмотра задач:", reply_markup=date_keyboard("taskviewdate"))
    return TASK_VIEW_DATE


async def task_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["view_mode"] = "all"
    await query.edit_message_text("Выберите дату для просмотра задач:", reply_markup=date_keyboard("taskviewdate"))
    return TASK_VIEW_DATE


async def task_view_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskviewdate:", ""))
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
    reply_markup = tasks_menu_keyboard()
    await query.edit_message_text(format_all_tasks_for_private_view(day, tasks), reply_markup=reply_markup)
    return ConversationHandler.END


async def task_export_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Выберите дату для выгрузки задач:", reply_markup=date_keyboard("taskexportdate"))
    return TASK_EXPORT_DATE


async def task_export_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskexportdate:", ""))
    await query.edit_message_text(await export_tasks_for_date(context, day), reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def irregular_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "daily"
    await query.edit_message_text("Выберите дату:", reply_markup=date_keyboard("taskeditdate"))
    return TASK_EDIT_DATE


async def task_edit_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskeditdate:", ""))
    context.user_data["edit_task_date"] = date_to_str(day)
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day, include_cancelled=False)
    if not tasks:
        await query.edit_message_text("На эту дату задач пока нет.", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END
    await query.edit_message_text("Выберите задачу:", reply_markup=task_select_keyboard(tasks, "taskedit"))
    return TASK_EDIT_SELECT


async def task_edit_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.replace("taskedit:", "")
    _, task = get_task_by_id(task_id)
    if not task:
        await query.edit_message_text("Задача не найдена.", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END
    context.user_data["edit_task_id"] = task_id
    await query.edit_message_text("Что изменить?", reply_markup=edit_field_keyboard(task))
    return TASK_EDIT_FIELD


async def task_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("taskeditfield:", "")
    _, task = get_task_by_id(context.user_data["edit_task_id"])
    if field == "description":
        await query.edit_message_text("Введите новое описание:")
        return TASK_EDIT_DESCRIPTION
    if field == "deadline":
        await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return TASK_EDIT_DEADLINE
    if field == "assignees":
        day = parse_date(task["Дата"])
        context.user_data["selected_employee_ids"] = [x.strip() for x in str(task.get("Исполнители ID", "")).split(",") if x.strip()]
        await query.edit_message_text("Выберите исполнителей:", reply_markup=assignees_keyboard(get_working_employees_for_date(day), context.user_data["selected_employee_ids"]))
        return TASK_EDIT_ASSIGNEES
    if field == "status":
        await query.edit_message_text("Выберите статус:", reply_markup=status_keyboard())
        return TASK_EDIT_FIELD
    return ConversationHandler.END


async def task_edit_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_id = context.user_data["edit_task_id"]
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("Описание не должно быть пустым. Введите новое описание:")
        return TASK_EDIT_DESCRIPTION
    update_task_fields(task_id, **{"Описание": description})
    _, task = get_task_by_id(task_id)
    await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
    context.user_data.clear()
    await update.message.reply_text("Описание обновлено ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_status_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = {
        "active": TASK_STATUS_ACTIVE,
        "done": TASK_STATUS_DONE,
        "cancelled": TASK_STATUS_CANCELLED,
    }.get(query.data.replace("taskstatus:", ""), TASK_STATUS_ACTIVE)
    update_task_fields(context.user_data["edit_task_id"], **{"Статус": status})
    _, task = get_task_by_id(context.user_data["edit_task_id"])
    await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
    context.user_data.clear()
    await query.edit_message_text("Статус обновлен ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def irregular_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "daily"
    await query.edit_message_text("Выберите дату:", reply_markup=date_keyboard("taskdeldate"))
    return TASK_DELETE_DATE


async def task_delete_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskdeldate:", ""))
    context.user_data["delete_task_date"] = date_to_str(day)
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day, include_cancelled=False)
    if not tasks:
        await query.edit_message_text("На эту дату задач пока нет.", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END
    await query.edit_message_text("Выберите задачу для отмены на эту дату:", reply_markup=task_select_keyboard(tasks, "taskdel"))
    return TASK_DELETE_SELECT


async def task_delete_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.replace("taskdel:", "")
    _, task = get_task_by_id(task_id)
    if not task:
        await query.edit_message_text("Задача не найдена.", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END
    await query.edit_message_text(
        f"Отменить задачу на эту дату?\n\n{task.get('Описание', '')}",
        reply_markup=confirm_keyboard("taskdelconfirm", task_id),
    )
    return TASK_DELETE_CONFIRM


async def task_delete_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, task_id = query.data.split(":", 2)
    _, task = get_task_by_id(task_id)
    if task:
        update_task_fields(task_id, **{"Статус": TASK_STATUS_CANCELLED})
        await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
    context.user_data.clear()
    await query.edit_message_text("Задача отменена на выбранную дату ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        format_regular_tasks_view(get_task_templates(active_only=True)),
        reply_markup=regular_tasks_menu_keyboard(),
    )
    return ConversationHandler.END


async def regular_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "regular"
    await query.edit_message_text("Выберите день недели:", reply_markup=weekday_keyboard("regweekday"))
    return REG_ADD_WEEKDAY


async def regular_add_weekday_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["regular_weekday"] = int(query.data.replace("regweekday:", ""))
    await query.edit_message_text("Выберите тип шаблона:", reply_markup=task_type_keyboard())
    return REG_ADD_TYPE


async def regular_add_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["regular_task_type"] = query.data.replace("tasktype:", "")
    await query.edit_message_text("Введите описание шаблона:")
    return REG_ADD_DESCRIPTION


async def regular_add_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("Описание не должно быть пустым. Введите описание:")
        return REG_ADD_DESCRIPTION
    context.user_data["regular_description"] = description
    if context.user_data.get("regular_task_type") == TASK_TYPE_WAREHOUSE:
        await update.message.reply_text("Выберите режим исполнителей:", reply_markup=assignee_mode_keyboard())
        return REG_ADD_ASSIGNEE_MODE
    context.user_data["regular_assignee_mode"] = ASSIGNEE_MODE_NONE
    context.user_data["selected_employee_ids"] = []
    await update.message.reply_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
    return REG_ADD_DEADLINE


async def regular_assignee_mode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data.replace("regassigneemode:", "")
    if mode == "none":
        mode = ASSIGNEE_MODE_NONE
    context.user_data["regular_assignee_mode"] = mode
    context.user_data["selected_employee_ids"] = []
    if mode == ASSIGNEE_MODE_SPECIFIC:
        await query.edit_message_text("Выберите сотрудников:", reply_markup=regular_assignees_keyboard([]))
        return REG_EDIT_ASSIGNEES if "edit_template_id" in context.user_data else REG_ADD_ASSIGNEES
    if "edit_template_id" in context.user_data:
        set_task_template_assignees(context.user_data["edit_template_id"], mode, [])
        context.user_data.clear()
        await query.edit_message_text("Исполнители шаблона обновлены ✅", reply_markup=regular_tasks_menu_keyboard())
        return ConversationHandler.END
    await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
    return REG_ADD_DEADLINE


async def regular_assignee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.replace("regassignee:", "")
    selected = set(context.user_data.get("selected_employee_ids", []))

    if value == "done":
        employees = [employee for employee in get_employees(include_inactive=False) if employee["employee_id"] in selected]
        if "edit_template_id" in context.user_data:
            set_task_template_assignees(context.user_data["edit_template_id"], ASSIGNEE_MODE_SPECIFIC, employees)
            context.user_data.clear()
            await query.edit_message_text("Исполнители шаблона обновлены ✅", reply_markup=regular_tasks_menu_keyboard())
            return ConversationHandler.END
        await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return REG_ADD_DEADLINE

    selected.remove(value) if value in selected else selected.add(value)
    context.user_data["selected_employee_ids"] = list(selected)
    await query.edit_message_text("Выберите сотрудников:", reply_markup=regular_assignees_keyboard(selected))
    return REG_EDIT_ASSIGNEES if "edit_template_id" in context.user_data else REG_ADD_ASSIGNEES


async def finish_regular_task_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected_ids = set(context.user_data.get("selected_employee_ids", []))
    employees = [employee for employee in get_employees(include_inactive=False) if employee["employee_id"] in selected_ids]
    template_id = create_task_template(
        weekday=context.user_data["regular_weekday"],
        task_type=context.user_data["regular_task_type"],
        description=context.user_data["regular_description"],
        assignee_mode=context.user_data.get("regular_assignee_mode", ASSIGNEE_MODE_NONE),
        assignee_employees=employees,
        deadline=context.user_data.get("regular_deadline", ""),
    )
    context.user_data.clear()
    await update.callback_query.edit_message_text(f"Шаблон создан ✅\n{template_id}", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "regular"
    await query.edit_message_text("Выберите день недели:", reply_markup=weekday_keyboard("regeditday"))
    return REG_EDIT_DAY


async def regular_edit_day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    weekday = int(query.data.replace("regeditday:", ""))
    context.user_data["regular_weekday_filter"] = weekday
    templates = regular_templates_for_weekday(weekday)
    if not templates:
        await query.edit_message_text(
            f"На {WEEKDAY_NAMES[weekday].lower()} регулярных задач пока нет.",
            reply_markup=regular_tasks_menu_keyboard(),
        )
        return ConversationHandler.END
    await query.edit_message_text(
        f"{WEEKDAY_NAMES[weekday]}. Выберите шаблон:",
        reply_markup=regular_task_select_keyboard(templates, "regedit"),
    )
    return REG_EDIT_SELECT


async def regular_edit_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    template_id = query.data.replace("regedit:", "")
    template = get_task_template_by_id(template_id)
    if not template:
        await query.edit_message_text("Регулярная задача не найдена.", reply_markup=regular_tasks_menu_keyboard())
        return ConversationHandler.END
    context.user_data["edit_template_id"] = template_id
    await query.edit_message_text("Что изменить?", reply_markup=regular_edit_field_keyboard(template))
    return REG_EDIT_FIELD


async def regular_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("regeditfield:", "")
    if field == "description":
        await query.edit_message_text("Введите новое описание шаблона:")
        return REG_EDIT_DESCRIPTION
    if field == "weekday":
        await query.edit_message_text("Выберите день недели:", reply_markup=weekday_keyboard("regeditweekday"))
        return REG_EDIT_WEEKDAY
    if field == "type":
        await query.edit_message_text("Выберите тип задачи:", reply_markup=task_type_keyboard())
        return REG_EDIT_TYPE
    if field == "assignees":
        await query.edit_message_text("Выберите режим исполнителей:", reply_markup=assignee_mode_keyboard())
        return REG_EDIT_ASSIGNEE_MODE
    if field == "deadline":
        await query.edit_message_text("Выберите дедлайн:", reply_markup=deadline_keyboard())
        return REG_EDIT_DEADLINE
    return ConversationHandler.END


async def regular_edit_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("Описание не должно быть пустым. Введите новое описание:")
        return REG_EDIT_DESCRIPTION
    update_task_template_fields(context.user_data["edit_template_id"], **{"Описание": description})
    context.user_data.clear()
    await update.message.reply_text("Описание шаблона обновлено ✅", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_edit_weekday_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    update_task_template_fields(context.user_data["edit_template_id"], **{"weekday": int(query.data.replace("regeditweekday:", ""))})
    context.user_data.clear()
    await query.edit_message_text("День недели обновлен ✅", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_edit_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_type = query.data.replace("tasktype:", "")
    fields = {"Тип задачи": task_type}
    if task_type == TASK_TYPE_GENERAL:
        fields.update({"Тип исполнителей": ASSIGNEE_MODE_NONE, "Исполнители ID": "", "Исполнители": ""})
    update_task_template_fields(context.user_data["edit_template_id"], **fields)
    context.user_data.clear()
    await query.edit_message_text("Тип шаблона обновлен ✅", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def regular_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data["task_section"] = "regular"
    await query.edit_message_text("Выберите день недели:", reply_markup=weekday_keyboard("regdelday"))
    return REG_DELETE_DAY


async def regular_delete_day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    weekday = int(query.data.replace("regdelday:", ""))
    context.user_data["regular_weekday_filter"] = weekday
    templates = regular_templates_for_weekday(weekday)
    if not templates:
        await query.edit_message_text(
            f"На {WEEKDAY_NAMES[weekday].lower()} регулярных задач пока нет.",
            reply_markup=regular_tasks_menu_keyboard(),
        )
        return ConversationHandler.END
    await query.edit_message_text(
        f"{WEEKDAY_NAMES[weekday]}. Выберите шаблон для удаления:",
        reply_markup=regular_task_select_keyboard(templates, "regdel"),
    )
    return REG_DELETE_SELECT


async def regular_delete_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    template_id = query.data.replace("regdel:", "")
    template = get_task_template_by_id(template_id)
    if not template:
        await query.edit_message_text("Регулярная задача не найдена.", reply_markup=regular_tasks_menu_keyboard())
        return ConversationHandler.END
    await query.edit_message_text(
        f"Удалить шаблон?\n\n{template.get('Описание', '')}",
        reply_markup=confirm_keyboard("regdelconfirm", template_id),
    )
    return REG_DELETE_CONFIRM


async def regular_delete_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, template_id = query.data.split(":", 2)
    delete_task_template(template_id)
    context.user_data.clear()
    await query.edit_message_text("Регулярная задача удалена ✅", reply_markup=regular_tasks_menu_keyboard())
    return ConversationHandler.END


async def send_or_edit_task_message(context, day, export_type, chat_id, thread_id, text, reply_markup=None):
    existing = get_task_export(day, export_type)
    if existing and existing.get("chat_id") and existing.get("message_id"):
        try:
            await context.bot.edit_message_text(
                chat_id=int(existing["chat_id"]),
                message_id=int(existing["message_id"]),
                text=text,
                reply_markup=reply_markup,
            )
            return "обновлено"
        except BadRequest as error:
            if "Message is not modified" in str(error):
                return "без изменений"
            logging.exception("Не удалось отредактировать сообщение задач")
        except Exception:
            logging.exception("Не удалось отредактировать сообщение задач")

    kwargs = {"chat_id": int(chat_id), "text": text}
    if thread_id:
        kwargs["message_thread_id"] = int(thread_id)
    if reply_markup:
        kwargs["reply_markup"] = reply_markup
    message = await context.bot.send_message(**kwargs)
    upsert_task_export(day, export_type, chat_id, thread_id or "", message.message_id)
    return "отправлено"


async def export_warehouse_tasks_for_date(context, day):
    if not GROUP_CHAT_ID or not SCHEDULE_REMINDER_TOPIC_ID:
        return "не настроены GROUP_CHAT_ID или SCHEDULE_REMINDER_TOPIC_ID"
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
    return await send_or_edit_task_message(
        context,
        day,
        "warehouse",
        GROUP_CHAT_ID,
        SCHEDULE_REMINDER_TOPIC_ID,
        format_warehouse_tasks_message(day, tasks),
        warehouse_tasks_inline_keyboard(tasks),
    )


async def export_general_tasks_for_date(context, day):
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
    managers = get_warehouse_managers()
    statuses = []
    for manager in managers:
        chat_id = str(manager.get("telegram_user_id", "")).strip()
        if chat_id:
            statuses.append(
                await send_or_edit_task_message(
                    context,
                    day,
                    f"general:{chat_id}",
                    chat_id,
                    "",
                    format_general_tasks_message(day, tasks),
                    None,
                )
            )
    return "; ".join(statuses) if statuses else "руководитель склада не найден"


async def export_tasks_for_date(context, day):
    warehouse_status = await export_warehouse_tasks_for_date(context, day)
    general_status = await export_general_tasks_for_date(context, day)
    return f"Задачи на {date_to_str(day)} выгружены ✅\n\nСкладские в тему: {warehouse_status}\nНескладские в личку руководителю: {general_status}"


async def refresh_existing_exports_for_date(context, day):
    tasks = get_tasks_by_date(day)
    if get_task_export(day, "warehouse") and GROUP_CHAT_ID and SCHEDULE_REMINDER_TOPIC_ID:
        await send_or_edit_task_message(
            context,
            day,
            "warehouse",
            GROUP_CHAT_ID,
            SCHEDULE_REMINDER_TOPIC_ID,
            format_warehouse_tasks_message(day, tasks),
            warehouse_tasks_inline_keyboard(tasks),
        )
    for manager in get_warehouse_managers():
        chat_id = str(manager.get("telegram_user_id", "")).strip()
        export_type = f"general:{chat_id}"
        if chat_id and get_task_export(day, export_type):
            await send_or_edit_task_message(context, day, export_type, chat_id, "", format_general_tasks_message(day, tasks), None)


async def task_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = query.data.replace("taskdone:", "")
    _, task = get_task_by_id(task_id)
    if not task:
        await query.answer("Задача не найдена", show_alert=True)
        return
    employee = current_employee(update)
    if not can_user_complete_task(update.effective_user, task, employee):
        await query.answer("У вас нет прав отметить эту задачу", show_alert=True)
        return
    done = str(task.get("Статус", "")).strip() != TASK_STATUS_DONE
    mark_task_done(task_id, employee, done=done)
    _, updated = get_task_by_id(task_id)
    await refresh_existing_exports_for_date(context, parse_date(updated["Дата"]))
    await query.answer("Готово")


async def daily_staff_job(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID or not SCHEDULE_REMINDER_TOPIC_ID:
        return
    day = today_msk()
    week_start = day - timedelta(days=day.weekday())
    employees, dates, schedule, duty_by_date = get_schedule_matrix(week_start)
    await context.bot.send_message(
        chat_id=int(GROUP_CHAT_ID),
        message_thread_id=int(SCHEDULE_REMINDER_TOPIC_ID),
        text=format_daily_staff_message(day, employees, schedule, duty_by_date),
    )


async def daily_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    await export_tasks_for_date(context, today_msk())


async def weekly_template_job(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Создано задач из регулярных задач: %s", materialize_next_week_templates(today_msk()))


def setup_tasks_jobs(app):
    if not app.job_queue:
        logging.warning("JobQueue не включен. Установите python-telegram-bot[job-queue].")
        return
    app.job_queue.run_daily(daily_staff_job, time=time(hour=10, minute=30, tzinfo=MSK_TZ), name="daily_staff_message")
    app.job_queue.run_daily(daily_tasks_job, time=time(hour=10, minute=35, tzinfo=MSK_TZ), name="daily_tasks_export")
    app.job_queue.run_daily(
        weekly_template_job,
        time=time(hour=23, minute=0, tzinfo=MSK_TZ),
        days=(6,),
        name="weekly_task_template_materialization",
    )


def get_tasks_handlers():
    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(irregular_add_start, pattern=r"^task:add$"),
            CallbackQueryHandler(irregular_edit_start, pattern=r"^task:edit$"),
            CallbackQueryHandler(irregular_delete_start, pattern=r"^task:delete$"),
            CallbackQueryHandler(irregular_add_start, pattern=r"^irreg:add$"),
            CallbackQueryHandler(irregular_view_start, pattern=r"^irreg:view$"),
            CallbackQueryHandler(irregular_edit_start, pattern=r"^irreg:edit$"),
            CallbackQueryHandler(irregular_delete_start, pattern=r"^irreg:delete$"),
            CallbackQueryHandler(task_view_start, pattern=r"^task:view$"),
            CallbackQueryHandler(task_export_start, pattern=r"^task:export$"),
            CallbackQueryHandler(regular_add_start, pattern=r"^reg:add$"),
            CallbackQueryHandler(regular_edit_start, pattern=r"^reg:edit$"),
            CallbackQueryHandler(regular_delete_start, pattern=r"^reg:delete$"),
        ],
        states={
            TASK_ADD_TYPE: [CallbackQueryHandler(task_add_type_selected, pattern=r"^tasktype:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DATE: [CallbackQueryHandler(task_add_date_selected, pattern=r"^taskdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_add_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_ASSIGNEES: [CallbackQueryHandler(task_assignee_selected, pattern=r"^taskassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_VIEW_DATE: [CallbackQueryHandler(task_view_date_selected, pattern=r"^taskviewdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EXPORT_DATE: [CallbackQueryHandler(task_export_date_selected, pattern=r"^taskexportdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DATE: [CallbackQueryHandler(task_edit_date_selected, pattern=r"^taskeditdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_SELECT: [CallbackQueryHandler(task_edit_selected, pattern=r"^taskedit:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_FIELD: [CallbackQueryHandler(task_edit_field_selected, pattern=r"^taskeditfield:"), CallbackQueryHandler(task_status_selected, pattern=r"^taskstatus:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_edit_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_ASSIGNEES: [CallbackQueryHandler(task_assignee_selected, pattern=r"^taskassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_DELETE_DATE: [CallbackQueryHandler(task_delete_date_selected, pattern=r"^taskdeldate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_DELETE_SELECT: [CallbackQueryHandler(task_delete_selected, pattern=r"^taskdel:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_DELETE_CONFIRM: [CallbackQueryHandler(task_delete_confirmed, pattern=r"^taskdelconfirm:yes:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_WEEKDAY: [CallbackQueryHandler(regular_add_weekday_selected, pattern=r"^regweekday:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_TYPE: [CallbackQueryHandler(regular_add_type_selected, pattern=r"^tasktype:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, regular_add_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_ASSIGNEE_MODE: [CallbackQueryHandler(regular_assignee_mode_selected, pattern=r"^regassigneemode:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_ASSIGNEES: [CallbackQueryHandler(regular_assignee_selected, pattern=r"^regassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_ADD_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_DAY: [CallbackQueryHandler(regular_edit_day_selected, pattern=r"^regeditday:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_SELECT: [CallbackQueryHandler(regular_edit_selected, pattern=r"^regedit:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_FIELD: [CallbackQueryHandler(regular_edit_field_selected, pattern=r"^regeditfield:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, regular_edit_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_WEEKDAY: [CallbackQueryHandler(regular_edit_weekday_selected, pattern=r"^regeditweekday:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_TYPE: [CallbackQueryHandler(regular_edit_type_selected, pattern=r"^tasktype:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_ASSIGNEE_MODE: [CallbackQueryHandler(regular_assignee_mode_selected, pattern=r"^regassigneemode:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_ASSIGNEES: [CallbackQueryHandler(regular_assignee_selected, pattern=r"^regassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_EDIT_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_DELETE_DAY: [CallbackQueryHandler(regular_delete_day_selected, pattern=r"^regdelday:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_DELETE_SELECT: [CallbackQueryHandler(regular_delete_selected, pattern=r"^regdel:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            REG_DELETE_CONFIRM: [CallbackQueryHandler(regular_delete_confirmed, pattern=r"^regdelconfirm:yes:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
        },
        fallbacks=[CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
        per_message=False,
        allow_reentry=True,
    )
    return [
        CallbackQueryHandler(tasks_menu, pattern=r"^section:tasks$"),
        CallbackQueryHandler(regular_tasks_menu, pattern=r"^task:regular$"),
        CallbackQueryHandler(irregular_tasks_menu, pattern=r"^task:irregular$"),
        CallbackQueryHandler(regular_view, pattern=r"^reg:view$"),
        CallbackQueryHandler(task_done_callback, pattern=r"^taskdone:"),
        conversation,
    ]
