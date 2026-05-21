import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import GROUP_CHAT_ID, RECEIVING_REPORT_TOPIC_ID
from google_sheets import build_receiving_report_text
from keyboards import build_receiving_menu_keyboard, build_report_date_keyboard


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

    try:
        report_text = build_receiving_report_text(report_date)
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
    except Exception as error:
        logging.exception("Не удалось отправить отчет в тему")
        send_status = f"Не удалось отправить отчет в тему ⚠️\nОшибка: {error}"

    await query.edit_message_text(
        f"{report_text}\n\n{send_status}",
        reply_markup=build_receiving_menu_keyboard(),
    )


def get_report_handlers():
    return [
        CallbackQueryHandler(report_choose_date, pattern=r"^report:choose_date$"),
        CallbackQueryHandler(report_date_selected, pattern=r"^report:date:"),
    ]
