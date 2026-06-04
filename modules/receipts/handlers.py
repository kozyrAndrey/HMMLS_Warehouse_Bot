import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import RECEIPTS_ERROR_CHAT_ID, RECEIPTS_ERROR_TOPIC_ID
from core.keyboards import build_main_menu_keyboard, build_receipts_menu_keyboard
from modules.receipts.client import MoyskladError
from modules.receipts.service import (
    clear_receipt_link,
    find_orders_by_name,
    format_order_title,
    format_positions,
    get_attribute_value,
    get_order_with_positions,
    mark_receipt_error,
    normalize_chz_code,
    save_chz_codes_to_order,
)


(
    RECEIPT_ORDER_NAME,
    RECEIPT_SELECT_ORDER,
    RECEIPT_CHZ_CODES,
    RECEIPT_CHZ_PHOTO,
    RECEIPT_CONFIRM,
) = range(1200, 1205)


def receipt_nav_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data="receipt:cancel")]]
    )


def orders_keyboard(orders):
    rows = []
    for index, order in enumerate(orders):
        label = order.get("name", f"Заказ {index + 1}")
        rows.append([InlineKeyboardButton(label, callback_data=f"receipt:order:{index}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="receipt:cancel")])
    return InlineKeyboardMarkup(rows)


def chz_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Завершить ввод кодов", callback_data="receipt:finish_chz")],
            [InlineKeyboardButton("⚠️ Ошибка / отправить фото ЧЗ", callback_data="receipt:chz_error")],
            [InlineKeyboardButton("❌ Отмена", callback_data="receipt:cancel")],
        ]
    )


def confirm_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подготовить чек", callback_data="receipt:confirm")],
            [InlineKeyboardButton("⚠️ Ошибка / отправить фото ЧЗ", callback_data="receipt:chz_error")],
            [InlineKeyboardButton("❌ Отмена", callback_data="receipt:cancel")],
        ]
    )


async def show_receipts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "🧾 Чеки:",
        reply_markup=build_receipts_menu_keyboard(),
    )

    return ConversationHandler.END


async def receipt_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "Введите name заказа МойСклад:",
            reply_markup=receipt_nav_keyboard(),
        )
    else:
        await update.message.reply_text(
            "Введите name заказа МойСклад:",
            reply_markup=receipt_nav_keyboard(),
        )

    return RECEIPT_ORDER_NAME


async def order_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_name = update.message.text.strip()
    if not order_name:
        await update.message.reply_text("Введите непустой name заказа:")
        return RECEIPT_ORDER_NAME

    try:
        orders = await find_orders_by_name(order_name)
    except Exception as error:
        logging.exception("Не удалось найти заказ в МойСклад")
        await update.message.reply_text(
            f"Не удалось найти заказ в МойСклад ⚠️\n\n{error}",
            reply_markup=build_receipts_menu_keyboard(),
        )
        return ConversationHandler.END

    if not orders:
        await update.message.reply_text(
            "Заказы не найдены. Проверьте name заказа и введите ещё раз:",
            reply_markup=receipt_nav_keyboard(),
        )
        return RECEIPT_ORDER_NAME

    context.user_data["receipt_orders"] = orders

    if len(orders) == 1:
        context.user_data["receipt_order_index"] = 0
        return await load_selected_order(update, context, orders[0])

    await update.message.reply_text(
        "Найдено несколько заказов. Выберите нужный:",
        reply_markup=orders_keyboard(orders),
    )
    return RECEIPT_SELECT_ORDER


async def order_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index_text = query.data.replace("receipt:order:", "")
    try:
        index = int(index_text)
        order = context.user_data["receipt_orders"][index]
    except Exception:
        await query.edit_message_text("Заказ не найден в текущем диалоге. Начните заново.")
        return ConversationHandler.END

    context.user_data["receipt_order_index"] = index
    return await load_selected_order(update, context, order)


