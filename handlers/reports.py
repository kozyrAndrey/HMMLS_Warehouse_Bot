import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import GROUP_CHAT_ID, RECEIVING_REPORT_TOPIC_ID
from google_sheets import (
    build_receiving_report_text,
    delete_unexported_receiving_record,
    get_receiving_record_by_row,
    get_unexported_receiving_records,
    has_unexported_receiving_records_for_date,
    mark_receiving_rows_exported,
)
from keyboards import build_receiving_menu_keyboard, build_report_date_keyboard


def user_display_name(user):
    if user.username:
        return f"{user.full_name} (@{user.username})"

    return user.full_name


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


async def send_report_to_topic(context: ContextTypes.DEFAULT_TYPE, report_text):
    if not GROUP_CHAT_ID:
        return "Тема отчета не настроена: GROUP_CHAT_ID пустой."

    if not RECEIVING_REPORT_TOPIC_ID:
        return "Тема отчета не настроена: RECEIVING_REPORT_TOPIC_ID пустой."

    chat_id = int(GROUP_CHAT_ID)
    message_thread_id = int(RECEIVING_REPORT_TOPIC_ID)

    chunks = split_long_message(report_text)

    for chunk in chunks:
        await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            text=chunk,
        )

    return "Отчет отправлен в тему «Отчет приемки» ✅"


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
        send_status = await send_report_to_topic(context, report_text)
        marked_count = mark_receiving_rows_exported(report_date, exported_by)
        send_status += f"\nВыгруженных строк отмечено в таблице: {marked_count}"
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


def record_button_text(record):
    return (
        f"{shorten_text(record['username'], 14)} | "
        f"{shorten_text(record['product_name'], 24)} | "
        f"{record['size']} | "
        f"У:{record['packed']} Б:{record['defective']} Д:{record['rework']}"
    )


def format_record_details(record):
    return (
        f"Дата: {record['date']}\n"
        f"Пользователь: {record['username']}\n"
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


def get_report_handlers():
    return [
        CallbackQueryHandler(report_choose_date, pattern=r"^report:choose_date$"),
        CallbackQueryHandler(report_date_selected, pattern=r"^report:date:"),
        CallbackQueryHandler(receiving_delete_choose, pattern=r"^recvdel:choose$"),
        CallbackQueryHandler(receiving_delete_confirm, pattern=r"^recvdel:confirm:\d+$"),
        CallbackQueryHandler(receiving_delete_do, pattern=r"^recvdel:do:\d+$"),
        CallbackQueryHandler(receiving_delete_cancel, pattern=r"^recvdel:cancel$"),
    ]
