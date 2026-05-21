import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from database import get_table_columns, reset_local_db_with_backup
from google_sheets import (
    append_google_status_test_row,
    get_google_worksheet,
    get_last_records_text_from_google,
)
from keyboards import (
    build_main_menu_keyboard,
    build_receiving_menu_keyboard,
    build_returns_menu_keyboard,
    build_start_keyboard,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Нажмите кнопку ниже, чтобы открыть меню бота.",
        reply_markup=build_start_keyboard(),
    )


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "Выберите раздел:",
        reply_markup=build_main_menu_keyboard(),
    )

    return ConversationHandler.END


async def show_receiving_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "📦 Отчет оприходований:",
        reply_markup=build_receiving_menu_keyboard(),
    )

    return ConversationHandler.END


async def show_returns_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "↩️ Возвраты:",
        reply_markup=build_returns_menu_keyboard(),
    )

    return ConversationHandler.END


async def send_main_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text="Выберите раздел:"):
    context.user_data.clear()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text,
            reply_markup=build_main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=build_main_menu_keyboard(),
        )

    return ConversationHandler.END


async def menu_last_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        text = get_last_records_text_from_google(limit=10)
    except Exception as error:
        logging.exception("Ошибка чтения последних записей из Google Sheets")
        text = (
            "Не удалось загрузить последние записи из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}"
        )

    await query.edit_message_text(
        text,
        reply_markup=build_receiving_menu_keyboard(),
    )


async def last_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = get_last_records_text_from_google(limit=10)
    except Exception as error:
        logging.exception("Ошибка чтения последних записей из Google Sheets")
        text = (
            "Не удалось загрузить последние записи из Google Таблицы ⚠️\n\n"
            f"Ошибка: {error}"
        )

    await update.message.reply_text(
        text,
        reply_markup=build_receiving_menu_keyboard(),
    )


async def google_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        get_google_worksheet()
        append_google_status_test_row()

        await update.message.reply_text(
            "✅ Google Sheets работает. Тестовая строка добавлена в таблицу."
        )
    except Exception as error:
        logging.exception("Google Sheets status check failed")
        await update.message.reply_text(f"❌ Google Sheets не работает:\n{error}")


async def sqlite_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        columns = sorted(get_table_columns("incoming_goods"))

        await update.message.reply_text(
            "SQLite работает. Колонки в incoming_goods:\n" + "\n".join(columns)
        )
    except Exception as error:
        logging.exception("SQLite status check failed")
        await update.message.reply_text(f"❌ SQLite ошибка:\n{error}")


async def reset_local_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        backup_file = reset_local_db_with_backup()

        if backup_file:
            text = (
                "✅ Локальная SQLite-база пересоздана.\n"
                f"Старая база сохранена как: {backup_file.name}"
            )
        else:
            text = "✅ Локальная SQLite-база создана."

        await update.message.reply_text(text)
    except Exception as error:
        logging.exception("SQLite reset failed")
        await update.message.reply_text(f"❌ Не удалось пересоздать SQLite-базу:\n{error}")


async def whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message

    text = (
        f"chat_id: {chat.id}\n"
        f"message_thread_id: {message.message_thread_id}"
    )

    await update.message.reply_text(text)