async def load_selected_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order):
    order_id = order["id"]

    try:
        order, positions = await get_order_with_positions(order_id)
    except Exception as error:
        logging.exception("Не удалось загрузить заказ МойСклад")
        await send_text(
            update,
            f"Не удалось загрузить заказ МойСклад ⚠️\n\n{error}",
            reply_markup=build_receipts_menu_keyboard(),
        )
        return ConversationHandler.END

    receipt_link = get_attribute_value(order, "Ссылка на чек HOMME+LESS")

    context.user_data["receipt_order"] = order
    context.user_data["receipt_positions"] = positions
    context.user_data["receipt_chz_codes"] = []

    text = (
        f"{format_order_title(order)}\n\n"
        f"Товары:\n{format_positions(positions)}\n\n"
    )

    if receipt_link:
        text += (
            "Поле ссылки на чек сейчас заполнено. "
            "По твоему правилу при подготовке нового чека бот очистит его.\n\n"
        )

    text += (
        "Отправляйте коды маркировки ЧЗ по одному сообщению. "
        "После ввода всех кодов нажмите «Завершить ввод кодов»."
    )

    await send_text(update, text, reply_markup=chz_keyboard())
    return RECEIPT_CHZ_CODES


async def chz_code_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = normalize_chz_code(update.message.text)
    if not code:
        await update.message.reply_text("Код пустой. Отправьте код ещё раз:", reply_markup=chz_keyboard())
        return RECEIPT_CHZ_CODES

    codes = context.user_data.setdefault("receipt_chz_codes", [])
    if code in codes:
        await update.message.reply_text(
            "Такой код уже добавлен. Отправьте другой код или завершите ввод.",
            reply_markup=chz_keyboard(),
        )
        return RECEIPT_CHZ_CODES

    codes.append(code)
    await update.message.reply_text(
        f"Код добавлен. Всего кодов: {len(codes)}",
        reply_markup=chz_keyboard(),
    )
    return RECEIPT_CHZ_CODES


