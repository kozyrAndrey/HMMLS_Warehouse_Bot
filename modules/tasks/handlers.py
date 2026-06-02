import logging
from datetime import timedelta, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from config import GROUP_CHAT_ID, SCHEDULE_REMINDER_TOPIC_ID
from core.keyboards import build_main_menu_keyboard
from modules.payroll.google_sheets import find_employee_for_telegram_user
from modules.schedule.config import MSK_TZ, date_to_str, day_label, parse_date, today_msk
from modules.schedule.google_sheets import get_schedule_matrix
from modules.tasks.config import (
    NO_DEADLINE_TEXT, TASK_DEADLINES, TASK_STATUS_ACTIVE, TASK_STATUS_CANCELLED, TASK_STATUS_DONE,
    TASK_TYPE_GENERAL, TASK_TYPE_LABELS, TASK_TYPE_WAREHOUSE, is_tasks_manager,
)
from modules.tasks.formatting import (
    format_all_tasks_for_private_view, format_daily_staff_message, format_general_tasks_message,
    format_warehouse_tasks_message, filter_active_export_tasks,
)
from modules.tasks.google_sheets import (
    add_task_to_template, can_user_complete_task, create_task, get_task_by_id, get_task_export,
    get_tasks_by_date, get_warehouse_managers, get_working_employees_for_date, init_tasks_sheet,
    mark_task_done, materialize_next_week_templates, materialize_templates_for_date, set_task_assignees,
    update_task_fields, upsert_task_export,
)

(
    TASK_ADD_TYPE, TASK_ADD_DATE, TASK_ADD_DESCRIPTION, TASK_ADD_ASSIGNEES, TASK_ADD_DEADLINE, TASK_ADD_TEMPLATE,
    TASK_VIEW_DATE, TASK_EXPORT_DATE, TASK_EDIT_DATE, TASK_EDIT_SELECT, TASK_EDIT_FIELD, TASK_EDIT_DESCRIPTION,
    TASK_EDIT_ASSIGNEES, TASK_EDIT_DEADLINE,
) = range(1200, 1214)


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
        [InlineKeyboardButton("➕ Добавить задачу", callback_data="task:add")],
        [InlineKeyboardButton("👀 Просмотр задач на день", callback_data="task:view")],
        [InlineKeyboardButton("✏️ Изменить задачу", callback_data="task:edit")],
        [InlineKeyboardButton("📤 Выгрузить задачи", callback_data="task:export")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")],
    ])


