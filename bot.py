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
from modules.consumables.storage import init_consumables_storage
from modules.recruitment.storage import init_recruitment_storage
from modules.returns.storage import init_returns_storage
from modules.payroll.google_sheets import init_payroll_sheet
from modules.schedule.google_sheets import init_schedule_sheet
from modules.tasks.storage import init_tasks_storage
from handlers.common import (
    last_records,
    menu_last_records,
    db_status,
    show_employees_menu,
    show_main_menu,
    show_marking_menu,
    show_products_menu,
    show_receiving_menu,
    show_returns_menu,
    start,
    whereami,
)
from modules.receiving.handlers import get_incoming_conversation_handler
from modules.receiving.reports import get_report_handlers
from modules.returns.handlers import (
    get_returns_admin_handlers,
    get_returns_admin_message_handler,
    get_returns_admin_photo_handler,
    get_returns_conversation_handler,
)
from modules.payroll.handlers import get_payroll_handlers
from modules.schedule.handlers import get_schedule_handlers, setup_schedule_jobs
from modules.tasks.handlers import get_tasks_handlers, setup_tasks_jobs
from modules.ai_agent.weather import setup_ai_agent_jobs
from modules.consumables.handlers import get_consumables_handlers
from modules.recruitment.handlers import get_recruitment_handlers
from modules.marking.handlers import get_marking_handlers
from modules.marking.storage import init_marking_storage
from modules.reference.handlers import get_reference_handlers
from modules.employees.handlers import get_employee_handlers
from modules.products.handlers import get_product_handlers


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
    init_consumables_storage()
    init_recruitment_storage()
    init_returns_storage()
    init_marking_storage()

    try:
        init_payroll_sheet()
    except Exception:
        logging.exception("Не удалось инициализировать модуль ЗП")

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

    try:
        init_tasks_storage()
    except Exception:
        logging.exception("Не удалось инициализировать модуль задач")

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

    # Справочная информация.
    for handler in get_reference_handlers():
        app.add_handler(handler)

    # Основные сценарии.
    app.add_handler(get_incoming_conversation_handler())
    for handler in get_returns_admin_handlers():
        app.add_handler(handler)
    app.add_handler(get_returns_conversation_handler())
    app.add_handler(get_returns_admin_photo_handler(), group=1)
    app.add_handler(get_returns_admin_message_handler(), group=1)

    # Отчеты.
    for handler in get_report_handlers():
        app.add_handler(handler)

    # Расчет ЗП.
    for handler in get_payroll_handlers():
        app.add_handler(handler)

    # Расписание.
    for handler in get_schedule_handlers():
        app.add_handler(handler)

    # Задачи.
    for handler in get_tasks_handlers():
        app.add_handler(handler)

    # Расходники.
    for handler in get_consumables_handlers():
        app.add_handler(handler)

    # Резюме кандидатов.
    for handler in get_recruitment_handlers():
        app.add_handler(handler)

    # Маркировка.
    for handler in get_marking_handlers():
        app.add_handler(handler)

    # Сотрудники.
    for handler in get_employee_handlers():
        app.add_handler(handler)

    # Товары.
    for handler in get_product_handlers():
        app.add_handler(handler)

    setup_schedule_jobs(app)
    setup_tasks_jobs(app)
    setup_ai_agent_jobs(app)

    # Кнопки меню.
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern=r"^menu:start$"))
    app.add_handler(CallbackQueryHandler(show_receiving_menu, pattern=r"^section:receiving$"))
    app.add_handler(CallbackQueryHandler(show_returns_menu, pattern=r"^section:returns$"))
    app.add_handler(CallbackQueryHandler(show_marking_menu, pattern=r"^section:marking$"))
    app.add_handler(CallbackQueryHandler(show_employees_menu, pattern=r"^section:employees$"))
    app.add_handler(CallbackQueryHandler(show_products_menu, pattern=r"^section:products$"))
    app.add_handler(CallbackQueryHandler(menu_last_records, pattern=r"^menu:last$"))

    print("Bot started...")
    app.run_polling(bootstrap_retries=10)


if __name__ == "__main__":
    main()
