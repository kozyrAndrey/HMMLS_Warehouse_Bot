from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from core.keyboards import build_employees_menu_keyboard
from modules.payroll.google_sheets import (
    append_employee,
    get_employee_by_id,
    get_employees,
    is_manager,
    money,
    safe_float,
    set_employee_active,
    find_employee_for_telegram_user,
    update_employee_fields,
)


(
    EMP_ADD_NAME,
    EMP_ADD_PHONE,
    EMP_ADD_TG_ID,
    EMP_ADD_USERNAME,
    EMP_ADD_ROLE,
    EMP_ADD_HOURLY_RATE,
    EMP_ADD_FIXED_SALARY,
    EMP_ADD_COMMON_FUND,
    EMP_FIRE_SELECT,
    EMP_FIRE_CONFIRM,
    EMP_EDIT_SELECT,
    EMP_EDIT_FIELD,
    EMP_EDIT_VALUE,
) = range(1500, 1513)


EMPLOYEE_ROLES = [
    ("warehouse_employee", "Сотрудник склада"),
    ("warehouse_manager", "Руководитель склада"),
    ("brand_manager", "Руководитель бренда"),
    ("admin", "Администратор"),
]

EDIT_FIELDS = [
    ("full_name", "ФИО"),
    ("phone", "Телефон"),
    ("telegram_user_id", "Telegram user_id"),
    ("telegram_username", "Telegram username"),
    ("role", "Роль"),
    ("hourly_rate", "Часовая ставка"),
    ("fixed_salary", "Оклад"),
    ("include_in_common_fund", "Участие в общем фонде"),
    ("is_active", "Активность"),
]


def current_employee(update: Update):
    return find_employee_for_telegram_user(update.effective_user)


def ensure_manager(update: Update):
    return is_manager(current_employee(update))


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")]])


def roles_keyboard():
    rows = [[InlineKeyboardButton(label, callback_data=f"emprole:{role}")] for role, label in EMPLOYEE_ROLES]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")])
    return InlineKeyboardMarkup(rows)


def common_fund_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Да", callback_data="empfund:yes")],
        [InlineKeyboardButton("Нет", callback_data="empfund:no")],
        [InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")],
    ])


def active_employees_keyboard(prefix):
    rows = []
    for employee in get_employees(include_inactive=False):
        rows.append([InlineKeyboardButton(employee["full_name"], callback_data=f"{prefix}:{employee['employee_id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")])
    return InlineKeyboardMarkup(rows)


def employees_keyboard(prefix, include_inactive=False):
    rows = []
    for employee in get_employees(include_inactive=include_inactive):
        status = "" if employee.get("is_active") else " 🚫"
        rows.append([InlineKeyboardButton(f"{employee['full_name']}{status}", callback_data=f"{prefix}:{employee['employee_id']}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")])
    return InlineKeyboardMarkup(rows)


def edit_fields_keyboard():
    rows = [[InlineKeyboardButton(label, callback_data=f"empeditfield:{field}")] for field, label in EDIT_FIELDS]
    rows.append([InlineKeyboardButton("✅ Готово", callback_data="empedit:done")])
    return InlineKeyboardMarkup(rows)


def bool_edit_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Да", callback_data=f"{prefix}:yes")],
        [InlineKeyboardButton("Нет", callback_data=f"{prefix}:no")],
        [InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")],
    ])


def employee_card(employee):
    username = employee.get("telegram_username") or ""
    if username:
        username = f"@{username}"
    else:
        username = "—"

    return (
        f"ФИО: {employee['full_name']}\n"
        f"Телефон: {employee.get('phone') or '—'}\n"
        f"Telegram user_id: {employee.get('telegram_user_id') or '—'}\n"
        f"Telegram username: {username}\n"
        f"Роль: {employee.get('role') or '—'}\n"
        f"Часовая ставка: {money(employee.get('hourly_rate', 0))}\n"
        f"Оклад: {money(employee.get('fixed_salary', 0))}\n"
        f"Общий фонд: {'да' if employee.get('include_in_common_fund') else 'нет'}\n"
        f"Активен: {'да' if employee.get('is_active') else 'нет'}"
    )


