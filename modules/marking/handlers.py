import logging
import os
import tempfile
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from core.keyboards import build_marking_menu_keyboard
from modules.marking.duplicate_chz import DuplicateChzError, create_duplicate_chz_pdf
from modules.marking.export import (
    build_moysklad_client,
    create_trend_island_codes_xlsx,
    get_retireorder_export_rows,
)
from modules.marking.moysklad_lookup import find_marking_product_info
from modules.moysklad.client import MoySkladError
from modules.payroll.google_sheets import find_employee_for_telegram_user, is_manager


MARKING_DOCUMENT_NAME = 1400
MARKING_DUPLICATE_CHZ_CODE = 1401


def marking_cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="marking:cancel")],
    ])


def ensure_manager(update: Update):
    employee = find_employee_for_telegram_user(update.effective_user)
    return is_manager(employee)


def marking_menu_keyboard(update: Update):
    return build_marking_menu_keyboard(manager=ensure_manager(update))


async def trend_export_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not ensure_manager(update):
        await query.edit_message_text(
            "⛔️ Выгрузка доступна только руководителям.",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "Введите название документа «Вывод из оборота», откуда сделать выгрузку кодов:",
        reply_markup=marking_cancel_keyboard(),
    )
    return MARKING_DOCUMENT_NAME


async def trend_export_document_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ensure_manager(update):
        await update.message.reply_text(
            "⛔️ Выгрузка доступна только руководителям.",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END

    document_name = (update.message.text or "").strip()
    if not document_name:
        await update.message.reply_text(
            "Введите непустое название документа.",
            reply_markup=marking_cancel_keyboard(),
        )
        return MARKING_DOCUMENT_NAME

    status_message = await update.message.reply_text("Готовлю выгрузку кодов маркировки...")

    try:
        client = build_moysklad_client()
        document, rows = get_retireorder_export_rows(client, document_name)
    except MoySkladError as error:
        await status_message.edit_text(
            f"Не удалось сформировать выгрузку:\n{error}",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END
    except Exception as error:
        logging.exception("Ошибка выгрузки кодов маркировки")
        await status_message.edit_text(
            f"Не удалось сформировать выгрузку:\n{error}",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END

    if not rows:
        await status_message.edit_text(
            "В документе не найдено позиций для выгрузки.",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        path = create_trend_island_codes_xlsx(rows, tmp.name)

    total_codes = sum(len(item["codes"]) for item in rows)
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in document_name)
    filename = f"trend_island_codes_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    try:
        with open(path, "rb") as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                filename=filename,
                caption=(
                    f"Выгрузка кодов для Trend Island\n"
                    f"Документ: {document.get('name')}\n"
                    f"Позиций: {len(rows)}\n"
                    f"Кодов: {total_codes}"
                ),
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            logging.exception("Не удалось удалить временный файл выгрузки маркировки")

    await status_message.edit_text(
        "Выгрузка сформирована ✅",
        reply_markup=marking_menu_keyboard(update),
    )
    return ConversationHandler.END


async def duplicate_chz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Пришлите полный код ЧЗ текстом.\n\n"
        "Если в коде есть разделитель GS, можно вставить его как <GS> или \\x1d.",
        reply_markup=marking_cancel_keyboard(),
    )
    return MARKING_DUPLICATE_CHZ_CODE


async def duplicate_chz_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_code = (update.message.text or "").strip()
    if not raw_code:
        await update.message.reply_text("Пришлите непустой полный код ЧЗ.", reply_markup=marking_cancel_keyboard())
        return MARKING_DUPLICATE_CHZ_CODE

    status_message = await update.message.reply_text("Готовлю дубликат ЧЗ...")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        path = tmp.name

    try:
        product_info = find_marking_product_info(raw_code)
        create_duplicate_chz_pdf(raw_code, path, product_info=product_info)
        with open(path, "rb") as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                filename=f"duplicate_chz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                caption="Дубликат ЧЗ ✅",
            )
    except DuplicateChzError as error:
        await status_message.edit_text(str(error), reply_markup=marking_menu_keyboard(update))
        return ConversationHandler.END
    except Exception as error:
        logging.exception("Ошибка генерации дубликата ЧЗ")
        await status_message.edit_text(
            f"Не удалось сформировать дубликат ЧЗ:\n{error}",
            reply_markup=marking_menu_keyboard(update),
        )
        return ConversationHandler.END
    finally:
        try:
            os.unlink(path)
        except OSError:
            logging.exception("Не удалось удалить временный PDF дубликата ЧЗ")

    await status_message.edit_text("Дубликат ЧЗ сформирован ✅", reply_markup=marking_menu_keyboard(update))
    return ConversationHandler.END


async def marking_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Действие отменено.", reply_markup=marking_menu_keyboard(update))
    elif update.message:
        await update.message.reply_text("Действие отменено.", reply_markup=marking_menu_keyboard(update))

    return ConversationHandler.END


def get_marking_handlers():
    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(trend_export_start, pattern=r"^marking:trend_export$"),
            CallbackQueryHandler(duplicate_chz_start, pattern=r"^marking:duplicate_chz$"),
        ],
        states={
            MARKING_DOCUMENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, trend_export_document_received),
                CallbackQueryHandler(marking_cancel, pattern=r"^marking:cancel$"),
            ],
            MARKING_DUPLICATE_CHZ_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, duplicate_chz_code_received),
                CallbackQueryHandler(marking_cancel, pattern=r"^marking:cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(marking_cancel, pattern=r"^marking:cancel$"),
        ],
        name="marking_trend_export",
        persistent=False,
    )

    return [conversation]
