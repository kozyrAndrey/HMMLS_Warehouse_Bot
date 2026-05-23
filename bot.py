import logging

from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
)

from config import BOT_TOKEN
from database import init_db
from google_sheets import init_google_sheet
from payroll_google_sheets import init_payroll_sheet
from handlers.common import (
    google_status,
    last_records,
    menu_last_records,
    reset_local_db,
    show_main_menu,
    show_receiving_menu,
    show_returns_menu,
    sqlite_status,
    start,
    whereami,
)
from handlers.incoming import get_incoming_conversation_handler
from handlers.reports import get_report_handlers
from handlers.returns import get_returns_conversation_handler
from handlers.payroll import get_payroll_handlers


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )


async def error_handler(update, context):
    logging.exception("Ошибка при обработке update", exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не указан BOT_TOKEN.")

    setup_logging()

    init_db()

    google_ready = init_google_sheet()
    if not google_ready:
        logging.warning(
            "Google Sheets не настроен или google_credentials.json не найден. "
            "Записи в Google Таблицу работать не будут, пока не исправить настройки."
        )

    payroll_ready = init_payroll_sheet()
    if not payroll_ready:
        logging.warning(
            "Payroll Google Sheets не настроен. "
            "Модуль ЗП будет работать только после настройки PAYROLL_GOOGLE_SHEET_ID."
        )

    request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .build()
    )

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("last", last_records))

    # Служебные команды.
    app.add_handler(CommandHandler("google_status", google_status))
    app.add_handler(CommandHandler("sqlite_status", sqlite_status))
    app.add_handler(CommandHandler("reset_local_db", reset_local_db))
    app.add_handler(CommandHandler("whereami", whereami))

    # Основные сценарии.
    app.add_handler(get_incoming_conversation_handler())
    app.add_handler(get_returns_conversation_handler())

    # Отчеты.
    for handler in get_report_handlers():
        app.add_handler(handler)

    # Расчет ЗП.
    for handler in get_payroll_handlers():
        app.add_handler(handler)

    # Кнопки меню.
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern=r"^menu:start$"))
    app.add_handler(CallbackQueryHandler(show_receiving_menu, pattern=r"^section:receiving$"))
    app.add_handler(CallbackQueryHandler(show_returns_menu, pattern=r"^section:returns$"))
    app.add_handler(CallbackQueryHandler(menu_last_records, pattern=r"^menu:last$"))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