async def employees_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not ensure_manager(update):
        await query.edit_message_text("⛔️ Управление сотрудниками доступно только руководителям.")
        return ConversationHandler.END

    context.user_data["employee_add"] = {}
    await query.edit_message_text("Введите ФИО сотрудника:", reply_markup=cancel_keyboard())
    return EMP_ADD_NAME


async def employee_add_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = (update.message.text or "").strip()
    if not full_name:
        await update.message.reply_text("Введите непустое ФИО:", reply_markup=cancel_keyboard())
        return EMP_ADD_NAME

    context.user_data["employee_add"]["full_name"] = full_name
    await update.message.reply_text(
        "Введите номер телефона сотрудника или «-», если пока неизвестен:",
        reply_markup=cancel_keyboard(),
    )
    return EMP_ADD_PHONE


async def employee_add_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.message.text or "").strip()
    context.user_data["employee_add"]["phone"] = "" if value == "-" else value
    await update.message.reply_text(
        "Введите Telegram user_id сотрудника или «-», если пока неизвестен:",
        reply_markup=cancel_keyboard(),
    )
    return EMP_ADD_TG_ID


async def employee_add_tg_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.message.text or "").strip()
    context.user_data["employee_add"]["telegram_user_id"] = "" if value == "-" else value
    await update.message.reply_text(
        "Введите Telegram username без @ или «-», если пока неизвестен:",
        reply_markup=cancel_keyboard(),
    )
    return EMP_ADD_USERNAME


async def employee_add_username_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.message.text or "").strip()
    context.user_data["employee_add"]["telegram_username"] = "" if value == "-" else value
    await update.message.reply_text("Выберите роль:", reply_markup=roles_keyboard())
    return EMP_ADD_ROLE


async def employee_add_role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    role = query.data.replace("emprole:", "")
    if role not in {role_key for role_key, _label in EMPLOYEE_ROLES}:
        await query.edit_message_text("Неизвестная роль.", reply_markup=roles_keyboard())
        return EMP_ADD_ROLE

    context.user_data["employee_add"]["role"] = role
    await query.edit_message_text("Введите часовую ставку, например 437.5:", reply_markup=cancel_keyboard())
    return EMP_ADD_HOURLY_RATE


async def employee_add_hourly_rate_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["employee_add"]["hourly_rate"] = safe_float(update.message.text)
    await update.message.reply_text("Введите фиксированный оклад или 0:", reply_markup=cancel_keyboard())
    return EMP_ADD_FIXED_SALARY


async def employee_add_fixed_salary_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["employee_add"]["fixed_salary"] = safe_float(update.message.text)
    await update.message.reply_text("Участвует в общем фонде?", reply_markup=common_fund_keyboard())
    return EMP_ADD_COMMON_FUND


async def employee_add_common_fund_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    include_in_common_fund = query.data.endswith(":yes")
    data = context.user_data.get("employee_add") or {}
    employee = append_employee(
        full_name=data.get("full_name", ""),
        phone=data.get("phone", ""),
        telegram_user_id=data.get("telegram_user_id", ""),
        telegram_username=data.get("telegram_username", ""),
        role=data.get("role", "warehouse_employee"),
        hourly_rate=data.get("hourly_rate", 0),
        fixed_salary=data.get("fixed_salary", 0),
        include_in_common_fund=include_in_common_fund,
    )
    context.user_data.pop("employee_add", None)

    await query.edit_message_text(
        "Сотрудник добавлен ✅\n\n"
        f"ФИО: {employee['full_name']}\n"
        f"Телефон: {employee.get('phone') or '—'}\n"
        f"Роль: {employee['role']}\n"
        f"Часовая ставка: {money(employee['hourly_rate'])}\n"
        f"Оклад: {money(employee['fixed_salary'])}",
        reply_markup=build_employees_menu_keyboard(),
    )
    return ConversationHandler.END


