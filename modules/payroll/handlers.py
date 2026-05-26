import logging
import os
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

# ID темы «Штрафы» в общей Telegram-группе.
# Добавь в .env: PAYROLL_PENALTIES_TOPIC_ID=...
PAYROLL_PENALTIES_TOPIC_ID = os.getenv("PAYROLL_PENALTIES_TOPIC_ID", "")
from core.keyboards import build_main_menu_keyboard
from modules.payroll.config import (
    PENALTY_ABSENCE_NO_REASON_TYPE_ID,
    PENALTY_AUTO_DISMISSAL_TYPE_ID,
    PENALTY_TYPES,
    PENALTY_TYPE_GROUPS,
)
from modules.payroll.calculations import build_full_payroll_text, build_personal_salary_text
from modules.payroll.google_sheets import (
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
    count_employee_penalties_by_type,
    money,
    report_data_to_model,
    safe_float,
    update_active_period,
    update_daily_report,
    update_report_message_ids,
    validate_date,
    now_str,
)
from modules.payroll.pdf_reports import create_payroll_pdf


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
    PENALTY_TYPE_GROUP,
    PENALTY_TYPE,
    PENALTY_COMMENT,
    PENALTY_AMOUNT,
    PENALTY_CONFIRM,
    PERIOD_NAME,
    PERIOD_START,
    PERIOD_END,
    PERIOD_EDIT_FIELD,
    PERIOD_EDIT_VALUE,
    CLEANUP_CONFIRM,
) = range(300, 331)


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


def edit_mode_keyboard(prefix):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Изменить полностью", callback_data=f"{prefix}:replace")],
            [InlineKeyboardButton("➕ Дополнить", callback_data=f"{prefix}:append")],
            [InlineKeyboardButton("⬅️ Назад к выбору поля", callback_data="editfield:back")],
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


def penalty_type_group_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Неверная отправка", callback_data="pntype:wrong_shipping")],
            [InlineKeyboardButton("Неверная инвентаризация", callback_data="pngrp:inventory")],
            [InlineKeyboardButton("Отчет позже срока", callback_data="pngrp:late_report")],
            [InlineKeyboardButton("Опоздание / невыход", callback_data="pngrp:lateness_absence")],
            [InlineKeyboardButton("Неверный пересчет расходников", callback_data="pntype:consumables_wrong_count")],
            [InlineKeyboardButton("Неверно положил товар на полку", callback_data="pntype:wrong_shelf")],
            [InlineKeyboardButton("Некачественная уборка", callback_data="pntype:poor_cleaning")],
            [InlineKeyboardButton("Офисные ключи", callback_data="pngrp:office_keys")],
            [InlineKeyboardButton("Неверное оприходование товара", callback_data="pngrp:receiving_errors")],
            [InlineKeyboardButton("Другое", callback_data="pntype:other")],
            [InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")],
        ]
    )


def penalty_type_keyboard(group_id):
    group = PENALTY_TYPE_GROUPS.get(group_id)
    rows = []

    if group:
        for penalty_type_id in group["items"]:
            penalty_type = PENALTY_TYPES[penalty_type_id]
            rows.append(
                [InlineKeyboardButton(penalty_type["name"], callback_data=f"pntype:{penalty_type_id}")]
            )

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="pngrp:back")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")])
    return InlineKeyboardMarkup(rows)


def penalty_confirm_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подтвердить", callback_data="penalty:confirm")],
            [InlineKeyboardButton("❌ Отмена", callback_data="pay:cancel")],
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


def format_penalty_topic_text(employee, penalty_date, penalty_category, penalty_type, comment, amount, created_by):
    return "\n".join(
        [
            "⚠️ Новый штраф",
            "",
            f"Сотрудник: {employee['full_name']}",
            f"Дата: {penalty_date}",
            f"Категория: {penalty_category}",
            f"Тип штрафа: {penalty_type}",
            f"Комментарий: {comment}",
            f"Сумма: {money(amount)}",
            "",
            f"Назначил: {created_by}",
        ]
    )


