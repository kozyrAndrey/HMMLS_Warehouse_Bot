from pathlib import Path

# ============================================================
# Исправление зависших ConversationHandler после перехода между разделами.
# Запускать из корня проекта:
# python apply_navigation_conversation_reset_fix.py
# ============================================================

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

old_import = '''from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
'''

new_import = '''from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
'''

if old_import in text:
    text = text.replace(old_import, new_import)
elif "ConversationHandler" not in text:
    raise RuntimeError("Не удалось добавить импорт ConversationHandler в bot.py")

marker = '''async def error_handler(update, context):
    logging.exception("Ошибка при обработке update", exc_info=context.error)


def main():
'''

insert = '''async def error_handler(update, context):
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
'''

if "def reset_conversations_on_navigation" not in text:
    if marker not in text:
        raise RuntimeError("Не найдено место для вставки reset_conversations_on_navigation в bot.py")
    text = text.replace(marker, insert)

anchor = '''    app.add_error_handler(error_handler)

    # Глобальная защита:
'''

replacement = '''    app.add_error_handler(error_handler)

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
'''

if "reset_conversations_on_navigation" in text and "group=-2" not in text:
    if anchor not in text:
        raise RuntimeError("Не найдено место для регистрации reset_conversations_on_navigation в bot.py")
    text = text.replace(anchor, replacement)

path.write_text(text, encoding="utf-8")

print("Готово: bot.py обновлен ✅")