async def employees_fire_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not ensure_manager(update):
        await query.edit_message_text("⛔️ Управление сотрудниками доступно только руководителям.")
        return ConversationHandler.END

    await query.edit_message_text("Выберите сотрудника:", reply_markup=active_employees_keyboard("empfire"))
    return EMP_FIRE_SELECT


async def employee_fire_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee_id = query.data.replace("empfire:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    context.user_data["employee_fire_id"] = employee_id
    await query.edit_message_text(
        f"Уволить сотрудника {employee['full_name']}?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Да, уволить", callback_data="empfireconfirm:yes")],
            [InlineKeyboardButton("❌ Отмена", callback_data="emp:cancel")],
        ]),
    )
    return EMP_FIRE_CONFIRM


async def employee_fire_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee_id = context.user_data.get("employee_fire_id")
    employee = set_employee_active(employee_id, False)
    context.user_data.pop("employee_fire_id", None)

    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    await query.edit_message_text(
        f"Сотрудник {employee['full_name']} уволен ✅",
        reply_markup=build_employees_menu_keyboard(),
    )
    return ConversationHandler.END


async def employees_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not ensure_manager(update):
        await query.edit_message_text("⛔️ Управление сотрудниками доступно только руководителям.")
        return ConversationHandler.END

    await query.edit_message_text("Выберите сотрудника для редактирования:", reply_markup=employees_keyboard("empedit", True))
    return EMP_EDIT_SELECT


async def employee_edit_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee_id = query.data.replace("empedit:", "")
    employee = get_employee_by_id(employee_id)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    context.user_data["employee_edit_id"] = employee_id
    await query.edit_message_text(
        "Что изменить?\n\n" + employee_card(employee),
        reply_markup=edit_fields_keyboard(),
    )
    return EMP_EDIT_FIELD


async def employee_edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    field = query.data.replace("empeditfield:", "")
    if field not in {field_key for field_key, _label in EDIT_FIELDS}:
        await query.edit_message_text("Неизвестное поле.", reply_markup=edit_fields_keyboard())
        return EMP_EDIT_FIELD

    context.user_data["employee_edit_field"] = field

    if field == "role":
        await query.edit_message_text("Выберите новую роль:", reply_markup=roles_keyboard())
        return EMP_EDIT_VALUE

    if field == "include_in_common_fund":
        await query.edit_message_text("Участвует в общем фонде?", reply_markup=bool_edit_keyboard("empeditbool"))
        return EMP_EDIT_VALUE

    if field == "is_active":
        await query.edit_message_text("Сотрудник активен?", reply_markup=bool_edit_keyboard("empeditbool"))
        return EMP_EDIT_VALUE

    prompts = {
        "full_name": "Введите новое ФИО:",
        "phone": "Введите новый телефон или «-», чтобы очистить:",
        "telegram_user_id": "Введите новый Telegram user_id или «-», чтобы очистить:",
        "telegram_username": "Введите новый Telegram username без @ или «-», чтобы очистить:",
        "hourly_rate": "Введите новую часовую ставку:",
        "fixed_salary": "Введите новый оклад:",
    }
    await query.edit_message_text(prompts[field], reply_markup=cancel_keyboard())
    return EMP_EDIT_VALUE


