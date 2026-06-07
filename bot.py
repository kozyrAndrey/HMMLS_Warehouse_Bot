import logging

from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from core.access import access_guard
from modules.receiving.postgres_storage import init_receiving_storage
from modules.payroll.google_sheets import init_payroll_sheet
from modules.schedule.google_sheets import init_schedule_sheet
from handlers.common import (
    last_records,
    menu_last_records,
    db_status,
    show_main_menu,
    show_receiving_menu,
    show_returns_menu,
    start,
    whereami,
)
from modules.receiving.handlers import get_incoming_conversation_handler
from modules.receiving.reports import get_report_handlers
from modules.returns.handlers import get_returns_conversation_handler
from modules.payroll.handlers import get_payroll_handlers
from modules.receipts.handlers import get_receipts_handlers
from modules.schedule.handlers import get_schedule_handlers, setup_schedule_jobs


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )


async def error_handler(update, context):
    logging.exception("Ошибка при обработке update", exc_info=context.error)


async def reset_conversations_on_navigation(update, context):
    # Сбрасывает зависшие ConversationHandler при переходе в другой раздел.
    # Например: незавершенное «Оприходование» больше не перехватит текст
    # внутри раздела «Расчет ЗП».
    try:
        for handlers in context.application.handlers.values():
            for handler in handlers:
                if not isinstance(handler, ConversationHandler):
                    continue

                try:
                    key = handler._get_key(update)
                    handler._conversations.pop(key, None)
                except Exception:
                    logging.exception("Не удалось сбросить состояние ConversationHandler")
    except Exception:
        logging.exception("Не удалось выполнить общий сброс диалогов")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не указан BOT_TOKEN.")

    setup_logging()

    init_receiving_storage()

    payroll_ready = False
    try:
        payroll_ready = init_payroll_sheet()
    except Exception:
        logging.exception("Не удалось инициализировать модуль ЗП")

    if not payroll_ready:
        logging.warning(
            "Payroll Google Sheets не настроен. "
            "Модуль ЗП будет работать только после настройки PAYROLL_GOOGLE_SHEET_ID."
        )

    schedule_ready = False
    try:
        schedule_ready = init_schedule_sheet()
    except Exception:
        logging.exception("Не удалось инициализировать модуль расписания")

    if not schedule_ready:
        logging.warning(
            "Модуль расписания не инициализирован. "
            "Проверьте OPERATIONS_GOOGLE_SHEET_ID и доступ service account к новой таблице."
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

    # Сброс зависших диалогов при переходе между разделами.
    # Важно: group=-2, чтобы это сработало ДО access_guard и ДО модулей.
    app.add_handler(
        CallbackQueryHandler(
            reset_conversations_on_navigation,
            pattern=r"^(section:|menu:start$)",
        ),
        group=-2,
    )
    app.add_handler(CommandHandler("start", reset_conversations_on_navigation), group=-2)

    # Глобальная защита:
    # /start разрешен всем, чтобы пользователь увидел кнопку «Старт».
    # После нажатия «Старт» и любые дальнейшие действия доступны только сотрудникам из списка.
    # /whoami оставлен доступным, чтобы можно было узнать Telegram user_id нового сотрудника.
    app.add_handler(CallbackQueryHandler(access_guard), group=-1)
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.COMMAND
            & ~filters.Regex(r"^/(start|whoami)(\\s|$)"),
            access_guard,
        ),
        group=-1,
    )
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, access_guard),
        group=-1,
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("last", last_records))

    # Служебные команды.
    app.add_handler(CommandHandler("db_status", db_status))
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

    # Чеки.
    for handler in get_receipts_handlers():
        app.add_handler(handler)

    # Расписание.
    for handler in get_schedule_handlers():
        app.add_handler(handler)


    setup_schedule_jobs(app)

    # Кнопки меню.
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern=r"^menu:start$"))
    app.add_handler(CallbackQueryHandler(show_receiving_menu, pattern=r"^section:receiving$"))
    app.add_handler(CallbackQueryHandler(show_returns_menu, pattern=r"^section:returns$"))
    app.add_handler(CallbackQueryHandler(menu_last_records, pattern=r"^menu:last$"))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
