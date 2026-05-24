import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import GROUP_CHAT_ID, PAYROLL_REPORT_TOPIC_ID
from keyboards import build_main_menu_keyboard
from payroll_calculations import build_full_payroll_text, build_personal_salary_text
from payroll_google_sheets import (
    append_daily_report,
    append_expense,
    append_penalty,
    cleanup_old_operational_data,
    create_active_period,
    find_employee_for_telegram_user,
    find_report_row,
    get_active_period,
    get_employee_by_id,
    get_employees,
    get_kpi_items,
    get_periods,
    is_manager,
    kpi_from_json,
    kpi_to_json,
    calculate_kpi_sum,
    money,
    report_data_to_model,
    safe_float,
    update_active_period,
    update_daily_report,
    update_report_message_ids,
    validate_date,
    now_str,
)
from pdf_reports import create_payroll_pdf


(
    CREATE_EMPLOYEE,
    CREATE_DATE,
    CREATE_INTERVAL,
    CREATE_HOURS,
    CREATE_TASKS,
    CREATE_KPI_SELECT,
    CREATE_KPI_QTY,
    EDIT_EMPLOYEE,
    EDIT_DATE,
    EDIT_FIELD,
    EDIT_VALUE,
    EDIT_KPI_SELECT,
    EDIT_KPI_QTY,
    SALARY_EMPLOYEE,
    EXPENSE_EMPLOYEE,
    EXPENSE_DATE,
    EXPENSE_COMMENT,
    EXPENSE_AMOUNT,
    PENALTY_EMPLOYEE,
    PENALTY_DATE,
    PENALTY_COMMENT,
    PENALTY_AMOUNT,
    PERIOD_NAME,
    PERIOD_START,
    PERIOD_END,
    PERIOD_EDIT_FIELD,
    PERIOD_EDIT_VALUE,
    CLEANUP_CONFIRM,
) = range(300, 328)


# ============================================================
# ОБЩИЕ КЛАВИАТУРЫ
# ============================================================


def payroll_main_keyboard(manager=False):
    rows = [
        [InlineKeyboardButton("📝 Создать ежедневный отчет", callback_data="pay:create_report")],
        [InlineKeyboardButton("✏️ Изменить отчет", callback_data="pay:edit_report")],
        [InlineKeyboardButton("💰 Проверить свою ЗП", callback_data="pay:check_salary")],
        [InlineKeyboardButton("💸 Добавить расход", callback_data="pay:add_expense")],
    ]

    if manager:
        rows.extend(
            [
                [InlineKeyboardButton("⚠️ Штраф", callback_data="pay:add_penalty")],
                [InlineKeyboardButton("📊 Рассчитать ЗП за период", callback_data="pay:calculate_period")],
                [InlineKeyboardButton("⚙️ Расчетные периоды", callback_data="pay:periods")],
                [InlineKeyboardButton("🧹 Очистить данные старше 1 года", callback_data="pay:cleanup")],
            ]
        )

    rows.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="menu:start")])
    return InlineKeyboardMarkup(rows)


def payroll_back_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")]]
    )


def date_keyboard(prefix):
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    today_text = today.strftime("%d.%m.%Y")
    yesterday_text = yesterday.strftime("%d.%m.%Y")
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(today_text, callback_data=f"{prefix}:{today_text}")],
            [InlineKeyboardButton(yesterday_text, callback_data=f"{prefix}:{yesterday_text}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")],
        ]
    )


def employees_keyboard(prefix, include_cancel=True):
    rows = []
    for employee in get_employees():
        rows.append(
            [InlineKeyboardButton(employee["full_name"], callback_data=f"{prefix}:{employee['employee_id']}")]
        )
    if include_cancel:
        rows.append([InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")])
    return InlineKeyboardMarkup(rows)


def kpi_keyboard(prefix):
    rows = []
    for item in get_kpi_items():
        rows.append(
            [InlineKeyboardButton(item["name"], callback_data=f"{prefix}:{item['kpi_id']}")]
        )
    rows.append([InlineKeyboardButton("✅ Завершить KPI", callback_data=f"{prefix}:done")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")])
    return InlineKeyboardMarkup(rows)


def edit_field_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Рабочий промежуток", callback_data="editfield:interval")],
            [InlineKeyboardButton("Отработано часов", callback_data="editfield:hours")],
            [InlineKeyboardButton("Задачи", callback_data="editfield:tasks")],
            [InlineKeyboardButton("KPI", callback_data="editfield:kpi")],
            [InlineKeyboardButton("✅ Завершить изменение", callback_data="editfield:finish")],
            [InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")],
        ]
    )


def periods_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Создать текущий период", callback_data="period:create")],
            [InlineKeyboardButton("✏️ Изменить текущий период", callback_data="period:edit")],
            [InlineKeyboardButton("📋 Посмотреть периоды", callback_data="period:list")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="section:payroll")],
        ]
    )