async def employee_edit_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    employee_id = context.user_data.get("employee_edit_id")
    field = context.user_data.get("employee_edit_field")
    value = (update.message.text or "").strip()

    if not employee_id or not field:
        await update.message.reply_text("Не удалось понять, что редактируем.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    if value == "-":
        value = ""

    employee = update_employee_fields(employee_id, **{field: value})
    if not employee:
        await update.message.reply_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    context.user_data.pop("employee_edit_field", None)
    await update.message.reply_text(
        "Сохранено ✅\n\nЧто изменить дальше?\n\n" + employee_card(employee),
        reply_markup=edit_fields_keyboard(),
    )
    return EMP_EDIT_FIELD


async def employee_edit_role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee_id = context.user_data.get("employee_edit_id")
    role = query.data.replace("emprole:", "")
    employee = update_employee_fields(employee_id, role=role)
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    context.user_data.pop("employee_edit_field", None)
    await query.edit_message_text(
        "Сохранено ✅\n\nЧто изменить дальше?\n\n" + employee_card(employee),
        reply_markup=edit_fields_keyboard(),
    )
    return EMP_EDIT_FIELD


async def employee_edit_bool_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee_id = context.user_data.get("employee_edit_id")
    field = context.user_data.get("employee_edit_field")
    value = query.data.endswith(":yes")

    employee = update_employee_fields(employee_id, **{field: value})
    if not employee:
        await query.edit_message_text("Сотрудник не найден.", reply_markup=build_employees_menu_keyboard())
        return ConversationHandler.END

    context.user_data.pop("employee_edit_field", None)
    await query.edit_message_text(
        "Сохранено ✅\n\nЧто изменить дальше?\n\n" + employee_card(employee),
        reply_markup=edit_fields_keyboard(),
    )
    return EMP_EDIT_FIELD


async def employee_edit_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("employee_edit_id", None)
    context.user_data.pop("employee_edit_field", None)
    await query.edit_message_text("Редактирование завершено ✅", reply_markup=build_employees_menu_keyboard())
    return ConversationHandler.END


async def employees_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("employee_add", None)
    context.user_data.pop("employee_fire_id", None)
    context.user_data.pop("employee_edit_id", None)
    context.user_data.pop("employee_edit_field", None)
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Действие отменено.", reply_markup=build_employees_menu_keyboard())
    elif update.message:
        await update.message.reply_text("Действие отменено.", reply_markup=build_employees_menu_keyboard())
    return ConversationHandler.END


def get_employee_handlers():
    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(employees_add_start, pattern=r"^emp:add$"),
            CallbackQueryHandler(employees_edit_start, pattern=r"^emp:edit$"),
            CallbackQueryHandler(employees_fire_start, pattern=r"^emp:fire$"),
        ],
        states={
            EMP_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_name_received)],
            EMP_ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_phone_received)],
            EMP_ADD_TG_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_tg_id_received)],
            EMP_ADD_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_username_received)],
            EMP_ADD_ROLE: [CallbackQueryHandler(employee_add_role_selected, pattern=r"^emprole:")],
            EMP_ADD_HOURLY_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_hourly_rate_received)],
            EMP_ADD_FIXED_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, employee_add_fixed_salary_received)],
            EMP_ADD_COMMON_FUND: [CallbackQueryHandler(employee_add_common_fund_selected, pattern=r"^empfund:")],
            EMP_FIRE_SELECT: [CallbackQueryHandler(employee_fire_selected, pattern=r"^empfire:")],
            EMP_FIRE_CONFIRM: [CallbackQueryHandler(employee_fire_confirmed, pattern=r"^empfireconfirm:yes$")],
            EMP_EDIT_SELECT: [CallbackQueryHandler(employee_edit_selected, pattern=r"^empedit:")],
            EMP_EDIT_FIELD: [
                CallbackQueryHandler(employee_edit_done, pattern=r"^empedit:done$"),
                CallbackQueryHandler(employee_edit_field_selected, pattern=r"^empeditfield:"),
            ],
            EMP_EDIT_VALUE: [
                CallbackQueryHandler(employee_edit_role_selected, pattern=r"^emprole:"),
                CallbackQueryHandler(employee_edit_bool_selected, pattern=r"^empeditbool:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, employee_edit_text_received),
            ],
        },
        fallbacks=[CallbackQueryHandler(employees_cancel, pattern=r"^emp:cancel$")],
        name="employees_management",
        persistent=False,
    )
    return [conversation]