async def chz_finished(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order = context.user_data.get("receipt_order") or {}
    positions = context.user_data.get("receipt_positions") or []
    codes = context.user_data.get("receipt_chz_codes") or []

    if not order:
        await query.edit_message_text(
            "Данные заказа потерялись. Начните формирование чека заново.",
            reply_markup=build_receipts_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text(
        f"{format_order_title(order)}\n\n"
        f"Товары:\n{format_positions(positions)}\n\n"
        f"Кодов ЧЗ добавлено: {len(codes)}\n\n"
        "Подтвердите подготовку чека.",
        reply_markup=confirm_keyboard(),
    )
    return RECEIPT_CONFIRM


async def receipt_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order = context.user_data.get("receipt_order") or {}
    positions = context.user_data.get("receipt_positions") or []
    codes = context.user_data.get("receipt_chz_codes") or []
    order_id = order.get("id")

    if not order_id:
        await query.edit_message_text("Данные заказа потерялись. Начните заново.")
        context.user_data.clear()
        return ConversationHandler.END

    try:
        chz_status = await save_chz_codes_to_order(order_id, positions, codes)
    except Exception as error:
        logging.exception("Не удалось записать коды ЧЗ в МойСклад")
        await query.edit_message_text(
            f"Не удалось записать коды ЧЗ в МойСклад ⚠️\n\n{error}",
            reply_markup=build_receipts_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        await clear_receipt_link(order_id)
    except Exception as error:
        logging.exception("Не удалось очистить поле ссылки на чек")
        await query.edit_message_text(
            f"Не удалось очистить поле ссылки на чек ⚠️\n\n{error}",
            reply_markup=build_receipts_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    await query.edit_message_text(
        "Черновик чека подготовлен ✅\n\n"
        "Поле ссылки на чек очищено.\n\n"
        f"Коды ЧЗ:\n{chz_status}\n\n"
        "На этом этапе бот ещё не нажимает кнопку решения МойСклад автоматически: "
        "это место оставлено отдельным шагом после проверки доступного API/механизма кнопки.",
        reply_markup=build_receipts_menu_keyboard(),
    )

    context.user_data.clear()
    return ConversationHandler.END


async def chz_error_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "Отправьте фото Честного знака. Бот запишет `error` в поле ссылки на чек "
        "и отправит ошибку в заданную тему Telegram.",
        reply_markup=receipt_nav_keyboard(),
    )
    return RECEIPT_CHZ_PHOTO


async def chz_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "Пожалуйста, отправьте именно фото ЧЗ.",
            reply_markup=receipt_nav_keyboard(),
        )
        return RECEIPT_CHZ_PHOTO

    order = context.user_data.get("receipt_order") or {}
    order_id = order.get("id")

    if not order_id:
        await update.message.reply_text("Данные заказа потерялись. Начните заново.")
        context.user_data.clear()
        return ConversationHandler.END

    try:
        await mark_receipt_error(order_id)
    except Exception as error:
        logging.exception("Не удалось записать error в поле ссылки на чек")
        await update.message.reply_text(
            f"Фото получено, но не удалось записать `error` в МойСклад ⚠️\n\n{error}",
            reply_markup=build_receipts_menu_keyboard(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    status = await send_error_photo_to_topic(context, update.effective_user, order, update.message.photo[-1].file_id)

    await update.message.reply_text(
        "Ошибка по ЧЗ зафиксирована ⚠️\n\n"
        "В поле ссылки на чек записано `error`.\n"
        f"{status}",
        reply_markup=build_receipts_menu_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def send_error_photo_to_topic(context, user, order, photo_file_id):
    if not RECEIPTS_ERROR_CHAT_ID:
        return "Тема для ошибок не настроена."

    codes = context.user_data.get("receipt_chz_codes") or []
    caption = (
        "Ошибка формирования чека / ЧЗ\n"
        f"Заказ: {order.get('name', '-')}\n"
        f"Сотрудник: {user.full_name or user.username or user.id}\n"
        f"Кодов ЧЗ в боте: {len(codes)}\n"
        "Нужно проверить фото Честного знака."
    )

    kwargs = {
        "chat_id": int(RECEIPTS_ERROR_CHAT_ID),
        "photo": photo_file_id,
        "caption": caption,
    }
    if RECEIPTS_ERROR_TOPIC_ID:
        kwargs["message_thread_id"] = int(RECEIPTS_ERROR_TOPIC_ID)

    try:
        await context.bot.send_photo(**kwargs)
        return "Фото ЧЗ отправлено в тему Telegram ✅"
    except Exception as error:
        logging.exception("Не удалось отправить фото ошибки чека в тему")
        return f"Не удалось отправить фото в тему Telegram ⚠️\nОшибка: {error}"


async def receipt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "Формирование чека отменено."

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=build_receipts_menu_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=build_receipts_menu_keyboard())

    return ConversationHandler.END


async def send_text(update, text, reply_markup=None):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


def get_receipts_handlers():
    return [
        CallbackQueryHandler(show_receipts_menu, pattern=r"^section:receipts$"),
        CallbackQueryHandler(chz_finished, pattern=r"^receipt:finish_chz$"),
        CallbackQueryHandler(receipt_confirmed, pattern=r"^receipt:confirm$"),
        ConversationHandler(
            entry_points=[
                CommandHandler("receipt", receipt_start),
                CallbackQueryHandler(receipt_start, pattern=r"^receipt:start$"),
            ],
            states={
                RECEIPT_ORDER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, order_name_received),
                    CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
                ],
                RECEIPT_SELECT_ORDER: [
                    CallbackQueryHandler(order_selected, pattern=r"^receipt:order:"),
                    CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
                ],
                RECEIPT_CHZ_CODES: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, chz_code_received),
                    CallbackQueryHandler(chz_finished, pattern=r"^receipt:finish_chz$"),
                    CallbackQueryHandler(chz_error_selected, pattern=r"^receipt:chz_error$"),
                    CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
                ],
                RECEIPT_CHZ_PHOTO: [
                    MessageHandler(filters.PHOTO, chz_photo_received),
                    MessageHandler(filters.ALL & ~filters.COMMAND, chz_photo_received),
                    CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
                ],
                RECEIPT_CONFIRM: [
                    CallbackQueryHandler(receipt_confirmed, pattern=r"^receipt:confirm$"),
                    CallbackQueryHandler(chz_error_selected, pattern=r"^receipt:chz_error$"),
                    CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", receipt_cancel),
                CallbackQueryHandler(receipt_cancel, pattern=r"^receipt:cancel$"),
            ],
        ),
    ]
