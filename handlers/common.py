import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from modules.receiving.postgres_storage import get_last_records_text, get_receiving_db_status
from core.keyboards import (
    build_main_menu_keyboard,
    build_receiving_menu_keyboard,
    build_receiving_report_type_keyboard,
    build_returns_menu_keyboard,
    build_start_keyboard,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

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
        reply_markup=build_receiving_report_type_keyboard(),
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
        text = get_last_records_text(limit=10)
    except Exception as error:
        logging.exception("Ошибка чтения последних записей из PostgreSQL")
        text = (
            "Не удалось загрузить последние записи из PostgreSQL ⚠️\n\n"
            f"Ошибка: {error}"
        )

    await query.edit_message_text(
        text,
        reply_markup=build_receiving_menu_keyboard(),
    )


async def last_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = get_last_records_text(limit=10)
    except Exception as error:
        logging.exception("Ошибка чтения последних записей из PostgreSQL")
        text = (
            "Не удалось загрузить последние записи из PostgreSQL ⚠️\n\n"
            f"Ошибка: {error}"
        )

    await update.message.reply_text(
        text,
        reply_markup=build_receiving_menu_keyboard(),
    )


async def db_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        version, columns = get_receiving_db_status()

        await update.message.reply_text(
            "PostgreSQL работает ✅\n\n"
            f"{version}\n\n"
            "Колонки в incoming_goods:\n"
            + "\n".join(columns)
        )
    except Exception as error:
        logging.exception("PostgreSQL status check failed")
        await update.message.reply_text(f"❌ PostgreSQL ошибка:\n{error}")


async def whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message

    text = (
        f"chat_id: {chat.id}\n"
        f"message_thread_id: {message.message_thread_id}"
    )

    await update.message.reply_text(text)