def format_penalty_preview(employee, penalty_date, penalty_category, penalty_type, comment, amount):
    return "\n".join(
        [
            "Проверьте штраф:",
            "",
            f"Сотрудник: {employee['full_name']}",
            f"Дата: {penalty_date}",
            f"Категория: {penalty_category}",
            f"Тип штрафа: {penalty_type}",
            f"Комментарий: {comment}",
            f"Сумма: {money(amount)}",
        ]
    )


async def send_penalty_to_topic(context: ContextTypes.DEFAULT_TYPE, employee, penalty_date, penalty_category, penalty_type, comment, amount, created_by):
    if not GROUP_CHAT_ID:
        return "GROUP_CHAT_ID не настроен, сообщение в тему «Штрафы» не отправлено."

    if not PAYROLL_PENALTIES_TOPIC_ID:
        return "PAYROLL_PENALTIES_TOPIC_ID не настроен, сообщение в тему «Штрафы» не отправлено."

    await context.bot.send_message(
        chat_id=int(GROUP_CHAT_ID),
        message_thread_id=int(PAYROLL_PENALTIES_TOPIC_ID),
        text=format_penalty_topic_text(employee, penalty_date, penalty_category, penalty_type, comment, amount, created_by),
    )

    return "Штраф отправлен в тему «Штрафы» ✅"


def last_30_days_period(end_date):
    end_dt = datetime.strptime(end_date, "%d.%m.%Y")
    start_dt = end_dt - timedelta(days=30)
    return start_dt.strftime("%d.%m.%Y"), end_dt.strftime("%d.%m.%Y")


async def maybe_send_third_absence_notice(context, employee, penalty_date, created_by):
    auto_type = PENALTY_TYPES[PENALTY_AUTO_DISMISSAL_TYPE_ID]
    absence_type = PENALTY_TYPES[PENALTY_ABSENCE_NO_REASON_TYPE_ID]
    start_date, end_date = last_30_days_period(penalty_date)

    absence_count = count_employee_penalties_by_type(
        employee_id=employee["employee_id"],
        penalty_type=absence_type["name"],
        start_date=start_date,
        end_date=end_date,
    )

    if absence_count != 3:
        return None

    comment = (
        f"За последние 30 дней ({start_date} — {end_date}) у сотрудника "
        "зафиксирован третий невыход на смену без уважительной причины. "
        "Необходимо рассмотреть вопрос об увольнении."
    )

    append_penalty(
        employee,
        penalty_date,
        auto_type["category"],
        auto_type["name"],
        comment,
        0,
        created_by,
    )

    try:
        return await send_penalty_to_topic(
            context=context,
            employee=employee,
            penalty_date=penalty_date,
            penalty_category=auto_type["category"],
            penalty_type=auto_type["name"],
            comment=comment,
            amount=0,
            created_by=created_by,
        )
    except Exception as error:
        logging.exception("Не удалось отправить автоматическое уведомление о третьем невыходе")
        return f"Автоуведомление о третьем невыходе не отправлено ⚠️\nОшибка: {error}"


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

    if field == "back":
        await query.edit_message_text(
            "Что нужно изменить?",
            reply_markup=edit_field_keyboard(),
        )
        return EDIT_FIELD

    context.user_data["edit_field"] = field
    report_data = context.user_data.get("edit_report_data") or {}

    if field == "interval":
        current_value = report_data.get("Рабочий промежуток", "") or "—"
        await query.edit_message_text(
            "Текущий рабочий промежуток:\n"
            f"{current_value}\n\n"
            "Введите новый рабочий промежуток:",
            reply_markup=payroll_back_keyboard(),
        )
        return EDIT_VALUE

    if field == "hours":
        current_value = report_data.get("Отработано часов", "") or "—"
        await query.edit_message_text(
            "Текущие отработанные часы:\n"
            f"{money(safe_float(current_value)) if current_value != '—' else '—'}\n\n"
            "Введите новое количество часов:",
            reply_markup=payroll_back_keyboard(),
        )
        return EDIT_VALUE

    if field == "tasks":
        current_tasks = report_data.get("Задачи", "") or "—"
        await query.edit_message_text(
            "Текущие задачи:\n"
            f"{current_tasks}\n\n"
            "Выберите действие:",
            reply_markup=edit_mode_keyboard("edittasks"),
        )
        return EDIT_FIELD

    if field == "kpi":
        current_kpi_items = kpi_from_json(report_data.get("KPI данные", ""))
        await query.edit_message_text(
            "Текущий KPI:\n"
            f"{format_kpi_lines(current_kpi_items)}\n\n"
            "Выберите действие:",
            reply_markup=edit_mode_keyboard("editkpi"),
        )
        return EDIT_FIELD

    await query.edit_message_text("Неизвестное поле.", reply_markup=edit_field_keyboard())
    return EDIT_FIELD