def period_edit_field_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Название", callback_data="periodfield:name")],
            [InlineKeyboardButton("Дата начала", callback_data="periodfield:start")],
            [InlineKeyboardButton("Дата конца", callback_data="periodfield:end")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="pay:periods")],
        ]
    )


def cleanup_confirm_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Да, очистить", callback_data="cleanup:yes")],
            [InlineKeyboardButton("Отмена", callback_data="pay:cancel")],
        ]
    )


# ============================================================
# ОБЩИЕ ХЕЛПЕРЫ
# ============================================================


def parse_hours(text):
    value = safe_float(text)
    if value <= 0:
        return None
    if abs(value * 2 - round(value * 2)) > 0.0001:
        return None
    return value


def parse_positive_amount(text):
    value = safe_float(text)
    if value <= 0:
        return None
    return value


def current_employee_or_none(update):
    return find_employee_for_telegram_user(update.effective_user)


async def deny_unknown_user(update: Update):
    user = update.effective_user
    text = (
        "Я не нашел вас в справочнике сотрудников.\n\n"
        f"Ваш Telegram user_id: {user.id}\n"
        f"Ваш username: @{user.username if user.username else '-'}\n\n"
        "Передайте эти данные руководителю, чтобы он добавил вас в лист «Сотрудники»."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def show_payroll_menu_message(target, employee):
    manager = is_manager(employee)
    text = "💰 Расчет ЗП"
    if employee:
        text += f"\n\nСотрудник: {employee['full_name']}"
        text += f"\nРоль: {employee['role']}"
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text(text, reply_markup=payroll_main_keyboard(manager=manager))
    else:
        await target.reply_text(text, reply_markup=payroll_main_keyboard(manager=manager))


async def payroll_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    if not employee:
        await deny_unknown_user(update)
        return ConversationHandler.END

    await show_payroll_menu_message(query, employee)
    return ConversationHandler.END


async def payroll_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    employee = current_employee_or_none(update)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if employee:
            await show_payroll_menu_message(query, employee)
        else:
            await query.edit_message_text("Действие отменено.", reply_markup=build_main_menu_keyboard())
    else:
        if employee:
            await show_payroll_menu_message(update.message, employee)
        else:
            await update.message.reply_text("Действие отменено.", reply_markup=build_main_menu_keyboard())

    return ConversationHandler.END


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    employee = current_employee_or_none(update)

    text = (
        f"Telegram user_id: {user.id}\n"
        f"Username: @{user.username if user.username else '-'}"
    )

    if employee:
        text += (
            f"\n\nСотрудник: {employee['full_name']}\n"
            f"employee_id: {employee['employee_id']}\n"
            f"role: {employee['role']}"
        )
    else:
        text += "\n\nВ листе «Сотрудники» вы пока не найдены."

    await update.message.reply_text(text)


def format_kpi_lines(kpi_items):
    if not kpi_items:
        return "—"

    lines = []

    for item in kpi_items:
        qty = safe_float(item.get("qty"))
        lines.append(f"{item.get('name')} — {money(qty)}")

    return "\n".join(lines)


def format_daily_report_text(report_model):
    employee = report_model["employee"]
    return "\n".join(
        [
            "📝 Ежедневный отчет",
            "",
            f"Сотрудник: {employee['full_name']}",
            f"Дата: {report_model['date']}",
            f"Время работы: {report_model['interval']}",
            f"Отработано часов: {money(report_model['hours'])}",
            "",
            "Задачи:",
            report_model["tasks"] or "—",
            "",
            "KPI:",
            format_kpi_lines(report_model["kpi_items"]),
        ]
    )


async def send_daily_report_to_topic(context: ContextTypes.DEFAULT_TYPE, report_model):
    if not GROUP_CHAT_ID or not PAYROLL_REPORT_TOPIC_ID:
        return {"chat_id": "", "thread_id": "", "message_id": ""}

    message = await context.bot.send_message(
        chat_id=int(GROUP_CHAT_ID),
        message_thread_id=int(PAYROLL_REPORT_TOPIC_ID),
        text=format_daily_report_text(report_model),
    )
    return {
        "chat_id": int(GROUP_CHAT_ID),
        "thread_id": int(PAYROLL_REPORT_TOPIC_ID),
        "message_id": message.message_id,
    }


async def delete_old_report_message(context: ContextTypes.DEFAULT_TYPE, report_model):
    chat_id = report_model.get("telegram_chat_id")
    message_id = report_model.get("telegram_message_id")
    if not chat_id or not message_id:
        return False
    try:
        await context.bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
        return True
    except Exception:
        logging.exception("Не удалось удалить старое сообщение ежедневного отчета")
        return False


# ============================================================
# СОЗДАНИЕ ЕЖЕДНЕВНОГО ОТЧЕТА
# ============================================================


async def create_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    if not employee:
        await deny_unknown_user(update)
        return ConversationHandler.END

    context.user_data["pay_action"] = "create_report"

    if is_manager(employee):
        await query.edit_message_text(
            "Выберите сотрудника для ежедневного отчета:",
            reply_markup=employees_keyboard("cremp"),
        )
        return CREATE_EMPLOYEE

    context.user_data["employee_id"] = employee["employee_id"]
    await query.edit_message_text(
        f"Сотрудник: {employee['full_name']}\n\nВыберите дату отчета:",
        reply_markup=date_keyboard("crdate"),
    )
    return CREATE_DATE


async def create_employee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.replace("cremp:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_back_keyboard())
        return CREATE_EMPLOYEE

    context.user_data["employee_id"] = employee_id
    await query.edit_message_text(
        f"Сотрудник: {employee['full_name']}\n\nВыберите дату отчета:",
        reply_markup=date_keyboard("crdate"),
    )
    return CREATE_DATE


async def create_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report_date = query.data.replace("crdate:", "")
    employee_id = context.user_data.get("employee_id")
    employee = get_employee_by_id(employee_id)

    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_back_keyboard())
        return CREATE_DATE

    if find_report_row(employee_id, report_date)[0] is not None:
        await query.edit_message_text(
            f"Отчет сотрудника {employee['full_name']} за {report_date} уже существует.\n"
            "Используйте «Изменить отчет».",
            reply_markup=payroll_main_keyboard(manager=is_manager(current_employee_or_none(update))),
        )
        return ConversationHandler.END

    context.user_data["report_date"] = report_date
    await query.edit_message_text(
        f"Сотрудник: {employee['full_name']}\nДата: {report_date}\n\n"
        "Введите рабочий временной промежуток, например: 10:00-19:00",
        reply_markup=payroll_back_keyboard(),
    )
    return CREATE_INTERVAL


async def create_interval_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    interval = update.message.text.strip()
    if not interval:
        await update.message.reply_text("Введите рабочий временной промежуток:", reply_markup=payroll_back_keyboard())
        return CREATE_INTERVAL

    context.user_data["interval"] = interval
    await update.message.reply_text(
        "Введите количество отработанных часов. Можно кратно 0.5, например 8 или 7.5:",
        reply_markup=payroll_back_keyboard(),
    )
    return CREATE_HOURS


async def create_hours_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hours = parse_hours(update.message.text)
    if hours is None:
        await update.message.reply_text("Введите часы числом, кратным 0.5. Например: 8 или 7.5")
        return CREATE_HOURS

    context.user_data["hours"] = hours
    await update.message.reply_text("Опишите выполненные за день задачи:", reply_markup=payroll_back_keyboard())
    return CREATE_TASKS


async def create_tasks_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = update.message.text.strip()
    if not tasks:
        await update.message.reply_text("Описание задач не должно быть пустым. Введите задачи:")
        return CREATE_TASKS

    context.user_data["tasks"] = tasks
    context.user_data["kpi_items"] = []
    await update.message.reply_text(
        "Выберите категорию KPI или нажмите «Завершить KPI»:",
        reply_markup=kpi_keyboard("crkpi"),
    )
    return CREATE_KPI_SELECT


async def create_kpi_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kpi_id = query.data.replace("crkpi:", "")

    if kpi_id == "done":
        return await finish_create_report(query, context, update.effective_user)

    kpi_items = get_kpi_items()
    selected = next((item for item in kpi_items if item["kpi_id"] == kpi_id), None)
    if not selected:
        await query.edit_message_text("KPI не найден. Выберите заново:", reply_markup=kpi_keyboard("crkpi"))
        return CREATE_KPI_SELECT

    context.user_data["selected_kpi"] = selected
    await query.edit_message_text(
        f"KPI: {selected['name']}\n\nВведите количество:",
        reply_markup=payroll_back_keyboard(),
    )
    return CREATE_KPI_QTY


async def create_kpi_qty_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = parse_positive_amount(update.message.text)
    if qty is None:
        await update.message.reply_text("Введите количество числом больше 0:")
        return CREATE_KPI_QTY

    selected = context.user_data.get("selected_kpi")
    if not selected:
        await update.message.reply_text("KPI потерялся. Выберите категорию заново:", reply_markup=kpi_keyboard("crkpi"))
        return CREATE_KPI_SELECT

    context.user_data.setdefault("kpi_items", []).append(
        {
            "kpi_id": selected["kpi_id"],
            "name": selected["name"],
            "rate": selected["rate"],
            "qty": qty,
            "sum": qty * selected["rate"],
        }
    )
    context.user_data.pop("selected_kpi", None)

    await update.message.reply_text(
        "KPI добавлен. Выберите еще один KPI или нажмите «Завершить KPI»:",
        reply_markup=kpi_keyboard("crkpi"),
    )
    return CREATE_KPI_SELECT


async def finish_create_report(target, context: ContextTypes.DEFAULT_TYPE, telegram_user):
    employee = get_employee_by_id(context.user_data.get("employee_id"))
    if not employee:
        await target.edit_message_text("Сотрудник не найден.")
        return ConversationHandler.END

    report_date = context.user_data["report_date"]
    interval = context.user_data["interval"]
    hours = context.user_data["hours"]
    tasks = context.user_data["tasks"]
    kpi_items = context.user_data.get("kpi_items", [])

    report_model = {
        "date": report_date,
        "employee": employee,
        "interval": interval,
        "hours": hours,
        "tasks": tasks,
        "kpi_items": kpi_items,
        "kpi_sum": calculate_kpi_sum(kpi_items),
        "telegram_chat_id": "",
        "telegram_message_id": "",
    }

    try:
        telegram_data = await send_daily_report_to_topic(context, report_model)
        append_daily_report(employee, report_date, interval, hours, tasks, kpi_items, telegram_data)
        status = "Отчет сохранен и отправлен в тему ✅"
    except Exception as error:
        logging.exception("Ошибка создания ежедневного отчета")
        status = f"Отчет не удалось сохранить/отправить ⚠️\nОшибка: {error}"

    manager = is_manager(find_employee_for_telegram_user(telegram_user))
    await target.edit_message_text(
        f"{format_daily_report_text(report_model)}\n\n{status}",
        reply_markup=payroll_main_keyboard(manager=manager),
    )
    context.user_data.clear()
    return ConversationHandler.END

# ============================================================
# ИЗМЕНЕНИЕ ЕЖЕДНЕВНОГО ОТЧЕТА
# ============================================================


async def edit_report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    current_employee = current_employee_or_none(update)
    if not current_employee:
        await deny_unknown_user(update)
        return ConversationHandler.END

    context.user_data["pay_action"] = "edit_report"

    if is_manager(current_employee):
        await query.edit_message_text(
            "Выберите сотрудника, чей отчет нужно изменить:",
            reply_markup=employees_keyboard("edemp"),
        )
        return EDIT_EMPLOYEE

    context.user_data["employee_id"] = current_employee["employee_id"]
    await query.edit_message_text(
        f"Сотрудник: {current_employee['full_name']}\n\nВыберите дату отчета:",
        reply_markup=date_keyboard("eddate"),
    )
    return EDIT_DATE


async def edit_employee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.replace("edemp:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_back_keyboard())
        return EDIT_EMPLOYEE

    context.user_data["employee_id"] = employee_id
    await query.edit_message_text(
        f"Сотрудник: {employee['full_name']}\n\nВыберите дату отчета:",
        reply_markup=date_keyboard("eddate"),
    )
    return EDIT_DATE


async def edit_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report_date = query.data.replace("eddate:", "")
    employee_id = context.user_data.get("employee_id")
    row_index, report_data = find_report_row(employee_id, report_date)

    if not report_data:
        await query.edit_message_text(
            "Отчет за эту дату не найден.",
            reply_markup=payroll_main_keyboard(manager=is_manager(current_employee_or_none(update))),
        )
        return ConversationHandler.END

    context.user_data["edit_row_index"] = row_index
    context.user_data["edit_report_data"] = report_data
    await query.edit_message_text(
        "Отчет найден. Что нужно изменить?",
        reply_markup=edit_field_keyboard(),
    )
    return EDIT_FIELD


async def edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("editfield:", "")

    if field == "finish":
        return await finish_edit_report(query, context, update.effective_user)

    context.user_data["edit_field"] = field

    if field == "interval":
        await query.edit_message_text("Введите новый рабочий промежуток:", reply_markup=payroll_back_keyboard())
        return EDIT_VALUE

    if field == "hours":
        await query.edit_message_text("Введите новое количество часов:", reply_markup=payroll_back_keyboard())
        return EDIT_VALUE

    if field == "tasks":
        await query.edit_message_text("Введите новое описание задач:", reply_markup=payroll_back_keyboard())
        return EDIT_VALUE

    if field == "kpi":
        context.user_data["edit_new_kpi_items"] = []
        await query.edit_message_text(
            "Выберите KPI заново или нажмите «Завершить KPI». Старый список KPI будет заменен новым.",
            reply_markup=kpi_keyboard("edkpi"),
        )
        return EDIT_KPI_SELECT

    await query.edit_message_text("Неизвестное поле.", reply_markup=edit_field_keyboard())
    return EDIT_FIELD


async def edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    field = context.user_data.get("edit_field")
    report_data = context.user_data.get("edit_report_data") or {}

    if not value:
        await update.message.reply_text("Значение не должно быть пустым. Введите заново:")
        return EDIT_VALUE

    if field == "interval":
        report_data["Рабочий промежуток"] = value
    elif field == "hours":
        hours = parse_hours(value)
        if hours is None:
            await update.message.reply_text("Введите часы числом, кратным 0.5. Например: 8 или 7.5")
            return EDIT_VALUE
        report_data["Отработано часов"] = hours
    elif field == "tasks":
        report_data["Задачи"] = value
    else:
        await update.message.reply_text("Неизвестное поле.")
        return EDIT_FIELD

    report_data["Обновлено"] = now_str()
    context.user_data["edit_report_data"] = report_data

    await update.message.reply_text(
        "Изменение принято. Выберите ещё поле или нажмите «Завершить изменение».",
        reply_markup=edit_field_keyboard(),
    )
    return EDIT_FIELD


async def edit_kpi_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kpi_id = query.data.replace("edkpi:", "")

    if kpi_id == "done":
        report_data = context.user_data.get("edit_report_data") or {}
        kpi_items = context.user_data.get("edit_new_kpi_items", [])
        report_data["KPI данные"] = kpi_to_json(kpi_items)
        report_data["KPI сумма"] = calculate_kpi_sum(kpi_items)
        report_data["Обновлено"] = now_str()
        context.user_data["edit_report_data"] = report_data
        await query.edit_message_text(
            "KPI обновлен. Выберите ещё поле или нажмите «Завершить изменение».",
            reply_markup=edit_field_keyboard(),
        )
        return EDIT_FIELD

    selected = next((item for item in get_kpi_items() if item["kpi_id"] == kpi_id), None)
    if not selected:
        await query.edit_message_text("KPI не найден. Выберите заново:", reply_markup=kpi_keyboard("edkpi"))
        return EDIT_KPI_SELECT

    context.user_data["selected_kpi"] = selected
    await query.edit_message_text(
        f"KPI: {selected['name']}\n\nВведите количество:",
        reply_markup=payroll_back_keyboard(),
    )
    return EDIT_KPI_QTY


async def edit_kpi_qty_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = parse_positive_amount(update.message.text)
    if qty is None:
        await update.message.reply_text("Введите количество числом больше 0:")
        return EDIT_KPI_QTY

    selected = context.user_data.get("selected_kpi")
    if not selected:
        await update.message.reply_text("KPI потерялся. Выберите категорию заново:", reply_markup=kpi_keyboard("edkpi"))
        return EDIT_KPI_SELECT

    context.user_data.setdefault("edit_new_kpi_items", []).append(
        {
            "kpi_id": selected["kpi_id"],
            "name": selected["name"],
            "rate": selected["rate"],
            "qty": qty,
            "sum": qty * selected["rate"],
        }
    )
    context.user_data.pop("selected_kpi", None)

    await update.message.reply_text(
        "KPI добавлен. Выберите ещё KPI или нажмите «Завершить KPI»:",
        reply_markup=kpi_keyboard("edkpi"),
    )
    return EDIT_KPI_SELECT


async def finish_edit_report(query, context: ContextTypes.DEFAULT_TYPE, telegram_user):
    row_index = context.user_data.get("edit_row_index")
    report_data = context.user_data.get("edit_report_data")

    if not row_index or not report_data:
        await query.edit_message_text("Данные отчета потерялись.")
        return ConversationHandler.END

    old_model = report_data_to_model(report_data)
    await delete_old_report_message(context, old_model)

    model = report_data_to_model(report_data)
    model["kpi_sum"] = calculate_kpi_sum(model["kpi_items"])
    report_data["KPI сумма"] = model["kpi_sum"]
    report_data["Обновлено"] = now_str()

    try:
        telegram_data = await send_daily_report_to_topic(context, model)
        report_data["telegram_chat_id"] = telegram_data.get("chat_id", "")
        report_data["telegram_thread_id"] = telegram_data.get("thread_id", "")
        report_data["telegram_message_id"] = telegram_data.get("message_id", "")
        update_daily_report(row_index, report_data)
        status = "Отчет обновлен и новое сообщение отправлено в тему ✅"
    except Exception as error:
        logging.exception("Ошибка обновления отчета")
        status = f"Отчет не удалось обновить полностью ⚠️\nОшибка: {error}"

    manager = is_manager(find_employee_for_telegram_user(telegram_user))
    await query.edit_message_text(
        f"{format_daily_report_text(model)}\n\n{status}",
        reply_markup=payroll_main_keyboard(manager=manager),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ============================================================
# ПРОВЕРКА ЗП
# ============================================================


async def check_salary_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    if not employee:
        await deny_unknown_user(update)
        return ConversationHandler.END

    if is_manager(employee):
        await query.edit_message_text(
            "Выберите сотрудника для проверки ЗП:",
            reply_markup=employees_keyboard("salemp"),
        )
        return SALARY_EMPLOYEE

    text = build_personal_salary_text(employee)
    await query.edit_message_text(text, reply_markup=payroll_main_keyboard(manager=False))
    return ConversationHandler.END


async def salary_employee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.replace("salemp:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_main_keyboard(manager=True))
        return ConversationHandler.END

    text = build_personal_salary_text(employee)
    await query.edit_message_text(text, reply_markup=payroll_main_keyboard(manager=True))
    return ConversationHandler.END


# ============================================================
# РАСХОДЫ
# ============================================================


async def expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    employee = current_employee_or_none(update)
    if not employee:
        await deny_unknown_user(update)
        return ConversationHandler.END

    if is_manager(employee):
        await query.edit_message_text("Выберите сотрудника для расхода:", reply_markup=employees_keyboard("exemp"))
        return EXPENSE_EMPLOYEE

    context.user_data["employee_id"] = employee["employee_id"]
    await query.edit_message_text("Выберите дату расхода:", reply_markup=date_keyboard("exdate"))
    return EXPENSE_DATE


async def expense_employee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.replace("exemp:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_back_keyboard())
        return EXPENSE_EMPLOYEE
    context.user_data["employee_id"] = employee_id
    await query.edit_message_text("Выберите дату расхода:", reply_markup=date_keyboard("exdate"))
    return EXPENSE_DATE


async def expense_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["expense_date"] = query.data.replace("exdate:", "")
    await query.edit_message_text("Введите комментарий к расходу:", reply_markup=payroll_back_keyboard())
    return EXPENSE_COMMENT


async def expense_comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if not comment:
        await update.message.reply_text("Комментарий не должен быть пустым. Введите комментарий:")
        return EXPENSE_COMMENT
    context.user_data["expense_comment"] = comment
    await update.message.reply_text("Введите сумму расхода:", reply_markup=payroll_back_keyboard())
    return EXPENSE_AMOUNT


async def expense_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_positive_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Введите сумму числом больше 0:")
        return EXPENSE_AMOUNT

    employee = get_employee_by_id(context.user_data.get("employee_id"))
    current_employee = current_employee_or_none(update)
    append_expense(
        employee,
        context.user_data["expense_date"],
        context.user_data["expense_comment"],
        amount,
        current_employee["full_name"] if current_employee else str(update.effective_user.id),
    )
    await update.message.reply_text(
        f"Расход добавлен ✅\n\nСотрудник: {employee['full_name']}\nДата: {context.user_data['expense_date']}\nСумма: {money(amount)}",
        reply_markup=payroll_main_keyboard(manager=is_manager(current_employee)),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ============================================================
# ШТРАФЫ
# ============================================================


async def penalty_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    await query.edit_message_text("Выберите сотрудника для штрафа:", reply_markup=employees_keyboard("pnemp"))
    return PENALTY_EMPLOYEE


async def penalty_employee_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employee_id = query.data.replace("pnemp:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=payroll_back_keyboard())
        return PENALTY_EMPLOYEE
    context.user_data["employee_id"] = employee_id
    await query.edit_message_text("Введите дату штрафа в формате ДД.ММ.ГГГГ:", reply_markup=payroll_back_keyboard())
    return PENALTY_DATE


async def penalty_date_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_value = update.message.text.strip()
    if not validate_date(date_value):
        await update.message.reply_text("Неверный формат даты. Введите ДД.ММ.ГГГГ:")
        return PENALTY_DATE
    context.user_data["penalty_date"] = date_value
    await update.message.reply_text("Введите комментарий к штрафу:", reply_markup=payroll_back_keyboard())
    return PENALTY_COMMENT


async def penalty_comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if not comment:
        await update.message.reply_text("Комментарий не должен быть пустым. Введите комментарий:")
        return PENALTY_COMMENT
    context.user_data["penalty_comment"] = comment
    await update.message.reply_text("Введите сумму штрафа:", reply_markup=payroll_back_keyboard())
    return PENALTY_AMOUNT


async def penalty_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_positive_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Введите сумму числом больше 0:")
        return PENALTY_AMOUNT

    employee = get_employee_by_id(context.user_data.get("employee_id"))
    current_employee = current_employee_or_none(update)
    append_penalty(
        employee,
        context.user_data["penalty_date"],
        context.user_data["penalty_comment"],
        amount,
        current_employee["full_name"] if current_employee else str(update.effective_user.id),
    )
    await update.message.reply_text(
        f"Штраф добавлен ✅\n\nСотрудник: {employee['full_name']}\nДата: {context.user_data['penalty_date']}\nСумма: {money(amount)}",
        reply_markup=payroll_main_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END

# ============================================================
# РАСЧЕТНЫЕ ПЕРИОДЫ
# ============================================================


async def periods_menu_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    active = get_active_period()
    active_text = "Активный период не настроен."
    if active:
        active_text = f"Активный период:\n{active['name']}\n{active['start_date']} — {active['end_date']}"
    await query.edit_message_text(active_text, reply_markup=periods_keyboard())
    return ConversationHandler.END


async def period_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["period_action"] = "create"
    await query.edit_message_text("Введите название расчетного периода:", reply_markup=payroll_back_keyboard())
    return PERIOD_NAME


async def period_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не должно быть пустым. Введите название:")
        return PERIOD_NAME
    context.user_data["period_name"] = name
    await update.message.reply_text("Введите дату начала периода в формате ДД.ММ.ГГГГ:", reply_markup=payroll_back_keyboard())
    return PERIOD_START


async def period_start_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_value = update.message.text.strip()
    if not validate_date(date_value):
        await update.message.reply_text("Неверный формат даты. Введите ДД.ММ.ГГГГ:")
        return PERIOD_START
    context.user_data["period_start"] = date_value
    await update.message.reply_text("Введите дату конца периода в формате ДД.ММ.ГГГГ:", reply_markup=payroll_back_keyboard())
    return PERIOD_END


async def period_end_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_value = update.message.text.strip()
    if not validate_date(date_value):
        await update.message.reply_text("Неверный формат даты. Введите ДД.ММ.ГГГГ:")
        return PERIOD_END

    current_employee = current_employee_or_none(update)
    name = context.user_data["period_name"]
    start_date = context.user_data["period_start"]
    end_date = date_value

    create_active_period(name, start_date, end_date, current_employee["full_name"])
    await update.message.reply_text(
        f"Активный расчетный период создан ✅\n\n{name}\n{start_date} — {end_date}",
        reply_markup=payroll_main_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def period_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    active = get_active_period()
    if not active:
        await query.edit_message_text("Активный период не настроен.", reply_markup=periods_keyboard())
        return ConversationHandler.END

    await query.edit_message_text(
        f"Текущий период:\n{active['name']}\n{active['start_date']} — {active['end_date']}\n\nЧто изменить?",
        reply_markup=period_edit_field_keyboard(),
    )
    return PERIOD_EDIT_FIELD


async def period_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("periodfield:", "")
    context.user_data["period_edit_field"] = field

    if field == "name":
        await query.edit_message_text("Введите новое название периода:", reply_markup=payroll_back_keyboard())
    elif field == "start":
        await query.edit_message_text("Введите новую дату начала в формате ДД.ММ.ГГГГ:", reply_markup=payroll_back_keyboard())
    elif field == "end":
        await query.edit_message_text("Введите новую дату конца в формате ДД.ММ.ГГГГ:", reply_markup=payroll_back_keyboard())
    else:
        await query.edit_message_text("Неизвестное поле.", reply_markup=period_edit_field_keyboard())
        return PERIOD_EDIT_FIELD
    return PERIOD_EDIT_VALUE


async def period_edit_value_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    field = context.user_data.get("period_edit_field")
    if not value:
        await update.message.reply_text("Значение не должно быть пустым. Введите заново:")
        return PERIOD_EDIT_VALUE

    if field in {"start", "end"} and not validate_date(value):
        await update.message.reply_text("Неверный формат даты. Введите ДД.ММ.ГГГГ:")
        return PERIOD_EDIT_VALUE

    kwargs = {}
    if field == "name":
        kwargs["name"] = value
    elif field == "start":
        kwargs["start_date"] = value
    elif field == "end":
        kwargs["end_date"] = value

    updated = update_active_period(**kwargs)
    if not updated:
        await update.message.reply_text("Активный период не найден.", reply_markup=payroll_main_keyboard(manager=True))
        return ConversationHandler.END

    active = get_active_period()
    await update.message.reply_text(
        f"Период обновлен ✅\n\n{active['name']}\n{active['start_date']} — {active['end_date']}",
        reply_markup=payroll_main_keyboard(manager=True),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def period_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    periods = get_periods()
    if not periods:
        await query.edit_message_text("Расчетные периоды пока не созданы.", reply_markup=periods_keyboard())
        return ConversationHandler.END

    lines = ["Расчетные периоды:"]
    for period in periods[-15:]:
        status = "активный" if period["status"] == "active" else "закрытый"
        lines.append(f"\n{period['name']}\n{period['start_date']} — {period['end_date']}\nСтатус: {status}")
    await query.edit_message_text("\n".join(lines), reply_markup=periods_keyboard())
    return ConversationHandler.END


# ============================================================
# РАСЧЕТ ЗП ЗА ПЕРИОД + PDF
# ============================================================




def split_long_message(text, limit=3900):
    chunks = []
    current = ""
    for line in text.splitlines():
        candidate = current + ("\n" if current else "") + line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
                current = line
            else:
                chunks.append(line[:limit])
                current = line[limit:]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks

async def calculate_period_payroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    active = get_active_period()
    if not active:
        await query.edit_message_text(
            "Активный расчетный период не настроен. Создайте его в разделе «Расчетные периоды».",
            reply_markup=payroll_main_keyboard(manager=True),
        )
        return ConversationHandler.END

    text = build_full_payroll_text(active)

    if len(text) <= 3900:
        await query.edit_message_text(text, reply_markup=payroll_main_keyboard(manager=True))
    else:
        await query.edit_message_text("Отчет получился длинным. Отправляю частями и PDF...", reply_markup=payroll_main_keyboard(manager=True))
        for chunk in split_long_message(text):
            await context.bot.send_message(chat_id=query.message.chat_id, text=chunk)

    try:
        filename = f"payroll_{active['start_date'].replace('.', '-')}_{active['end_date'].replace('.', '-')}.pdf"
        pdf_path = create_payroll_pdf(text, filename=filename)
        with open(pdf_path, "rb") as file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=file,
                filename=filename,
                caption="PDF ведомость ЗП",
            )
    except Exception as error:
        logging.exception("Не удалось создать PDF ведомость")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"PDF не удалось создать ⚠️\nОшибка: {error}",
        )

    return ConversationHandler.END


# ============================================================
# ОЧИСТКА СТАРЫХ ДАННЫХ
# ============================================================


async def cleanup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current_employee = current_employee_or_none(update)
    if not is_manager(current_employee):
        await query.edit_message_text("Недостаточно прав.")
        return ConversationHandler.END

    await query.edit_message_text(
        "Удалить данные старше 1 года из листов «Ежедневные отчеты», «Расходы», «Штрафы»?\n\n"
        "Справочники сотрудников, KPI и расчетные периоды не будут удалены.",
        reply_markup=cleanup_confirm_keyboard(),
    )
    return CLEANUP_CONFIRM


async def cleanup_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    result = cleanup_old_operational_data(days=365)
    lines = ["Очистка завершена ✅"]
    for sheet_name, count in result.items():
        lines.append(f"{sheet_name}: удалено строк — {count}")

    await query.edit_message_text("\n".join(lines), reply_markup=payroll_main_keyboard(manager=True))
    return ConversationHandler.END


# ============================================================
# HANDLERS
# ============================================================


def get_payroll_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_report_start, pattern=r"^pay:create_report$"),
            CallbackQueryHandler(edit_report_start, pattern=r"^pay:edit_report$"),
            CallbackQueryHandler(check_salary_start, pattern=r"^pay:check_salary$"),
            CallbackQueryHandler(expense_start, pattern=r"^pay:add_expense$"),
            CallbackQueryHandler(penalty_start, pattern=r"^pay:add_penalty$"),
            CallbackQueryHandler(periods_menu_start, pattern=r"^pay:periods$"),
            CallbackQueryHandler(period_create_start, pattern=r"^period:create$"),
            CallbackQueryHandler(period_edit_start, pattern=r"^period:edit$"),
            CallbackQueryHandler(period_list, pattern=r"^period:list$"),
            CallbackQueryHandler(calculate_period_payroll, pattern=r"^pay:calculate_period$"),
            CallbackQueryHandler(cleanup_start, pattern=r"^pay:cleanup$"),
        ],
        states={
            CREATE_EMPLOYEE: [
                CallbackQueryHandler(create_employee_selected, pattern=r"^cremp:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_DATE: [
                CallbackQueryHandler(create_date_selected, pattern=r"^crdate:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_interval_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_HOURS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_hours_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_TASKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_tasks_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_KPI_SELECT: [
                CallbackQueryHandler(create_kpi_selected, pattern=r"^crkpi:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CREATE_KPI_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_kpi_qty_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_EMPLOYEE: [
                CallbackQueryHandler(edit_employee_selected, pattern=r"^edemp:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_DATE: [
                CallbackQueryHandler(edit_date_selected, pattern=r"^eddate:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(edit_field_selected, pattern=r"^editfield:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_KPI_SELECT: [
                CallbackQueryHandler(edit_kpi_selected, pattern=r"^edkpi:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EDIT_KPI_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_kpi_qty_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            SALARY_EMPLOYEE: [
                CallbackQueryHandler(salary_employee_selected, pattern=r"^salemp:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EXPENSE_EMPLOYEE: [
                CallbackQueryHandler(expense_employee_selected, pattern=r"^exemp:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EXPENSE_DATE: [
                CallbackQueryHandler(expense_date_selected, pattern=r"^exdate:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EXPENSE_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_comment_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            EXPENSE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_amount_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PENALTY_EMPLOYEE: [
                CallbackQueryHandler(penalty_employee_selected, pattern=r"^pnemp:"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PENALTY_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, penalty_date_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PENALTY_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, penalty_comment_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PENALTY_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, penalty_amount_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PERIOD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, period_name_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PERIOD_START: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, period_start_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PERIOD_END: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, period_end_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PERIOD_EDIT_FIELD: [
                CallbackQueryHandler(period_edit_field_selected, pattern=r"^periodfield:"),
                CallbackQueryHandler(periods_menu_start, pattern=r"^pay:periods$"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PERIOD_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, period_edit_value_received),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            CLEANUP_CONFIRM: [
                CallbackQueryHandler(cleanup_confirm, pattern=r"^cleanup:yes$"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payroll_cancel)],
    )


def get_payroll_handlers():
    return [
        CommandHandler("whoami", whoami),
        CallbackQueryHandler(payroll_menu, pattern=r"^section:payroll$"),
        get_payroll_conversation_handler(),
    ]