def task_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Складская", callback_data="tasktype:warehouse")],
        [InlineKeyboardButton("🧩 Нескладская", callback_data="tasktype:general")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


def date_keyboard(prefix, days=14):
    rows = []
    current = today_msk()
    for offset in range(days):
        day = current + timedelta(days=offset)
        rows.append([InlineKeyboardButton(day_label(day), callback_data=f"{prefix}:{date_to_str(day)}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def assignees_keyboard(working, selected_ids):
    selected_ids = set(selected_ids or [])
    rows = []
    for employee in working:
        mark = "✅" if employee["employee_id"] in selected_ids else "⬜️"
        username = str(employee.get("telegram_username", "")).strip().lstrip("@")
        label = f"{mark} {employee['full_name']}" + (f" @{username}" if username else "")
        rows.append([InlineKeyboardButton(label, callback_data=f"taskassignee:{employee['employee_id']}")])
    rows.append([InlineKeyboardButton("✅ Завершить выбор", callback_data="taskassignee:done")])
    rows.append([InlineKeyboardButton("👤 Без исполнителей", callback_data="taskassignee:none")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def deadline_keyboard():
    rows = []
    for index in range(0, len(TASK_DEADLINES), 3):
        rows.append([InlineKeyboardButton(value, callback_data=f"taskdeadline:{value}") for value in TASK_DEADLINES[index:index + 3]])
    rows.append([InlineKeyboardButton(NO_DEADLINE_TEXT, callback_data="taskdeadline:none")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")])
    return InlineKeyboardMarkup(rows)


def template_choice_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Только одноразовая", callback_data="tasktemplate:no")],
        [InlineKeyboardButton("Одноразовая + добавить в шаблон", callback_data="tasktemplate:yes")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


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


def edit_field_keyboard(task):
    task_type = str(task.get("Тип задачи", "")).strip()
    rows = [[InlineKeyboardButton("📝 Описание", callback_data="taskeditfield:description")]]
    if task_type == TASK_TYPE_WAREHOUSE:
        rows.append([InlineKeyboardButton("👥 Исполнители", callback_data="taskeditfield:assignees")])
        rows.append([InlineKeyboardButton("⏰ Дедлайн", callback_data="taskeditfield:deadline")])
    rows.extend([
        [InlineKeyboardButton("✅ Статус", callback_data="taskeditfield:status")],
        [InlineKeyboardButton("♻️ Добавить в шаблон", callback_data="taskeditfield:template")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


def status_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬜ Невыполнено", callback_data="taskstatus:active")],
        [InlineKeyboardButton("✅ Выполнено", callback_data="taskstatus:done")],
        [InlineKeyboardButton("🚫 Отменено", callback_data="taskstatus:cancelled")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
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


async def tasks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Действие отменено.", reply_markup=tasks_menu_keyboard())
    else:
        await update.message.reply_text("Действие отменено.", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not ensure_tasks_manager(update):
        await query.edit_message_text("⛔️ Нет доступа.", reply_markup=build_main_menu_keyboard())
        return ConversationHandler.END
    context.user_data.clear()
    await query.edit_message_text("Выберите тип задачи:", reply_markup=task_type_keyboard())
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
        await update.message.reply_text("Добавить эту задачу в еженедельный шаблон?", reply_markup=template_choice_keyboard())
        return TASK_ADD_TEMPLATE

    day = parse_date(context.user_data["task_date"])
    working = get_working_employees_for_date(day)
    context.user_data["selected_employee_ids"] = []
    if not working:
        await update.message.reply_text(
            "На эту дату пока нет сотрудников в расписании. Задачу можно создать без исполнителей.\n\nВыберите дедлайн:",
            reply_markup=deadline_keyboard(),
        )
        return TASK_ADD_DEADLINE

    await update.message.reply_text(
        "Выберите исполнителей из тех, кто работает в выбранный день:",
        reply_markup=assignees_keyboard(working, []),
    )
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

    context.user_data["task_deadline"] = deadline
    await query.edit_message_text("Добавить эту задачу в еженедельный шаблон?", reply_markup=template_choice_keyboard())
    return TASK_ADD_TEMPLATE


async def task_template_choice_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(context.user_data["task_date"])
    task_type = context.user_data["task_type"]
    selected_ids = set(context.user_data.get("selected_employee_ids", []))
    assignees = []
    if task_type == TASK_TYPE_WAREHOUSE and selected_ids:
        assignees = [employee for employee in get_working_employees_for_date(day) if employee["employee_id"] in selected_ids]
    employee = current_employee(update)
    task_id = create_task(
        day=day,
        task_type=task_type,
        description=context.user_data["task_description"],
        assignee_employees=assignees,
        deadline=context.user_data.get("task_deadline", ""),
        created_by=employee["full_name"] if employee else "manager",
    )
    template_status = ""
    if query.data.endswith(":yes"):
        _, task_record = get_task_by_id(task_id)
        template_status = f"\nДобавлено в шаблон ✅ ({add_task_to_template(task_record)})"
    await refresh_existing_exports_for_date(context, day)
    context.user_data.clear()
    await query.edit_message_text(f"Задача создана ✅{template_status}", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_view_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите дату для просмотра задач:", reply_markup=date_keyboard("taskviewdate"))
    return TASK_VIEW_DATE


async def task_view_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskviewdate:", ""))
    materialize_templates_for_date(day)
    await query.edit_message_text(format_all_tasks_for_private_view(day, get_tasks_by_date(day)), reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_export_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите дату для выгрузки задач:", reply_markup=date_keyboard("taskexportdate"))
    return TASK_EXPORT_DATE


async def task_export_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskexportdate:", ""))
    await query.edit_message_text(await export_tasks_for_date(context, day), reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Выберите дату:", reply_markup=date_keyboard("taskeditdate"))
    return TASK_EDIT_DATE


async def task_edit_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = parse_date(query.data.replace("taskeditdate:", ""))
    context.user_data["edit_task_date"] = date_to_str(day)
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
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
    task_id = context.user_data["edit_task_id"]
    _, task = get_task_by_id(task_id)
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
    if field == "template":
        await query.edit_message_text(f"Задача добавлена в шаблон ✅\n{add_task_to_template(task)}", reply_markup=tasks_menu_keyboard())
        return ConversationHandler.END
    return ConversationHandler.END


async def task_edit_description_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_id = context.user_data["edit_task_id"]
    update_task_fields(task_id, **{"Описание": update.message.text.strip()})
    _, task = get_task_by_id(task_id)
    await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
    context.user_data.clear()
    await update.message.reply_text("Описание обновлено ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


async def task_status_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = {"active": TASK_STATUS_ACTIVE, "done": TASK_STATUS_DONE, "cancelled": TASK_STATUS_CANCELLED}.get(query.data.replace("taskstatus:", ""), TASK_STATUS_ACTIVE)
    update_task_fields(context.user_data["edit_task_id"], **{"Статус": status})
    _, task = get_task_by_id(context.user_data["edit_task_id"])
    await refresh_existing_exports_for_date(context, parse_date(task["Дата"]))
    context.user_data.clear()
    await query.edit_message_text("Статус обновлен ✅", reply_markup=tasks_menu_keyboard())
    return ConversationHandler.END


def status_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬜ Невыполнено", callback_data="taskstatus:active")],
        [InlineKeyboardButton("✅ Выполнено", callback_data="taskstatus:done")],
        [InlineKeyboardButton("🚫 Отменено", callback_data="taskstatus:cancelled")],
        [InlineKeyboardButton("❌ Отмена", callback_data="task:cancel")],
    ])


async def send_or_edit_task_message(context, day, export_type, chat_id, thread_id, text, reply_markup=None):
    existing = get_task_export(day, export_type)
    if existing and existing.get("chat_id") and existing.get("message_id"):
        try:
            await context.bot.edit_message_text(chat_id=int(existing["chat_id"]), message_id=int(existing["message_id"]), text=text, reply_markup=reply_markup)
            return "обновлено"
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
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
    return await send_or_edit_task_message(
        context, day, "warehouse", GROUP_CHAT_ID, SCHEDULE_REMINDER_TOPIC_ID,
        format_warehouse_tasks_message(day, tasks), warehouse_tasks_inline_keyboard(tasks)
    )


async def export_general_tasks_for_date(context, day):
    materialize_templates_for_date(day)
    tasks = get_tasks_by_date(day)
    managers = get_warehouse_managers()
    statuses = []
    for manager in managers:
        chat_id = str(manager.get("telegram_user_id", "")).strip()
        if chat_id:
            statuses.append(await send_or_edit_task_message(
                context, day, f"general:{chat_id}", chat_id, "",
                format_general_tasks_message(day, tasks), None
            ))
    return "; ".join(statuses) if statuses else "руководитель склада не найден"


async def export_tasks_for_date(context, day):
    warehouse_status = await export_warehouse_tasks_for_date(context, day)
    general_status = await export_general_tasks_for_date(context, day)
    return f"Задачи на {date_to_str(day)} выгружены ✅\n\nСкладские в тему: {warehouse_status}\nНескладские в личку руководителю: {general_status}"


async def refresh_existing_exports_for_date(context, day):
    tasks = get_tasks_by_date(day)
    if get_task_export(day, "warehouse"):
        await send_or_edit_task_message(
            context, day, "warehouse", GROUP_CHAT_ID, SCHEDULE_REMINDER_TOPIC_ID,
            format_warehouse_tasks_message(day, tasks), warehouse_tasks_inline_keyboard(tasks)
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
    await context.bot.send_message(chat_id=int(GROUP_CHAT_ID), message_thread_id=int(SCHEDULE_REMINDER_TOPIC_ID), text=format_daily_staff_message(day, employees, schedule, duty_by_date))


async def daily_tasks_job(context: ContextTypes.DEFAULT_TYPE):
    await export_tasks_for_date(context, today_msk())


async def weekly_template_job(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Создано задач из шаблона: %s", materialize_next_week_templates(today_msk()))


def setup_tasks_jobs(app):
    if not app.job_queue:
        logging.warning("JobQueue не включен. Установите python-telegram-bot[job-queue].")
        return
    app.job_queue.run_daily(daily_staff_job, time=time(hour=9, minute=0, tzinfo=MSK_TZ), name="daily_staff_message")
    app.job_queue.run_daily(daily_tasks_job, time=time(hour=9, minute=5, tzinfo=MSK_TZ), name="daily_tasks_export")
    app.job_queue.run_daily(weekly_template_job, time=time(hour=23, minute=0, tzinfo=MSK_TZ), days=(6,), name="weekly_task_template_materialization")


def get_tasks_handlers():
    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(task_add_start, pattern=r"^task:add$"),
            CallbackQueryHandler(task_view_start, pattern=r"^task:view$"),
            CallbackQueryHandler(task_export_start, pattern=r"^task:export$"),
            CallbackQueryHandler(task_edit_start, pattern=r"^task:edit$"),
        ],
        states={
            TASK_ADD_TYPE: [CallbackQueryHandler(task_add_type_selected, pattern=r"^tasktype:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DATE: [CallbackQueryHandler(task_add_date_selected, pattern=r"^taskdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_add_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_ASSIGNEES: [CallbackQueryHandler(task_assignee_selected, pattern=r"^taskassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_ADD_TEMPLATE: [CallbackQueryHandler(task_template_choice_selected, pattern=r"^tasktemplate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_VIEW_DATE: [CallbackQueryHandler(task_view_date_selected, pattern=r"^taskviewdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EXPORT_DATE: [CallbackQueryHandler(task_export_date_selected, pattern=r"^taskexportdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DATE: [CallbackQueryHandler(task_edit_date_selected, pattern=r"^taskeditdate:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_SELECT: [CallbackQueryHandler(task_edit_selected, pattern=r"^taskedit:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_FIELD: [CallbackQueryHandler(task_edit_field_selected, pattern=r"^taskeditfield:"), CallbackQueryHandler(task_status_selected, pattern=r"^taskstatus:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_edit_description_received), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_ASSIGNEES: [CallbackQueryHandler(task_assignee_selected, pattern=r"^taskassignee:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
            TASK_EDIT_DEADLINE: [CallbackQueryHandler(task_deadline_selected, pattern=r"^taskdeadline:"), CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
        },
        fallbacks=[CallbackQueryHandler(tasks_cancel, pattern=r"^task:cancel$")],
        per_message=False,
        allow_reentry=True,
    )
    return [
        CallbackQueryHandler(tasks_menu, pattern=r"^section:tasks$"),
        CallbackQueryHandler(task_done_callback, pattern=r"^taskdone:"),
        conversation,
    ]