async def edit_tasks_mode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("edittasks:", "")
    if mode not in {"replace", "append"}:
        await query.edit_message_text("Неизвестное действие.", reply_markup=edit_field_keyboard())
        return EDIT_FIELD

    context.user_data["edit_field"] = "tasks"
    context.user_data["edit_mode"] = mode

    report_data = context.user_data.get("edit_report_data") or {}
    current_tasks = report_data.get("Задачи", "") or "—"

    if mode == "replace":
        text = (
            "Текущие задачи:\n"
            f"{current_tasks}\n\n"
            "Введите новый текст задач. Старый текст будет заменен полностью:"
        )
    else:
        text = (
            "Текущие задачи:\n"
            f"{current_tasks}\n\n"
            "Введите текст, который нужно добавить к текущим задачам:"
        )

    await query.edit_message_text(text, reply_markup=payroll_back_keyboard())
    return EDIT_VALUE


def add_or_replace_kpi_item(kpi_items, new_item):
    for item in kpi_items:
        if item.get("kpi_id") == new_item.get("kpi_id"):
            item["name"] = new_item["name"]
            item["rate"] = new_item["rate"]
            item["qty"] = new_item["qty"]
            item["sum"] = new_item["sum"]
            return kpi_items

    kpi_items.append(new_item)
    return kpi_items


