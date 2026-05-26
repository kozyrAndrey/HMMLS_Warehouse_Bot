import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import GROUP_CHAT_ID, RECEIVING_REPORT_TOPIC_ID
from modules.receiving.google_sheets import (
    build_receiving_report_text,
    delete_unexported_receiving_record,
    get_exported_receiving_report_by_export_id,
    get_exported_receiving_report_groups,
    get_receiving_record_by_row,
    get_unexported_receiving_records,
    has_unexported_receiving_records_for_date,
    mark_receiving_rows_exported,
    unmark_receiving_rows_by_export_id,
)
from core.keyboards import build_receiving_menu_keyboard, build_report_date_keyboard


# Локальный fallback-справочник ФИО.
# Нужен, чтобы отчеты читались нормально даже если Google-таблица ЗП
# временно недоступна или лист «Сотрудники» еще не синхронизирован.
LOCAL_EMPLOYEE_NAMES_BY_USER_ID = {
    "413489632": "Андрей Козырь",
    "927075259": "Дмитрий Тарасов",
    "1152528155": "Константин Рогов",
    "597723397": "Егор Репин",
    "272117327": "Никита Комаричев",
    "854197803": "Лев Грунверг",
    "5223200693": "Файсал Сабер",
}

LOCAL_EMPLOYEE_NAMES_BY_USERNAME = {
    "opulent_shooter": "Андрей Козырь",
    "adafagahajakal": "Дмитрий Тарасов",
    "kstyaaaa": "Константин Рогов",
    "whereareyo0o": "Егор Репин",
    "rokiothegoat": "Никита Комаричев",
    "fadexdf": "Лев Грунверг",
    "hamza_sam": "Файсал Сабер",
}


def normalize_username_local(username):
    return str(username or "").strip().lstrip("@").lower()


def employee_name_from_user_id_or_username(user_id=None, username=None, fallback=None):
    user_id = str(user_id or "").strip()
    username = normalize_username_local(username)

    if user_id and user_id in LOCAL_EMPLOYEE_NAMES_BY_USER_ID:
        return LOCAL_EMPLOYEE_NAMES_BY_USER_ID[user_id]

    if username and username in LOCAL_EMPLOYEE_NAMES_BY_USERNAME:
        return LOCAL_EMPLOYEE_NAMES_BY_USERNAME[username]

    return fallback or username or user_id or "Неизвестный сотрудник"


# ============================================================
# ФИО СОТРУДНИКА
# ============================================================

def get_employee_full_name_for_user(user):
    """Возвращает ФИО сотрудника из модуля ЗП по Telegram user_id/username.

    Порядок поиска:
    1. Локальный справочник по user_id/username.
    2. Google-таблица ЗП, лист «Сотрудники».
    3. payroll_config.py.
    4. Telegram full_name / username.
    """
    local_name = employee_name_from_user_id_or_username(
        user_id=user.id,
        username=user.username,
        fallback=None,
    )
    if local_name and local_name != "Неизвестный сотрудник":
        return local_name

    try:
        from modules.payroll.google_sheets import find_employee_for_telegram_user

        employee = find_employee_for_telegram_user(user)
        if employee and employee.get("full_name"):
            return employee["full_name"]
    except Exception:
        logging.exception("Не удалось получить ФИО сотрудника из Google Таблицы ЗП")

    try:
        from payroll_config import PAYROLL_EMPLOYEES, normalize_username

        telegram_user_id = str(user.id)
        username = normalize_username(user.username)

        for employee in PAYROLL_EMPLOYEES:
            if str(employee.get("telegram_user_id", "")).strip() == telegram_user_id:
                return employee.get("full_name") or user.full_name

        if username:
            for employee in PAYROLL_EMPLOYEES:
                if normalize_username(employee.get("telegram_username", "")) == username:
                    return employee.get("full_name") or user.full_name
    except Exception:
        logging.exception("Не удалось получить ФИО сотрудника из payroll_config.py")

    return user.full_name or user.username or str(user.id)


def user_display_name(user):
    return get_employee_full_name_for_user(user)


# ============================================================
# ВЫГРУЗКА ОТЧЕТА ОПРИХОДОВАНИЙ
# ============================================================

async def report_choose_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Выберите дату для выгрузки отчета:",
        reply_markup=build_report_date_keyboard(),
    )


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


def make_export_id(report_date):
    date_part = report_date.replace(".", "")
    time_part = datetime.now().strftime("%H%M%S")
    return f"recv{date_part}{time_part}"