async def edit_kpi_mode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("editkpi:", "")
    if mode not in {"replace", "append"}:
        await query.edit_message_text("Неизвестное действие.", reply_markup=edit_field_keyboard())
        return EDIT_FIELD

    report_data = context.user_data.get("edit_report_data") or {}
    old_kpi_items = kpi_from_json(report_data.get("KPI данные", ""))

    context.user_data["edit_kpi_mode"] = mode

    if mode == "replace":
        context.user_data["edit_new_kpi_items"] = []
        text = (
            "Текущий KPI:\n"
            f"{format_kpi_lines(old_kpi_items)}\n\n"
            "Выберите KPI заново. Старый KPI-блок будет заменен полностью.\n"
            "Когда закончите, нажмите «Завершить KPI»."
        )
    else:
        context.user_data["edit_new_kpi_items"] = [dict(item) for item in old_kpi_items]
        text = (
            "Текущий KPI:\n"
            f"{format_kpi_lines(old_kpi_items)}\n\n"
            "Выберите KPI, который нужно добавить или изменить.\n"
            "Если выбранный KPI уже есть в отчете, новое количество заменит старое по этой категории.\n"
            "Когда закончите, нажмите «Завершить KPI»."
        )

    await query.edit_message_text(text, reply_markup=kpi_keyboard("edkpi"))
    return EDIT_KPI_SELECT


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
        mode = context.user_data.get("edit_mode", "replace")
        old_tasks = str(report_data.get("Задачи", "") or "").strip()

        if mode == "append" and old_tasks:
            report_data["Задачи"] = f"{old_tasks}\n{value}"
        else:
            report_data["Задачи"] = value

        context.user_data.pop("edit_mode", None)
    else:
        await update.message.reply_text("Неизвестное поле.")
        return EDIT_FIELD

    report_data["Обновлено"] = now_str()
    context.user_data["edit_report_data"] = report_data

    model_preview = report_data_to_model(report_data)

    await update.message.reply_text(
        "Изменение принято. Текущая версия отчета:\n\n"
        f"{format_daily_report_text(model_preview)}\n\n"
        "Выберите ещё поле или нажмите «Завершить изменение».",
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
        context.user_data.pop("edit_kpi_mode", None)
        context.user_data.pop("selected_kpi", None)

        model_preview = report_data_to_model(report_data)

        await query.edit_message_text(
            "KPI обновлен. Текущая версия отчета:\n\n"
            f"{format_daily_report_text(model_preview)}\n\n"
            "Выберите ещё поле или нажмите «Завершить изменение».",
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

    new_item = {
        "kpi_id": selected["kpi_id"],
        "name": selected["name"],
        "rate": selected["rate"],
        "qty": qty,
        "sum": qty * selected["rate"],
    }

    kpi_items = context.user_data.setdefault("edit_new_kpi_items", [])
    context.user_data["edit_new_kpi_items"] = add_or_replace_kpi_item(kpi_items, new_item)
    context.user_data.pop("selected_kpi", None)

    await update.message.reply_text(
        "KPI добавлен/обновлен. Текущий KPI:\n"
        f"{format_kpi_lines(context.user_data['edit_new_kpi_items'])}\n\n"
        "Выберите ещё KPI или нажмите «Завершить KPI»: ",
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
    await update.message.reply_text("Выберите тип штрафа:", reply_markup=penalty_type_group_keyboard())
    return PENALTY_TYPE_GROUP


async def penalty_type_group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "pngrp:back":
        await query.edit_message_text("Выберите тип штрафа:", reply_markup=penalty_type_group_keyboard())
        return PENALTY_TYPE_GROUP

    if data.startswith("pngrp:"):
        group_id = data.replace("pngrp:", "")
        group = PENALTY_TYPE_GROUPS.get(group_id)
        if not group:
            await query.edit_message_text("Группа штрафов не найдена.", reply_markup=penalty_type_group_keyboard())
            return PENALTY_TYPE_GROUP

        await query.edit_message_text(
            f"Тип штрафа: {group['name']}\n\nВыберите конкретный вариант:",
            reply_markup=penalty_type_keyboard(group_id),
        )
        return PENALTY_TYPE

    if data.startswith("pntype:"):
        return await penalty_type_selected(update, context)

    await query.edit_message_text("Выберите тип штрафа:", reply_markup=penalty_type_group_keyboard())
    return PENALTY_TYPE_GROUP


async def penalty_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "pngrp:back":
        await query.edit_message_text("Выберите тип штрафа:", reply_markup=penalty_type_group_keyboard())
        return PENALTY_TYPE_GROUP

    penalty_type_id = data.replace("pntype:", "")
    penalty_type = PENALTY_TYPES.get(penalty_type_id)

    if not penalty_type:
        await query.edit_message_text("Тип штрафа не найден. Выберите заново:", reply_markup=penalty_type_group_keyboard())
        return PENALTY_TYPE_GROUP

    context.user_data["penalty_type_id"] = penalty_type_id
    context.user_data["penalty_category"] = penalty_type.get("category", "Другое")
    context.user_data["penalty_type_name"] = penalty_type["name"]
    context.user_data["penalty_manual_amount"] = bool(penalty_type.get("manual_amount"))

    if not penalty_type.get("manual_amount"):
        context.user_data["penalty_amount"] = safe_float(penalty_type.get("amount"))
    else:
        context.user_data.pop("penalty_amount", None)

    await query.edit_message_text(
        f"Тип штрафа: {penalty_type['name']}\n\nВведите комментарий с деталями штрафа:",
        reply_markup=payroll_back_keyboard(),
    )
    return PENALTY_COMMENT


async def penalty_comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()
    if not comment:
        await update.message.reply_text("Комментарий не должен быть пустым. Введите комментарий:")
        return PENALTY_COMMENT

    context.user_data["penalty_comment"] = comment

    if context.user_data.get("penalty_manual_amount"):
        await update.message.reply_text("Введите сумму штрафа:", reply_markup=payroll_back_keyboard())
        return PENALTY_AMOUNT

    employee = get_employee_by_id(context.user_data.get("employee_id"))
    await update.message.reply_text(
        format_penalty_preview(
            employee=employee,
            penalty_date=context.user_data["penalty_date"],
            penalty_category=context.user_data["penalty_category"],
            penalty_type=context.user_data["penalty_type_name"],
            comment=context.user_data["penalty_comment"],
            amount=context.user_data["penalty_amount"],
        ),
        reply_markup=penalty_confirm_keyboard(),
    )
    return PENALTY_CONFIRM


async def penalty_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_positive_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("Введите сумму числом больше 0:")
        return PENALTY_AMOUNT

    context.user_data["penalty_amount"] = amount
    employee = get_employee_by_id(context.user_data.get("employee_id"))

    await update.message.reply_text(
        format_penalty_preview(
            employee=employee,
            penalty_date=context.user_data["penalty_date"],
            penalty_category=context.user_data["penalty_category"],
            penalty_type=context.user_data["penalty_type_name"],
            comment=context.user_data["penalty_comment"],
            amount=context.user_data["penalty_amount"],
        ),
        reply_markup=penalty_confirm_keyboard(),
    )
    return PENALTY_CONFIRM


async def penalty_confirm_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    employee = get_employee_by_id(context.user_data.get("employee_id"))
    current_employee = current_employee_or_none(update)
    created_by = current_employee["full_name"] if current_employee else str(update.effective_user.id)
    penalty_date = context.user_data["penalty_date"]
    penalty_category = context.user_data["penalty_category"]
    penalty_type_id = context.user_data.get("penalty_type_id")
    penalty_type = context.user_data["penalty_type_name"]
    penalty_comment = context.user_data["penalty_comment"]
    amount = context.user_data["penalty_amount"]

    append_penalty(
        employee,
        penalty_date,
        penalty_category,
        penalty_type,
        penalty_comment,
        amount,
        created_by,
    )

    try:
        topic_status = await send_penalty_to_topic(
            context=context,
            employee=employee,
            penalty_date=penalty_date,
            penalty_category=penalty_category,
            penalty_type=penalty_type,
            comment=penalty_comment,
            amount=amount,
            created_by=created_by,
        )
    except Exception as error:
        logging.exception("Не удалось отправить штраф в тему Telegram")
        topic_status = f"Штраф записан в таблицу, но не отправлен в тему ⚠️\nОшибка: {error}"

    auto_status = None
    if penalty_type_id == PENALTY_ABSENCE_NO_REASON_TYPE_ID:
        auto_status = await maybe_send_third_absence_notice(
            context=context,
            employee=employee,
            penalty_date=penalty_date,
            created_by=created_by,
        )

    extra_status = f"\n\n{auto_status}" if auto_status else ""

    await query.edit_message_text(
        "Штраф добавлен ✅\n\n"
        f"Сотрудник: {employee['full_name']}\n"
        f"Дата: {penalty_date}\n"
        f"Категория: {penalty_category}\n"
        f"Тип штрафа: {penalty_type}\n"
        f"Комментарий: {penalty_comment}\n"
        f"Сумма: {money(amount)}\n\n"
        f"{topic_status}{extra_status}",
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
                CallbackQueryHandler(edit_tasks_mode_selected, pattern=r"^edittasks:"),
                CallbackQueryHandler(edit_kpi_mode_selected, pattern=r"^editkpi:"),
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
            PENALTY_TYPE_GROUP: [
                CallbackQueryHandler(penalty_type_group_selected, pattern=r"^(pngrp|pntype):"),
                CallbackQueryHandler(payroll_cancel, pattern=r"^pay:cancel$"),
            ],
            PENALTY_TYPE: [
                CallbackQueryHandler(penalty_type_selected, pattern=r"^(pntype|pngrp):"),
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
            PENALTY_CONFIRM: [
                CallbackQueryHandler(penalty_confirm_received, pattern=r"^penalty:confirm$"),
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