async def send_report_to_topic(context: ContextTypes.DEFAULT_TYPE, report_text):
    if not GROUP_CHAT_ID:
        raise RuntimeError("Тема отчета не настроена: GROUP_CHAT_ID пустой.")

    if not RECEIVING_REPORT_TOPIC_ID:
        raise RuntimeError("Тема отчета не настроена: RECEIVING_REPORT_TOPIC_ID пустой.")

    chat_id = int(GROUP_CHAT_ID)
    message_thread_id = int(RECEIVING_REPORT_TOPIC_ID)

    chunks = split_long_message(report_text)
    message_ids = []

    for chunk in chunks:
        message = await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            text=chunk,
        )
        message_ids.append(message.message_id)

    return {
        "chat_id": chat_id,
        "thread_id": message_thread_id,
        "message_ids": message_ids,
        "status": "Отчет отправлен в тему «Отчет приемки» ✅",
    }


async def report_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    report_date = query.data.replace("report:date:", "")
    exported_by = user_display_name(query.from_user)

    try:
        has_records = has_unexported_receiving_records_for_date(report_date)
    except Exception as error:
        logging.exception("Не удалось проверить невыгруженные записи")
        await query.edit_message_text(
            "Не удалось проверить записи в Google Таблице ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not has_records:
        await query.edit_message_text(
            f"Дата: {report_date}\n"
            f"Выгрузил: {exported_by}\n\n"
            "Нет невыгруженных записей за эту дату.\n\n"
            "Если запись уже была выгружена в тему, она не попадает в повторную выгрузку.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    try:
        report_text = build_receiving_report_text(
            report_date=report_date,
            exported_by=exported_by,
            only_unexported=True,
        )
    except Exception as error:
        logging.exception("Не удалось собрать отчет оприходований")
        await query.edit_message_text(
            "Не удалось собрать отчет из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    try:
        export_info = await send_report_to_topic(context, report_text)
        export_id = make_export_id(report_date)

        marked_count = mark_receiving_rows_exported(
            report_date=report_date,
            exported_by=exported_by,
            export_id=export_id,
            chat_id=export_info["chat_id"],
            thread_id=export_info["thread_id"],
            message_ids=export_info["message_ids"],
        )

        send_status = (
            f"{export_info['status']}\n"
            f"ID выгрузки: {export_id}\n"
            f"Выгруженных строк отмечено в таблице: {marked_count}"
        )
    except Exception as error:
        logging.exception("Не удалось отправить отчет в тему или отметить строки")
        send_status = f"Не удалось отправить отчет в тему / отметить строки ⚠️\nОшибка: {error}"

    await query.edit_message_text(
        f"{report_text}\n\n{send_status}",
        reply_markup=build_receiving_menu_keyboard(),
    )


# ============================================================
# УДАЛЕНИЕ НЕВЫГРУЖЕННЫХ ЗАПИСЕЙ ОПРИХОДОВАНИЯ
# ============================================================

def shorten_text(text, max_len=32):
    text = str(text)

    if len(text) <= max_len:
        return text

    return text[: max_len - 1] + "…"


def record_employee_display_name(record):
    return employee_name_from_user_id_or_username(
        user_id=record.get("user_id"),
        username=record.get("username"),
        fallback=record.get("username") or record.get("user_id") or "",
    )


def record_button_text(record):
    return (
        f"{shorten_text(record_employee_display_name(record), 18)} | "
        f"{shorten_text(record['product_name'], 24)} | "
        f"{record['size']} | "
        f"У:{record['packed']} Б:{record['defective']} Д:{record['rework']}"
    )


def format_record_details(record):
    return (
        f"Дата: {record['date']}\n"
        f"Сотрудник: {record_employee_display_name(record)}\n"
        f"Группа: {record['category_name']}\n"
        f"Модель: {record['product_name']}\n"
        f"Размер: {record['size']}\n"
        f"Упаковано: {record['packed']}\n"
        f"Брак: {record['defective']}\n"
        f"Доработка: {record['rework']}"
    )


def build_delete_records_keyboard(records):
    keyboard = []

    for record in records:
        keyboard.append(
            [
                InlineKeyboardButton(
                    record_button_text(record),
                    callback_data=f"recvdel:confirm:{record['row_number']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="section:receiving")])

    return InlineKeyboardMarkup(keyboard)


def build_confirm_delete_keyboard(row_number):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Удалить", callback_data=f"recvdel:do:{row_number}"),
                InlineKeyboardButton("❌ Отмена", callback_data="recvdel:cancel"),
            ]
        ]
    )


async def receiving_delete_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        records = get_unexported_receiving_records(limit=15)
    except Exception as error:
        logging.exception("Не удалось получить невыгруженные записи")
        await query.edit_message_text(
            "Не удалось получить невыгруженные записи из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not records:
        await query.edit_message_text(
            "Нет невыгруженных записей, которые можно удалить.\n\n"
            "Записи, которые уже были выгружены в тему Telegram, не показываются и не удаляются.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    await query.edit_message_text(
        "Выберите запись для удаления.\n\n"
        "Показываются только последние 15 записей, которые еще НЕ были выгружены в тему Telegram:",
        reply_markup=build_delete_records_keyboard(records),
    )


async def receiving_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    row_number = int(query.data.replace("recvdel:confirm:", ""))

    try:
        record = get_receiving_record_by_row(row_number)
    except Exception as error:
        logging.exception("Не удалось прочитать запись для удаления")
        await query.edit_message_text(
            "Не удалось прочитать запись из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not record:
        await query.edit_message_text(
            "Запись не найдена. Возможно, она уже была удалена.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if record["exported"]:
        await query.edit_message_text(
            "Эта запись уже выгружена в отчет, поэтому удалить её через бота нельзя.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    context.user_data["receiving_delete_row_number"] = row_number

    await query.edit_message_text(
        "Проверьте запись перед удалением:\n\n"
        f"{format_record_details(record)}\n\n"
        "Удалить эту запись из Google Таблицы?",
        reply_markup=build_confirm_delete_keyboard(row_number),
    )


async def receiving_delete_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    row_number = int(query.data.replace("recvdel:do:", ""))

    try:
        deleted_record = delete_unexported_receiving_record(row_number)
    except Exception as error:
        logging.exception("Не удалось удалить запись")
        await query.edit_message_text(
            "Не удалось удалить запись ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    context.user_data.pop("receiving_delete_row_number", None)

    await query.edit_message_text(
        "Запись удалена ✅\n\n"
        f"{format_record_details(deleted_record)}",
        reply_markup=build_receiving_menu_keyboard(),
    )


async def receiving_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("receiving_delete_row_number", None)

    await query.edit_message_text(
        "Удаление отменено.",
        reply_markup=build_receiving_menu_keyboard(),
    )


# ============================================================
# УДАЛЕНИЕ ВЫГРУЖЕННОГО ОТЧЕТА ИЗ ТЕМЫ TELEGRAM
# ============================================================

def report_group_button_text(group):
    return (
        f"{group['date']} | "
        f"{shorten_text(group['exported_by'], 16)} | "
        f"строк: {group['row_count']} | "
        f"общее: {group['total']}"
    )


def format_report_group_details(group):
    message_ids = ", ".join(str(message_id) for message_id in group["message_ids"])

    return (
        f"Дата: {group['date']}\n"
        f"Выгрузил: {group['exported_by']}\n"
        f"Дата выгрузки: {group['exported_at']}\n"
        f"ID выгрузки: {group['export_id']}\n"
        f"Количество строк: {group['row_count']}\n"
        f"Упаковано: {group['total_packed']}\n"
        f"Брак: {group['total_defective']}\n"
        f"Доработка: {group['total_rework']}\n"
        f"Общее: {group['total']}\n"
        f"Message IDs: {message_ids}"
    )


def build_report_groups_keyboard(groups):
    keyboard = []

    for group in groups:
        keyboard.append(
            [
                InlineKeyboardButton(
                    report_group_button_text(group),
                    callback_data=f"recvrepdel:confirm:{group['export_id']}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="section:receiving")])

    return InlineKeyboardMarkup(keyboard)


def build_confirm_report_delete_keyboard(export_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Удалить отчет", callback_data=f"recvrepdel:do:{export_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="recvrepdel:cancel"),
            ]
        ]
    )


async def receiving_report_delete_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        groups = get_exported_receiving_report_groups(limit=10)
    except Exception as error:
        logging.exception("Не удалось получить выгруженные отчеты")
        await query.edit_message_text(
            "Не удалось получить выгруженные отчеты из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not groups:
        await query.edit_message_text(
            "Нет отчетов, которые можно удалить из темы.\n\n"
            "Важно: удалить можно только отчеты, выгруженные после обновления, "
            "потому что для старых выгрузок бот не знает Telegram message_id.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    await query.edit_message_text(
        "Выберите отчет, который нужно удалить из темы Telegram.\n\n"
        "После удаления записи снова станут невыгруженными, их можно будет исправить и выгрузить заново:",
        reply_markup=build_report_groups_keyboard(groups),
    )


async def receiving_report_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    export_id = query.data.replace("recvrepdel:confirm:", "")

    try:
        group = get_exported_receiving_report_by_export_id(export_id)
    except Exception as error:
        logging.exception("Не удалось получить отчет для удаления")
        await query.edit_message_text(
            "Не удалось получить отчет из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not group:
        await query.edit_message_text(
            "Отчет не найден. Возможно, он уже был удален или выгрузка старая.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    context.user_data["receiving_report_delete_export_id"] = export_id

    await query.edit_message_text(
        "Проверьте отчет перед удалением:\n\n"
        f"{format_report_group_details(group)}\n\n"
        "Что произойдет после подтверждения:\n"
        "1. Бот удалит сообщение/сообщения отчета из темы Telegram.\n"
        "2. Записи в Google Таблице снова станут невыгруженными.\n"
        "3. Их можно будет исправить и выгрузить заново.\n\n"
        "Удалить этот отчет?",
        reply_markup=build_confirm_report_delete_keyboard(export_id),
    )


async def receiving_report_delete_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    export_id = query.data.replace("recvrepdel:do:", "")

    try:
        group = get_exported_receiving_report_by_export_id(export_id)
    except Exception as error:
        logging.exception("Не удалось получить отчет для удаления")
        await query.edit_message_text(
            "Не удалось получить отчет из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    if not group:
        await query.edit_message_text(
            "Отчет не найден. Возможно, он уже был удален.",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    deleted_messages = 0
    delete_errors = []

    for message_id in group["message_ids"]:
        try:
            await context.bot.delete_message(
                chat_id=int(group["chat_id"]),
                message_id=int(message_id),
            )
            deleted_messages += 1
        except Exception as error:
            logging.exception("Не удалось удалить сообщение отчета из Telegram")
            delete_errors.append(f"message_id {message_id}: {error}")

    try:
        unmarked_rows = unmark_receiving_rows_by_export_id(export_id)
    except Exception as error:
        logging.exception("Не удалось снять отметку выгрузки с записей")
        await query.edit_message_text(
            "Сообщения в Telegram частично удалены, но не удалось снять отметку выгрузки в Google Таблице ⚠️\n\n"
            f"Ошибка: {error}",
            reply_markup=build_receiving_menu_keyboard(),
        )
        return

    context.user_data.pop("receiving_report_delete_export_id", None)

    text = (
        "Отчет удален из темы ✅\n\n"
        f"ID выгрузки: {export_id}\n"
        f"Удалено сообщений Telegram: {deleted_messages}\n"
        f"Записей снова сделано невыгруженными: {unmarked_rows}\n\n"
        "Теперь можно удалить/исправить нужные записи и выгрузить отчет заново."
    )

    if delete_errors:
        text += (
            "\n\nНекоторые сообщения удалить не удалось ⚠️\n"
            + "\n".join(delete_errors[:5])
        )

    await query.edit_message_text(
        text,
        reply_markup=build_receiving_menu_keyboard(),
    )


async def receiving_report_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.pop("receiving_report_delete_export_id", None)

    await query.edit_message_text(
        "Удаление отчета отменено.",
        reply_markup=build_receiving_menu_keyboard(),
    )


# ============================================================
# HANDLERS
# ============================================================

def get_report_handlers():
    return [
        CallbackQueryHandler(report_choose_date, pattern=r"^report:choose_date$"),
        CallbackQueryHandler(report_date_selected, pattern=r"^report:date:"),
        CallbackQueryHandler(receiving_delete_choose, pattern=r"^recvdel:choose$"),
        CallbackQueryHandler(receiving_delete_confirm, pattern=r"^recvdel:confirm:\d+$"),
        CallbackQueryHandler(receiving_delete_do, pattern=r"^recvdel:do:\d+$"),
        CallbackQueryHandler(receiving_delete_cancel, pattern=r"^recvdel:cancel$"),
        CallbackQueryHandler(receiving_report_delete_choose, pattern=r"^recvrepdel:choose$"),
        CallbackQueryHandler(receiving_report_delete_confirm, pattern=r"^recvrepdel:confirm:"),
        CallbackQueryHandler(receiving_report_delete_do, pattern=r"^recvrepdel:do:"),
        CallbackQueryHandler(receiving_report_delete_cancel, pattern=r"^recvrepdel:cancel$"),
    ]
